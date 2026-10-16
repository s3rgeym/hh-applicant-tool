FROM python:3.13-alpine

RUN apk add --no-cache tzdata

ARG UID=1000
ARG GID=1000
RUN addgroup -g $GID docker && \
    adduser -D -u $UID -G docker -s /bin/sh docker

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN apk add --no-cache --virtual .build-deps gcc musl-dev && \
    pip install --no-cache-dir -e '.' && \
    apk del .build-deps

ENV CONFIG_DIR=/config

RUN mkdir -p /config && chown docker:docker /config
VOLUME /config

USER docker

ENTRYPOINT ["hh-applicant-tool"]
