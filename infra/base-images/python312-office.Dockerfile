ARG AI_PLATFORM_BACKEND_DEPS_BASE
FROM ${AI_PLATFORM_BACKEND_DEPS_BASE}

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bash ca-certificates fontconfig fonts-noto-cjk libatomic1 \
        libreoffice-calc-nogui libreoffice-impress-nogui libreoffice-writer-nogui \
        tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*
