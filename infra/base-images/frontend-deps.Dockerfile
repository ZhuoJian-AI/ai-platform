ARG AI_PLATFORM_NODE22_BASE=node:22.19.0-bookworm-slim
FROM ${AI_PLATFORM_NODE22_BASE}

WORKDIR /app
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=600000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
