FROM node:22.19.0-bookworm-slim AS build

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000
COPY pnpm-11.7.0.tgz /tmp/pnpm-11.7.0.tgz
RUN npm install --global /tmp/pnpm-11.7.0.tgz \
    && rm -f /tmp/pnpm-11.7.0.tgz

WORKDIR /app
COPY package.json pnpm-lock.yaml tsconfig.json ./
COPY vendor ./vendor
RUN for attempt in 1 2 3 4 5; do \
        if pnpm install --frozen-lockfile --trust-lockfile; then exit 0; fi; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        sleep $((attempt * 5)); \
    done
COPY src ./src
RUN pnpm build && pnpm --config.trust-lockfile=true prune --prod

FROM node:22.19.0-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app
ARG DEBIAN_MIRROR=mirrors.aliyun.com
RUN sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "10";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' \
        > /etc/apt/apt.conf.d/80-network-retries \
    && for attempt in 1 2 3 4 5; do \
        if apt-get update \
            && apt-get install -y --no-install-recommends ca-certificates tar; then \
            break; \
        fi; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        rm -rf /var/lib/apt/lists/*; \
        sleep $((attempt * 5)); \
    done \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
RUN mkdir -p /extensions && chown node:node /extensions
USER node
EXPOSE 8030
CMD ["node", "dist/server.js"]
