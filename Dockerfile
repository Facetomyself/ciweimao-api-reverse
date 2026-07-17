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

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY client ./client
COPY service ./service

RUN mkdir -p /app/data /app/output_api /home/app/.ssh \
    && chmod 0700 /home/app/.ssh \
    && chown -R app:app /app /home/app/.ssh

USER app

EXPOSE 8000

CMD ["python", "-m", "service"]
