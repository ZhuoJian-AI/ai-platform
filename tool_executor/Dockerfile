ARG AI_PLATFORM_PYTHON_OFFICE_BASE=python:3.12-slim-bookworm
FROM ${AI_PLATFORM_PYTHON_OFFICE_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

# Platform-owned file tools use LibreOffice only for reviewed conversions.
# CJK fonts prevent Chinese documents from rendering as empty boxes.
RUN sed -i 's|deb.debian.org/debian|mirrors.aliyun.com/debian|g; s|security.debian.org/debian-security|mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        libreoffice-core-nogui \
        libreoffice-writer-nogui \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt
COPY app.py .
COPY builtin_tools.py .
COPY --chmod=755 entrypoint.sh /usr/local/bin/tool-executor-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/tool-executor-entrypoint

# Fixed tools still run as an unprivileged user and receive no platform secrets.
RUN groupadd --gid 10001 toolexecutor \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/tool-home toolexecutor \
    && mkdir -p /tmp/tool-home \
    && chown -R toolexecutor:toolexecutor /tmp/tool-home /app
USER 10001:10001

EXPOSE 8020
ENTRYPOINT ["/usr/local/bin/tool-executor-entrypoint"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
