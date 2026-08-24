ARG AI_PLATFORM_NODE20_BASE=node:20-bookworm-slim
ARG AI_PLATFORM_PYTHON_OFFICE_BASE=python:3.12-slim-bookworm
FROM ${AI_PLATFORM_NODE20_BASE} AS node-runtime

FROM ${AI_PLATFORM_PYTHON_OFFICE_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    NPM_CONFIG_REPLACE_REGISTRY_HOST=always \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=120000 \
    SKILL_BASE_NODE_MODULES=/opt/skill-node/node_modules \
    NODE_PATH=/opt/skill-node/node_modules

# Node comes from the official, fixed Node 20 LTS image instead of Debian's
# moving nodejs package.  Both stages use Debian bookworm, so the binary and
# its bundled npm installation share the same ABI.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt
RUN mkdir -p /opt/skill-node \
    && for attempt in 1 2 3 4 5; do \
        if npm install --prefix /opt/skill-node --omit=dev --no-audit --no-fund exceljs@4.4.0; then \
            break; \
        fi; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        sleep $((attempt * 5)); \
    done \
    && npm cache clean --force
COPY app.py .
COPY builtin_tools.py .

EXPOSE 8020
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
