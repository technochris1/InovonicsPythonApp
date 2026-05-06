FROM python:3.12-slim-bookworm AS builder

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && python -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.12-slim-bookworm

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    INOVONICS_PROCESSOR_HOST=processor \
    INOVONICS_PROCESSOR_PORT=10001 \
    INOVONICS_MQTT_BROKER=mqtt \
    INOVONICS_MQTT_PORT=1883 \
    INOVONICS_MQTT_CLIENT_ID=inovonics-python-app \
    INOVONICS_MQTT_USERNAME= \
    INOVONICS_MQTT_PASSWORD=password \
    INOVONICS_MQTT_COMMAND_TOPIC=homeassistant \
    INOVONICS_MQTT_DISCOVERY_PREFIX=homeassistant \
    INOVONICS_MQTT_STATE_PREFIX=inovonics \
    INOVONICS_BIT_COALESCING_ENABLED=true \
    INOVONICS_BIT_COALESCING_QUIET_PERIOD_MS=500 \
    INOVONICS_BIT_COALESCING_MAX_HOLD_MS=2000 \
    INOVONICS_BIT_COALESCING_IDLE_TTL_MS=900000 \
    INOVONICS_BIT_COALESCING_FLUSH_INTERVAL_MS=250 \
    INOVONICS_LOGGING_LEVEL=INFO

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . .

CMD ["python", "App.py"]
