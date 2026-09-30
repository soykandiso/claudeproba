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
# The English and Albanian models are for the two narrow second passes in
# normalise/pdf.py -- eng supplies the `%` that mkd has no character for, sqi reads
# the Albanian half of a bilingual call that mkd turns into nonsense. Neither ever
# reads a page on its own. A missing model is skipped rather than fatal, so an older
# image degrades to the Macedonian pass instead of failing.
# libharfbuzz-subset0 is for WeasyPrint (the report PDF, P2 s35), which already gets
# Pango from the packages above; it subsets the report's fonts and later WeasyPrint
# versions require it. The PDF's fonts are the repository's own woff2 files, never
# the system's, so no font package is installed here (app/reports/render.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-mkd tesseract-ocr-eng tesseract-ocr-sqi poppler-utils \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: they change far less often than application code, so this
# layer stays cached across ordinary edits.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# Read at runtime by the LLM gateway: task routing and versioned prompts.
COPY config ./config
COPY prompts ./prompts
# Read at runtime by stage 0: the activity classification, municipalities and
# regions. Versioned files, so the image and the repository cannot disagree.
COPY data ./data
# Shipped with the image so a deploy can run `alembic upgrade head`.
COPY migrations ./migrations
COPY alembic.ini ./

# The volume mount points exist in the image so a fresh named volume inherits their owner.
RUN useradd --system --uid 10001 grants \
    && mkdir -p /srv/snapshots /srv/models \
    && chown -R grants:grants /srv/app /srv/snapshots /srv/models
USER grants
# Fontconfig (under WeasyPrint) wants a writable cache and the app user's home does
# not exist: without this every report render logs "No writable cache directories".
# Set after USER, so the build steps above (uv, as root) do not write their cache there.
ENV XDG_CACHE_HOME=/tmp/grants-cache

EXPOSE 8000

# Two sync workers: this runs beside Postgres and Redis on one small VPS, and the
# slow work belongs to the RQ worker, not to a request handler.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
