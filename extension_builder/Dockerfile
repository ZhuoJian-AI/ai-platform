FROM node:22.19.0-bookworm-slim AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    NPM_CONFIG_FETCH_RETRIES=10 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=5000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000
RUN npm install --global pnpm@11.7.0
WORKDIR /app
COPY package.json tsconfig.json ./
RUN pnpm install
COPY src ./src
RUN pnpm build && pnpm prune --prod

FROM node:22.19.0-bookworm-slim
ARG DEBIAN_MIRROR=mirrors.aliyun.com
RUN sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git tar unzip \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global pnpm@11.7.0 --registry=https://registry.npmmirror.com \
        --fetch-retries=10 --fetch-retry-mintimeout=5000 --fetch-retry-maxtimeout=120000
ENV NODE_ENV=production
ENV HOME=/tmp/builder-home
WORKDIR /app
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE 8040
CMD ["node", "dist/server.js"]
