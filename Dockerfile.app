# Приложение сверки: сборка React-страницы + FastAPI backend, который её раздаёт.
# Сборка: docker compose build app

# 1) Фронтенд (Node.js 24 LTS)
FROM node:24.21.0-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) Backend (те же версии Python и uv, что у стартового mock)
FROM ghcr.io/astral-sh/uv:0.11.6@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 AS uv
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python
COPY recon/ recon/
COPY db/ db/
COPY --from=frontend /frontend/dist frontend/dist
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "recon.api:app", "--host", "0.0.0.0", "--port", "8000"]
