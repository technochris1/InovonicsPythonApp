import socket
import threading
import yaml
import atexit
import time
import json
import logging
import paho.mqtt.client as mqtt



class SocketMQTTClient:
    def __init__(self, config_path='config.yaml'):
        self.load_config(config_path)
        self.setup_logging()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.socket_connected = False
        self.mqtt_connected = False
        atexit.register(self.shutdown)

        self.mqtt_client = mqtt.Client(client_id=self.mqtt_config['client_id'])
        self.setup_mqtt()

    def load_config(self, path):
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
        self.socket_config = config['socket']
        self.mqtt_config = config['mqtt']
        self.logging_config = config.get('logging', {})

    def setup_logging(self):
        level = getattr(logging, self.logging_config.get('level', 'INFO').upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(self.logging_config.get('file', 'app.log')),
                logging.StreamHandler()
            ]
        )

    def connect_socket(self):
        def try_connect():
            while not self.socket_connected and self.running:
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.connect((self.socket_config['host'], self.socket_config['port']))
                    self.socket_connected = True
                    logging.info(f"Connected to socket {self.socket_config['host']}:{self.socket_config['port']}")
                    threading.Thread(target=self.receive_data, daemon=True).start()
                except Exception as e:
                    logging.error(f"Socket connection failed: {e}")
                    time.sleep(self.socket_config.get('reconnect_interval', 5))

        threading.Thread(target=try_connect, daemon=True).start()

    def receive_data(self):
        while self.running:
            try:
                data = self.sock.recv(1024)
                if not data:
                    logging.warning("Socket closed by server.")
                    self.socket_connected = False
                    self.sock.close()
                    self.connect_socket()
                    break

                logging.info(f"[SOCKET] Received raw: {repr(data)}")

                # Try to parse JSON directly from bytes
                try:
                    json_data = json.loads(data)
                    self.handle_command(json_data, source='socket')
                except (json.JSONDecodeError, TypeError):
                    logging.info("[SOCKET] Treating as raw/plain bytes.")
                    self.handle_plain_socket_message(data)

            except Exception as e:
                logging.error(f"Socket receive error: {e}")
                self.socket_connected = False
                self.sock.close()
                self.connect_socket()
                break

    def handle_plain_socket_message(self, message: bytes):
        # Try to decode just for logging / text commands
        try:
            text = message.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = repr(message)

        logging.info(f"[SOCKET] Plain message (decoded): {text}")

        if text.lower() == "ping":
            self.send("pong")
        elif text.lower() == "status":
            status = {
                "socket_connected": self.socket_connected,
                "mqtt_connected": self.mqtt_connected
            }
            self.send(json.dumps(status))
        else:
            logging.info(f"[SOCKET] No command matched. Raw message: {repr(message)}")

    def send(self, message):
        if not self.socket_connected:
            logging.warning("Socket not connected. Cannot send.")
            return
        try:
            self.sock.sendall(message.encode())
        except Exception as e:
            logging.error(f"Socket send error: {e}")
            self.socket_connected = False
            self.sock.close()
            self.connect_socket()

    def setup_mqtt(self):
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect

        if self.mqtt_config.get("username"):
            self.mqtt_client.username_pw_set(
                self.mqtt_config['username'],
                self.mqtt_config.get('password', '')
            )

        threading.Thread(target=self.connect_mqtt_loop, daemon=True).start()

    def connect_mqtt_loop(self):
        while not self.mqtt_connected and self.running:
            try:
                self.mqtt_client.connect(self.mqtt_config['broker'], self.mqtt_config['port'], keepalive=60)
                self.mqtt_client.loop_start()
                return
            except Exception as e:
                logging.error(f"MQTT connection failed: {e}")
                time.sleep(self.mqtt_config.get('reconnect_interval', 5))

    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.mqtt_connected = True
            logging.info(f"[MQTT] Connected to broker at {self.mqtt_config['broker']}:{self.mqtt_config['port']}")
            client.subscribe(self.mqtt_config['topic_sub'])
            logging.info(f"[MQTT] Subscribed to topic: {self.mqtt_config['topic_sub']}")
        else:
            logging.error(f"[MQTT] Failed to connect with code {rc}")

    def on_mqtt_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        logging.warning("[MQTT] Disconnected. Reconnecting...")
        self.connect_mqtt_loop()

    # def on_mqtt_message(self, client, userdata, msg):
    #     try:
    #         message = msg.payload.decode()
    #         logging.info(f"[MQTT] Received on '{msg.topic}': {message}")
    #         data = json.loads(message)
    #         self.handle_command(data, source='mqtt')
    #     except json.JSONDecodeError:
    #         logging.warning("[MQTT] Received invalid JSON.")
    def on_mqtt_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            logging.info(f"[MQTT] Received JSON on '{msg.topic}': {data}")
            self.handle_command(data, source='mqtt')
        except json.JSONDecodeError:
            logging.warning("[MQTT] Received invalid JSON.")

    def handle_command(self, data, source='mqtt'):
        command = data.get('command')
        payload = data.get('payload')

        if not command:
            logging.warning(f"[{source.upper()}] Missing 'command' in message.")
            return

        logging.info(f"[{source.upper()}] Command received: {command}, Payload: {payload}")

        if command == "ping":
            response = {"command": "pong", "payload": "I am alive."}
            self.send_response(response, source)

        elif command == "status":
            response = {
                "command": "status",
                "payload": {
                    "socket_connected": self.socket_connected,
                    "mqtt_connected": self.mqtt_connected
                }
            }
            self.send_response(response, source)

        elif command == "echo":
            response = {"command": "echo", "payload": payload}
            self.send_response(response, source)

        else:
            logging.warning(f"[{source.upper()}] Unknown command: {command}")

    def send_response(self, data, destination='mqtt'):
        message = json.dumps(data)
        if destination == 'socket' and self.socket_connected:
            self.send(message)
        elif destination == 'mqtt' and self.mqtt_connected:
            self.mqtt_client.publish(self.mqtt_config['topic_pub'], message)
        else:
            logging.warning(f"[{destination.upper()}] Not connected. Cannot send response.")

    def shutdown(self):
        if self.running:
            logging.info("Shutting down client...")
            self.running = False
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            logging.info("Clean shutdown complete.")


if __name__ == "__main__":
    client = SocketMQTTClient()
    client.connect_socket()

    try:
        while client.running:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
    finally:
        client.shutdown()
