# Backend image: python 3.12 + poppler (pdftotext, pdftoppm).
#
# Targets: `test` (adds the dev packages: pytest, and httpx for FastAPI's TestClient) and `runtime`
# (default, last stage). The runtime image is built from `base` only, so no test package is ever deployed.

FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8

WORKDIR /app

# Dependencies first, in a layer that only changes when pyproject.toml does (a stub package lets
# pip resolve them without the app code). No BuildKit cache mount: Railway rejects mounts without
# a service-specific id, and the layer cache already avoids re-downloading unless pyproject changes.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y reconcile-api \
    && rm -rf app

COPY app ./app
RUN pip install --no-deps .

FROM base AS test
# Dev-only packages (the `dev` extra in pyproject.toml). Only the test image has them.
RUN pip install ".[dev]"
COPY tests ./tests
CMD ["pytest"]

FROM base AS runtime
EXPOSE 8000
# Hosts such as Railway set $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
