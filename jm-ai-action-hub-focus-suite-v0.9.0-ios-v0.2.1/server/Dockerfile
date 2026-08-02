FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 actionhub
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY action_hub ./action_hub
RUN pip install --upgrade pip && pip install '.[postgres]'
RUN mkdir -p /app/data/exports && chown -R actionhub:actionhub /app
USER actionhub
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)"
CMD ["uvicorn", "action_hub.main:app", "--host", "0.0.0.0", "--port", "8787"]
