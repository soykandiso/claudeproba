FROM python:3.12-slim-bookworm

# Pinned so an image rebuild is reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

# OCR for PDFs without a text layer (decisions.md D9): Tesseract with the Macedonian
# model, and pdftoppm from poppler to render pages. No recommends, to stay small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-mkd poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: they change far less often than application code, so this
# layer stays cached across ordinary edits.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# Read at runtime by the LLM gateway: task routing and versioned prompts.
COPY config ./config
COPY prompts ./prompts
# Shipped with the image so a deploy can run `alembic upgrade head`.
COPY migrations ./migrations
COPY alembic.ini ./

# The volume mount points exist in the image so a fresh named volume inherits their owner.
RUN useradd --system --uid 10001 grants \
    && mkdir -p /srv/snapshots /srv/models \
    && chown -R grants:grants /srv/app /srv/snapshots /srv/models
USER grants

EXPOSE 8000

# Two sync workers: this runs beside Postgres and Redis on one small VPS, and the
# slow work belongs to the RQ worker, not to a request handler.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
