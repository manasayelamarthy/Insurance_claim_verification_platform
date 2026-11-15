FROM node:22-bookworm-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY data ./data
COPY --from=frontend-build /frontend/dist ./frontend/dist

RUN pip install --no-cache-dir .

EXPOSE 8000
VOLUME ["/app/data"]

CMD ["sh", "-c", "uvicorn app.web:app --host 0.0.0.0 --port ${PORT}"]
