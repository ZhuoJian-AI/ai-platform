FROM node:22.19.0-bookworm-slim

ARG DEBIAN_MIRROR=mirrors.aliyun.com

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:${PATH} \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000

RUN sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "10";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' \
        > /etc/apt/apt.conf.d/80-network-retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git tar unzip \
    && rm -rf /var/lib/apt/lists/*

COPY dsh_runtime/pnpm-11.7.0.tgz /tmp/pnpm-11.7.0.tgz
RUN npm install --global /tmp/pnpm-11.7.0.tgz \
    && pnpm config set registry https://registry.npmmirror.com \
    && rm -f /tmp/pnpm-11.7.0.tgz
