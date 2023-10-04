FROM alpine:3.17

RUN adduser -h /code -u 1000 -D -H exporter

COPY --chown=exporter:exporter requirements.txt /code/requirements.txt
COPY --chown=exporter:exporter /code            /code

ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /code
ENV PATH="/code/.local/bin:${PATH}"

RUN apk update --no-cache \
    && apk add --no-cache \
        "python3>=3.11" \
        "tzdata>=2023" \
    && apk add --no-cache --virtual .build-deps \
        "gcc=~12.2" \
        "libc-dev=~0.7" \
        "libffi-dev=~3.4" \
        "python3-dev>=3.11" \
    && su exporter -c \
        "python3 -m ensurepip --upgrade && \
        pip3 install --user -U -r requirements.txt && \
        rm requirements.txt" \
    && apk del .build-deps

USER exporter

ENTRYPOINT ["/code/exporter.py"]
