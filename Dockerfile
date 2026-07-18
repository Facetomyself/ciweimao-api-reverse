FROM docker.m.daocloud.io/library/python:3.13-slim

ARG APP_UID=10001
ARG APP_GID=10001
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home app

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --index-url "${PIP_INDEX_URL}" \
    --no-cache-dir -r requirements.txt

COPY client ./client
COPY service ./service

RUN mkdir -p /app/data /app/output_api \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["python", "-m", "service"]
