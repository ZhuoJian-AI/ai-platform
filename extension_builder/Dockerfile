FROM node:22.19.0-bookworm-slim AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@11.7.0 --activate
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
    && corepack enable && corepack prepare pnpm@11.7.0 --activate
ENV NODE_ENV=production
ENV HOME=/tmp/builder-home
WORKDIR /app
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE 8040
CMD ["node", "dist/server.js"]
