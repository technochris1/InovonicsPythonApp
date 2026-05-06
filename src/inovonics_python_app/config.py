from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = "app.log"
    max_bytes: int = 1_048_576
    backup_count: int = 5


@dataclass(slots=True)
class ProcessorConfig:
    host: str
    port: int
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 60.0
    socket_timeout_seconds: float = 5.0
    queue_timeout_seconds: float = 1.0
    auto_request_coordinator_metadata: bool = True


@dataclass(slots=True)
class MQTTConfig:
    broker: str
    port: int
    client_id: str
    username: str | None = None
    password: str | None = None
    keepalive: int = 60
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 60.0
    publish_wait_timeout_seconds: float = 10.0
    startup_wait_timeout_seconds: float = 15.0
    command_topic: str | None = None
    discovery_prefix: str = "homeassistant"
    state_prefix: str = "inovonics"


@dataclass(slots=True)
class AppConfig:
    processor: ProcessorConfig
    mqtt: MQTTConfig
    logging: LoggingConfig
    config_path: Path


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)

    for candidate in (Path("config.local.yaml"), Path("config.yaml")):
        if candidate.exists():
            return candidate

    raise FileNotFoundError("No configuration file found.")


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = resolve_config_path(config_path)
    raw_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _normalize_config(raw_data)

    processor_data = data["processor"]
    mqtt_data = data["mqtt"]
    logging_data = data.get("logging", {})

    return AppConfig(
        processor=ProcessorConfig(
            host=processor_data["host"],
            port=int(processor_data["port"]),
            reconnect_initial_delay_seconds=float(
                processor_data.get("reconnect_initial_delay_seconds", 1.0)
            ),
            reconnect_max_delay_seconds=float(
                processor_data.get("reconnect_max_delay_seconds", 60.0)
            ),
            socket_timeout_seconds=float(processor_data.get("socket_timeout_seconds", 5.0)),
            queue_timeout_seconds=float(processor_data.get("queue_timeout_seconds", 1.0)),
            auto_request_coordinator_metadata=bool(
                processor_data.get("auto_request_coordinator_metadata", True)
            ),
        ),
        mqtt=MQTTConfig(
            broker=mqtt_data["broker"],
            port=int(mqtt_data.get("port", 1883)),
            client_id=mqtt_data.get("client_id", "inovonics-python-app"),
            username=mqtt_data.get("username"),
            password=mqtt_data.get("password"),
            keepalive=int(mqtt_data.get("keepalive", 60)),
            reconnect_initial_delay_seconds=float(
                mqtt_data.get("reconnect_initial_delay_seconds", 1.0)
            ),
            reconnect_max_delay_seconds=float(
                mqtt_data.get("reconnect_max_delay_seconds", 60.0)
            ),
            publish_wait_timeout_seconds=float(
                mqtt_data.get("publish_wait_timeout_seconds", 10.0)
            ),
            startup_wait_timeout_seconds=float(
                mqtt_data.get("startup_wait_timeout_seconds", 15.0)
            ),
            command_topic=mqtt_data.get("command_topic"),
            discovery_prefix=mqtt_data.get("discovery_prefix", "homeassistant"),
            state_prefix=mqtt_data.get("state_prefix", "inovonics"),
        ),
        logging=LoggingConfig(
            level=str(logging_data.get("level", "INFO")),
            file=str(logging_data.get("file", "app.log")),
            max_bytes=int(logging_data.get("max_bytes", 1_048_576)),
            backup_count=int(logging_data.get("backup_count", 5)),
        ),
        config_path=path,
    )


def _normalize_config(data: dict[str, Any]) -> dict[str, Any]:
    if "processor" in data and "mqtt" in data:
        return data

    socket_data = data.get("socket", {})
    mqtt_data = data.get("mqtt", {})

    processor = {
        "host": socket_data.get("host", "127.0.0.1"),
        "port": socket_data.get("port", 10001),
        "reconnect_initial_delay_seconds": socket_data.get("reconnect_interval", 1),
        "reconnect_max_delay_seconds": max(socket_data.get("reconnect_interval", 5), 60),
        "socket_timeout_seconds": socket_data.get("socket_timeout_seconds", 5),
        "queue_timeout_seconds": socket_data.get("queue_timeout_seconds", 1),
        "auto_request_coordinator_metadata": socket_data.get(
            "auto_request_coordinator_metadata",
            True,
        ),
    }

    mqtt = {
        "broker": mqtt_data.get("broker", "127.0.0.1"),
        "port": mqtt_data.get("port", 1883),
        "client_id": mqtt_data.get("client_id", "inovonics-python-app"),
        "username": mqtt_data.get("username"),
        "password": mqtt_data.get("password"),
        "keepalive": mqtt_data.get("keepalive", 60),
        "reconnect_initial_delay_seconds": mqtt_data.get("reconnect_interval", 1),
        "reconnect_max_delay_seconds": max(mqtt_data.get("reconnect_interval", 5), 60),
        "publish_wait_timeout_seconds": mqtt_data.get("publish_wait_timeout_seconds", 10),
        "startup_wait_timeout_seconds": mqtt_data.get("startup_wait_timeout_seconds", 15),
        "command_topic": mqtt_data.get("topic_sub"),
        "discovery_prefix": mqtt_data.get("topic_pub", "homeassistant"),
        "state_prefix": mqtt_data.get("topic_state_pub", "inovonics"),
    }

    return {
        "processor": processor,
        "mqtt": mqtt,
        "logging": data.get("logging", {}),
    }
