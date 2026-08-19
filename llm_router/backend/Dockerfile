FROM python:3.12-slim

WORKDIR /app

# 使用阿里云镜像加速 pip / uv（构建环境网络受限）
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
    PYTHONPATH=/app

RUN pip install --no-cache-dir uv

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

RUN uv pip install --system -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
