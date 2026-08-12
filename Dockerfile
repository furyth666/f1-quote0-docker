FROM python:3.13-alpine

ARG APP_UID=10001
ARG APP_GID=10001

WORKDIR /app
RUN apk add --no-cache font-noto-cjk tzdata
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY service/f1_quote0 ./f1_quote0
COPY assets ./assets
RUN mkdir -p /data && chown "${APP_UID}:${APP_GID}" /data

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASSET_DIR=/app/assets \
    STATE_PATH=/data/status.json \
    TZ=UTC

USER ${APP_UID}:${APP_GID}
ENTRYPOINT ["python", "-m", "f1_quote0"]
