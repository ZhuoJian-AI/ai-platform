FROM node:20-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    SKILL_BASE_NODE_MODULES=/opt/skill-node/node_modules \
    NODE_PATH=/opt/skill-node/node_modules

# Node comes from the official, fixed Node 20 LTS image instead of Debian's
# moving nodejs package.  Both stages use Debian bookworm, so the binary and
# its bundled npm installation share the same ABI.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bash ca-certificates fontconfig fonts-noto-cjk libatomic1 \
        libreoffice-calc-nogui libreoffice-impress-nogui libreoffice-writer-nogui \
        tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /opt/skill-node \
    && npm install --prefix /opt/skill-node --omit=dev --no-audit --no-fund exceljs@4.4.0 \
    && npm cache clean --force
COPY app.py .
COPY builtin_tools.py .

EXPOSE 8020
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
