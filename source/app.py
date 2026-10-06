"""Read-only HTTP fixture. This is not 1C and does not implement full OData."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Interview HTTP fixture (NOT 1C)")
DATA = json.loads((Path(__file__).parent.parent / "fixtures/data.json").read_text())


@app.get("/health")
def health():
    return {"status": "ok", "source": "mock", "dataset_version": "1"}


@app.get("/{collection}")
def collection(collection: str):
    if collection not in DATA:
        raise HTTPException(404, "Unknown collection")
    return {"value": DATA[collection]}
