# Stage 1: Build
FROM python:3.11-alpine3.22 as builder

# Create user and group
RUN adduser -h /code -u 1000 -D -H exporter

# Copy only requirements to leverage Docker cache
COPY --chown=exporter:exporter requirements.txt /code/requirements.txt

# Install dependencies
RUN apk update --no-cache \
    && apk add --no-cache --virtual .build-deps \
        "gcc>=14" \
        "libc-dev>=0.7" \
    && su exporter -c "pip3 install --user -U -r /code/requirements.txt"

# Stage 2: Final
FROM python:3.11-alpine3.22

# Create user and group
RUN adduser -h /code -u 1000 -D -H exporter

# Set environment variables
ENV PATH="/code/.local/bin:${PATH}"

# Copy the necessary files from the build stage
COPY --chown=exporter:exporter --from=builder /code /code

# Copy application code
COPY --chown=exporter:exporter /code   /code

# Set working directory
WORKDIR /code

# Set user
USER exporter

# Entry point
ENTRYPOINT ["/code/exporter.py"]