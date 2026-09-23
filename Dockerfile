FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AKIM_DATA_GATE_DIR=/var/lib/akim/data-gate
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY engine ./engine
COPY data ./data
COPY data_gate ./data_gate
COPY services ./services
COPY ai ./ai
COPY api ./api
COPY scripts ./scripts
RUN python -m pip install --no-cache-dir -c requirements.lock . \
    && useradd --uid 10001 --create-home akim \
    && mkdir -p /var/lib/akim/data-gate \
    && chown -R akim:akim /var/lib/akim
USER akim
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
