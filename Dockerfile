FROM python:3.12-slim-bookworm

# Pinned so an image rebuild is reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

# Dependencies first: they change far less often than application code, so this
# layer stays cached across ordinary edits.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# Shipped with the image so a deploy can run `alembic upgrade head`.
COPY migrations ./migrations
COPY alembic.ini ./

RUN useradd --system --uid 10001 grants && chown -R grants:grants /srv/app
USER grants

EXPOSE 8000

# Two sync workers: this runs beside Postgres and Redis on one small VPS, and the
# slow work belongs to the RQ worker, not to a request handler.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
