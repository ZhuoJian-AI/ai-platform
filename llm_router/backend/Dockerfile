FROM python:3.12-slim

WORKDIR /app

# 使用阿里云镜像加速 pip，并提高受限构建网络下的容错能力。
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PYTHONPATH=/app

# 旧版 Word/Excel/PowerPoint 统一转为现代中间格式后复用 Python 解析器。
# 使用无界面组件，避免在服务端安装桌面环境。
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-noto-cjk \
        libreoffice-writer-nogui \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
