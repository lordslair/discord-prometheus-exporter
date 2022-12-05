FROM alpine:3.16

RUN adduser -h /code -u 1000 -D -H exporter

COPY                           requirements.txt  /requirements.txt
COPY --chown=exporter:exporter exporter.py       /code/exporter.py

ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

ENV LOGURU_COLORIZE='true'
ENV LOGURU_DEBUG_COLOR='<cyan><bold>'

ENV PYTHONUNBUFFERED='True'
ENV PYTHONIOENCODING='UTF-8'

WORKDIR /code
ENV PATH="/code/.local/bin:${PATH}"
ENV TZ="Europe/Paris"

RUN apk update --no-cache \
    && apk add --no-cache python3=~3.10 \
                          tzdata=~2022 \
    && apk add --no-cache --virtual .build-deps \
                                    gcc=~11.2 \
                                    libc-dev=~0.7 \
                                    libffi-dev=~3.4 \
                                    python3-dev=~3.10 \
    && su exporter -c "python3 -m ensurepip --upgrade \
                       && pip3 install --user -U -r /requirements.txt" \
    && apk del .build-deps \
    && rm /requirements.txt

USER exporter

ENTRYPOINT ["/code/exporter.py"]
