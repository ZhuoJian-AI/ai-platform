FROM python:3.12-slim

WORKDIR /app

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

COPY pyproject.toml ./
COPY mock ./mock

RUN pip install --no-cache-dir -e .

ENV MOCK_HOST=0.0.0.0
ENV MOCK_PORT=8010
EXPOSE 8010

CMD ["python", "-m", "mock"]
