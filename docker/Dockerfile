FROM alpine:3.14
MAINTAINER @Lordslair

COPY requirements.txt /requirements.txt
COPY exporter.py     /exporter.py

ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk update --no-cache \
    && apk add --no-cache python3 py3-pip \
    && apk add --no-cache --virtual .build-deps \
                                    gcc \
                                    libc-dev \
                                    libffi-dev \
                                    python3-dev \
                                    tzdata \
    && pip3 install -U -r /requirements.txt \
    && cp /usr/share/zoneinfo/Europe/Paris /etc/localtime \
    && apk del .build-deps \
    && rm /requirements.txt

ENTRYPOINT ["/exporter.py"]
