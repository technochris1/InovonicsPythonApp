from __future__ import annotations

import argparse
import atexit
import json
import logging
import logging.handlers
import threading
import time

import paho.mqtt.client as mqtt
from inovonics_echostream_processor import (
    AckEvent,
    CoordinatorNetworkIdEvent,
    CoordinatorSerialNumberEvent,
    CoordinatorStatusEvent,
    EchoStreamProcessorCore,
    NakEvent,
    NetworkStatusEvent,
    ProcessorEvent,
    RepeaterResetEvent,
    SecurityMessageEvent,
    UnknownMessageEvent,
)
from inovonics_echostream_processor.transports.cpython_socket import (
    SocketProcessorConfig,
    SocketProcessorService,
)

from inovonics_python_app.config import (
    AppConfig,
    LoggingConfig,
    load_config,
    render_config_for_logging,
)
from inovonics_python_app.home_assistant import (
    build_discovery_payload,
    discovery_topic,
    iter_state_messages,
)
from inovonics_python_app.version import __version__


def configure_logging(config: LoggingConfig) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))
    root_logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        config.file,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


class MqttBridgeApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._mqtt_connected = threading.Event()
        self._mqtt_connect_lock = threading.Lock()
        self._mqtt_connect_thread: threading.Thread | None = None
        self._running = False
        self._known_devices: set[str] = set()

        self.mqtt_client = mqtt.Client(client_id=self.config.mqtt.client_id)
        if self.config.mqtt.username:
            self.mqtt_client.username_pw_set(
                self.config.mqtt.username,
                self.config.mqtt.password or "",
            )

        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

        self.processor = SocketProcessorService(
            SocketProcessorConfig(
                host=self.config.processor.host,
                port=self.config.processor.port,
                reconnect_initial_delay_seconds=self.config.processor.reconnect_initial_delay_seconds,
                reconnect_max_delay_seconds=self.config.processor.reconnect_max_delay_seconds,
                socket_timeout_seconds=self.config.processor.socket_timeout_seconds,
                queue_timeout_seconds=self.config.processor.queue_timeout_seconds,
            ),
            core=EchoStreamProcessorCore(
                auto_request_coordinator_metadata=self.config.processor.auto_request_coordinator_metadata,
            ),
            logger=logging.getLogger("EchoStreamProcessor"),
        )
        self.processor.add_event_handler(self.handle_processor_event)

        atexit.register(self.stop)

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        self.mqtt_client.loop_start()
        self._schedule_mqtt_connect()

        if not self._mqtt_connected.wait(self.config.mqtt.startup_wait_timeout_seconds):
            self.logger.warning(
                "MQTT did not connect within %.1f seconds. Continuing startup.",
                self.config.mqtt.startup_wait_timeout_seconds,
            )

        self.processor.start()
        self.logger.info("Bridge started using config %s", self.config.config_path)

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        self.processor.stop()
        self._mqtt_connected.clear()

        try:
            self.mqtt_client.disconnect()
        except Exception:
            self.logger.debug("MQTT disconnect raised during shutdown.", exc_info=True)

        try:
            self.mqtt_client.loop_stop()
        except Exception:
            self.logger.debug("MQTT loop_stop raised during shutdown.", exc_info=True)

    def _schedule_mqtt_connect(self) -> None:
        with self._mqtt_connect_lock:
            if self._mqtt_connect_thread is not None and self._mqtt_connect_thread.is_alive():
                return

            self._mqtt_connect_thread = threading.Thread(
                target=self._mqtt_connect_loop,
                daemon=True,
                name="mqtt-connect",
            )
            self._mqtt_connect_thread.start()

    def _mqtt_connect_loop(self) -> None:
        backoff = self.config.mqtt.reconnect_initial_delay_seconds

        try:
            while self._running and not self._mqtt_connected.is_set():
                try:
                    self.mqtt_client.connect(
                        self.config.mqtt.broker,
                        self.config.mqtt.port,
                        keepalive=self.config.mqtt.keepalive,
                    )
                    return
                except OSError as exc:
                    self.logger.warning(
                        "MQTT connection failed: %s. Retrying in %.1f seconds.",
                        exc,
                        backoff,
                    )
                    if self._stop_event.wait(backoff):
                        return
                    backoff = min(backoff * 2, self.config.mqtt.reconnect_max_delay_seconds)
        finally:
            with self._mqtt_connect_lock:
                if self._mqtt_connect_thread is threading.current_thread():
                    self._mqtt_connect_thread = None

    def on_mqtt_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            self.logger.error("MQTT broker rejected the connection with rc=%s", rc)
            return

        self._mqtt_connected.set()
        self.logger.info(
            "Connected to MQTT broker %s:%s",
            self.config.mqtt.broker,
            self.config.mqtt.port,
        )

        if self.config.mqtt.command_topic:
            client.subscribe(self.config.mqtt.command_topic)

    def on_mqtt_disconnect(self, client, userdata, rc) -> None:
        self._mqtt_connected.clear()
        if self._running:
            self.logger.warning("MQTT disconnected with rc=%s. Reconnecting.", rc)
            self._schedule_mqtt_connect()

    def on_mqtt_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            self.logger.warning("Ignored invalid MQTT JSON on topic %s", msg.topic)
            return

        self.logger.info("Received MQTT command on %s: %s", msg.topic, payload)

    def publish(self, topic: str, payload: str, *, retain: bool) -> None:
        if not self._mqtt_connected.wait(self.config.mqtt.publish_wait_timeout_seconds):
            raise RuntimeError("MQTT not connected")

        result = self.mqtt_client.publish(
            topic=topic,
            payload=payload,
            qos=1,
            retain=retain,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed: rc={result.rc} topic={topic}")

        result.wait_for_publish()

    def handle_processor_event(self, event: ProcessorEvent) -> None:
        if isinstance(event, SecurityMessageEvent):
            self._publish_security_event(event)
            return

        if isinstance(event, CoordinatorStatusEvent):
            self.logger.info(
                "Coordinator status: unacked=%s reset=%s jammed=%s link_failure=%s",
                event.unacknowledged_count,
                event.reset,
                event.jammed,
                event.link_failure,
            )
            return

        if isinstance(event, CoordinatorSerialNumberEvent):
            self.logger.info("Coordinator serial number: %s", event.serial_number)
            return

        if isinstance(event, CoordinatorNetworkIdEvent):
            self.logger.info("Coordinator network id: %s", event.network_id)
            return

        if isinstance(event, RepeaterResetEvent):
            self.logger.info(
                "Repeater reset received from %s via %s",
                event.device_uid_hex,
                event.first_hop_hex,
            )
            return

        if isinstance(event, NetworkStatusEvent):
            self.logger.info(
                "Network status from %s mode=%s level=%s margin=%s",
                event.device_uid_hex,
                event.mode,
                event.signal_level,
                event.signal_margin,
            )
            return

        if isinstance(event, NakEvent):
            self.logger.warning("EchoStream NAK received with error code %s", event.error_code)
            return

        if isinstance(event, AckEvent):
            self.logger.debug("EchoStream ACK received.")
            return

        if isinstance(event, UnknownMessageEvent):
            self.logger.debug("Unknown EchoStream message: %s", event.reason)

    def _publish_security_event(self, event: SecurityMessageEvent) -> None:
        self._publish_discovery_if_needed(event)

        for topic, state in iter_state_messages(
            event,
            state_prefix=self.config.mqtt.state_prefix,
        ):
            self.publish(topic, state, retain=True)

    def _publish_discovery_if_needed(self, event: SecurityMessageEvent) -> None:
        if event.device_uid_hex in self._known_devices:
            return

        payload = build_discovery_payload(
            event,
            state_prefix=self.config.mqtt.state_prefix,
            app_name="inovonics-python-app",
            app_version=__version__,
        )
        topic = discovery_topic(self.config.mqtt.discovery_prefix, event.device_uid_hex)
        self.publish(topic, json.dumps(payload), retain=True)
        self._known_devices.add(event.device_uid_hex)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Inovonics MQTT bridge.")
    parser.add_argument(
        "--config",
        help="Path to a YAML configuration file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)
    config_path, rendered_config = render_config_for_logging(config.config_path)
    logging.getLogger(__name__).info(
        "Loaded config from %s:\n%s",
        config_path,
        rendered_config,
    )

    app = MqttBridgeApp(config)
    app.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Interrupted by user.")
    finally:
        app.stop()

    return 0
