ARG AI_PLATFORM_PYTHON_BASE=python:3.12-slim
FROM ${AI_PLATFORM_PYTHON_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10

COPY mock/pyproject.toml mock/README.md ./
COPY mock/mock ./mock
RUN python -m pip install --no-cache-dir --retries 10 --timeout 600 -e .
