"""HTTP API для веб-страницы. Импорт и сверка — два отдельных действия.

POST /api/import            → 202 {job_id}  импорт 1С → PostgreSQL (роль importer)
POST /api/reconcile {period}→ 202 {job_id}  сверка за месяц, отчёт сохраняется в recon_runs
GET  /api/jobs/{job_id}     → состояние: running | finished, результат импорта или отчёт

Задачи выполняются в фоне (BackgroundTasks) и хранятся в памяти процесса — очередь
по условию не нужна; итоги дополнительно сохраняются в БД (import_runs, recon_runs).
Логика та же, что у CLI/агента: run_import и run_reconciliation.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from recon import config
from recon.db import apply_schema
from recon.importer import run_import
from recon.reconcile import PERIOD_RE, run_reconciliation, save_report_db
from recon.source import SourceClient, SourceError

log = logging.getLogger("recon.api")
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"


class ReconcileRequest(BaseModel):
    period: str = Field(pattern=PERIOD_RE.pattern, examples=["2026-08"])


class Jobs:
    """Потокобезопасный реестр фоновых задач в памяти."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        job = {
            "job_id": str(uuid.uuid4()),
            "kind": kind,
            "params": params,
            "status": "running",
            "result": None,
        }
        with self._lock:
            self._jobs[job["job_id"]] = job
        return dict(job)

    def finish(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id].update(status="finished", result=result)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


def create_app(
    source_factory: Callable[[], SourceClient] | None = None,
    importer_dsn: Callable[[], str] = config.importer_dsn,
    reader_dsn: Callable[[], str] = config.reader_dsn,
    init_schema: bool = True,
) -> FastAPI:
    make_source = source_factory or (lambda: SourceClient(config.source_settings()))
    jobs = Jobs()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if init_schema:
            apply_schema(importer_dsn())  # воспроизводимое создание схемы при старте
        yield

    app = FastAPI(title="Сверка 1С ↔ PostgreSQL", lifespan=lifespan)

    def import_job(job_id: str) -> None:
        try:
            result = run_import(make_source(), importer_dsn()).as_dict()
        except SourceError as error:
            result = {"status": "error", "error": f"Источник: {error}"}
        except Exception as error:  # noqa: BLE001 — любая ошибка должна дойти до UI
            log.exception("import failed")
            result = {"status": "error", "error": f"{type(error).__name__}: {error}"}
        jobs.finish(job_id, result)

    def reconcile_job(job_id: str, period: str) -> None:
        try:
            report = run_reconciliation(period, make_source(), reader_dsn())
            save_report_db(report, importer_dsn())
            result = report.as_dict()
        except SourceError as error:
            result = {"status": "error", "period": period, "error": f"Источник 1С: {error}"}
        except Exception as error:  # noqa: BLE001
            log.exception("reconcile failed")
            result = {
                "status": "error",
                "period": period,
                "error": f"{type(error).__name__}: {error}",
            }
        jobs.finish(job_id, result)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "source": config.source_settings().base_url}

    @app.post("/api/import", status_code=202)
    def start_import(background: BackgroundTasks) -> dict[str, Any]:
        job = jobs.create("import", {})
        background.add_task(import_job, job["job_id"])
        return job

    @app.post("/api/reconcile", status_code=202)
    def start_reconcile(request: ReconcileRequest, background: BackgroundTasks) -> dict[str, Any]:
        job = jobs.create("reconcile", {"period": request.period})
        background.add_task(reconcile_job, job["job_id"], request.period)
        return job

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Задача не найдена")
        return job

    if STATIC_DIR.is_dir():  # собранный React-фронтенд (п. 4)
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app


app = create_app()
