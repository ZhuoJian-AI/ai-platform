ARG AI_PLATFORM_PYTHON_OFFICE_BASE=python:3.12-slim-bookworm
FROM ${AI_PLATFORM_PYTHON_OFFICE_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY llm_router/backend/pyproject.toml ./
RUN python -m pip install --no-cache-dir --retries 10 --timeout 600 -e ".[dev]"
