ARG AI_PLATFORM_NODE22_BASE=node:22.19.0-bookworm-slim
FROM ${AI_PLATFORM_NODE22_BASE} AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000
COPY pnpm-11.7.0.tgz /tmp/pnpm-11.7.0.tgz
RUN if ! command -v pnpm >/dev/null 2>&1; then \
        npm install --global /tmp/pnpm-11.7.0.tgz; \
    fi \
    && pnpm config set registry https://registry.npmmirror.com \
    && rm -f /tmp/pnpm-11.7.0.tgz
WORKDIR /app
COPY package.json tsconfig.json ./
RUN for attempt in 1 2 3 4 5; do \
        if pnpm install; then exit 0; fi; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        sleep $((attempt * 5)); \
    done
COPY src ./src
RUN pnpm build && pnpm --config.trust-lockfile=true prune --prod

FROM ${AI_PLATFORM_NODE22_BASE}
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    npm_config_registry=https://registry.npmmirror.com
ENV NODE_ENV=production
ENV HOME=/tmp/builder-home
WORKDIR /app
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE 8040
CMD ["node", "dist/server.js"]
