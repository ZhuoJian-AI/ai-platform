ARG AI_PLATFORM_NODE20_BASE=node:20-bookworm-slim
ARG AI_PLATFORM_PYTHON_OFFICE_BASE=python:3.12-slim-bookworm
FROM ${AI_PLATFORM_NODE20_BASE} AS node-runtime

FROM ${AI_PLATFORM_PYTHON_OFFICE_BASE}

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10 \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=600000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000 \
    SKILL_BASE_NODE_MODULES=/opt/skill-node/node_modules \
    NODE_PATH=/opt/skill-node/node_modules

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY skill_runner/requirements.txt /tmp/skill-runner-requirements.txt
RUN python -m pip install --no-cache-dir --retries 10 --timeout 600 \
        -r /tmp/skill-runner-requirements.txt \
    && rm -f /tmp/skill-runner-requirements.txt
RUN mkdir -p /opt/skill-node \
    && npm install --prefix /opt/skill-node --omit=dev --no-audit --no-fund exceljs@4.4.0 \
    && npm cache clean --force
