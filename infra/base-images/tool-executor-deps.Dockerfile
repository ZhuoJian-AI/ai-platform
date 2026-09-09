ARG AI_PLATFORM_PYTHON_OFFICE_BASE=python:3.12-slim-bookworm
FROM ${AI_PLATFORM_PYTHON_OFFICE_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10

COPY tool_executor/requirements.txt /tmp/tool-executor-requirements.txt
RUN python -m pip install --no-cache-dir --retries 10 --timeout 600 \
        -r /tmp/tool-executor-requirements.txt \
    && rm -f /tmp/tool-executor-requirements.txt \
    && groupadd --gid 10001 toolexecutor \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /tmp/tool-home toolexecutor \
    && mkdir -p /tmp/tool-home \
    && chown -R toolexecutor:toolexecutor /tmp/tool-home /app

USER 10001:10001
