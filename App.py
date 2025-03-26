import socket
import threading
import yaml
import atexit
import time
import json
import logging
import base64
from queue import Queue, Empty
from datetime import datetime
import paho.mqtt.client as mqtt
from bitstring import Bits, BitArray, BitStream, pack


class SocketMQTTClient:
    START_BYTES = bytes([6, 21, 28, 53, 114])
    _coordinatorSN = None
    _coordinatorNID = None



    def __init__(self, config_path='config.yaml'):
        self.load_config(config_path)
        self.setup_logging()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.socket_connected = False
        self.mqtt_connected = False

        self.message_queue = Queue()
        self.stop_event = threading.Event()

        self.metrics = {
            "total_messages": 0,
            "processed_successfully": 0,
            "failed_messages": 0,
            "mqtt_reconnects": 0,
            "socket_reconnects": 0
        }

        atexit.register(self.shutdown)

        self.processor_thread = threading.Thread(target=self.process_message_queue, daemon=True)
        self.processor_thread.start()

        self.metrics_thread = threading.Thread(target=self.log_metrics_periodically, daemon=True)
        self.metrics_thread.start()

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
            backoff = 1
            max_backoff = 60

            while not self.socket_connected and self.running:
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.connect((self.socket_config['host'], self.socket_config['port']))
                    self.socket_connected = True
                    logging.info(f"Connected to socket {self.socket_config['host']}:{self.socket_config['port']}")
                    logging.info("[SOCKET] Starting receive_data thread")
                    threading.Thread(target=self.receive_data, daemon=True).start()
                    return
                except Exception as e:
                    self.metrics["socket_reconnects"] += 1
                    logging.error(f"Socket connection failed: {e}")
                    logging.info(f"Retrying socket in {backoff} seconds...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)

        threading.Thread(target=try_connect, daemon=True).start()

    def checksumB(self, bytes):
        return b'%02X' % (sum(bytes) & 0xFF)

    def checksum(self, bytes):
        return (sum(bytes) & 0xFF)

    def receive_data(self):
        buffer = b''
        while self.running:
            
            try:
                logging.debug("[SOCKET] Waiting for data...")
                data = self.sock.recv(1024)
                if not data:
                    logging.warning("Socket closed by server.")
                    self.socket_connected = False
                    self.sock.close()
                    self.connect_socket()
                    break
                
                #logging.info(f"[SOCKET] Raw data received: {data.hex()}")
                buffer += data
                #logging.info(f"[SOCKET] Current Buffer: {buffer.hex()}")

                while True and len(buffer) > 0:
                    #logging.info("Buffer: " + str(buffer.hex()))
                    #logging.info("Buffer Starts With: " + str(buffer[0]) + " Buffer Length: " + str(len(buffer)))

                    while buffer[0] not in self.START_BYTES:
                        logging.info(f"[SOCKET] Sync lost. Dropping First byte: {buffer[:1].hex()}")
                        buffer = buffer[1:]
                        break
                    
                    # while not buffer.startswith(self.START_BYTES):
                    #     # Drop first byte until we sync with start bytes
                    #     logging.info(f"[SOCKET] Sync lost. Dropping byte: {buffer[:1].hex()}")
                    #     buffer = buffer[1:]
                    #     break
                    #     #if len(buffer) < len(self.START_BYTES):
                    #     #    break  # wait for more data
                    
                    #logging.info(f"[SOCKET] Synced with start bytes: {buffer[0]}")
                    
                    if len(buffer) < 2:
                        logging.info("[SOCKET] Not enough data for length byte, buffer: " + str(buffer.hex()) + " Length: " + str(len(buffer)) + ", waiting for more data...")
                        break

                    length_byte = buffer[1]
                    #logging.info(f"[SOCKET] Length byte: {length_byte}")
                    total_length =  length_byte + 1

                    if len(buffer) < total_length:
                        logging.info("[SOCKET] Not enough data for full message, buffer Length: " + str(len(buffer)) + " Total Length: " + str(total_length)+ ", waiting for more data...")
                        break


                    #messageLength = buffer[1]
                    if len(buffer) >= length_byte :
                        #logging.info(f"[SOCKET] message is long enough, checking checksum")

                        checksum = buffer[total_length - 1]
                        buffer_without_checksum = buffer[:total_length - 1]
                        #logging.info(f"[SOCKET] Checksum Byte = {checksum} Calculated Checksum: {self.checksum(buffer_without_checksum)}")
                        if checksum != self.checksum(buffer_without_checksum):
                            logging.info(f"[SOCKET] Checksum failed. Dropping message: {buffer.hex()}")
                            buffer = buffer[total_length:]
                            break

                    message = buffer[:total_length]
                    buffer = buffer[total_length:]

                    self.metrics["total_messages"] += 1
                    self.handle_binary_message(message)

            except Exception as e:
                logging.error(f"Socket receive error: {e}")
                self.socket_connected = False
                self.sock.close()
                self.connect_socket()
                break 

    def handle_binary_message(self, message: bytes):
        logging.info(f"[QUEUE] Enqueuing message: {message.hex()}")
        self.message_queue.put(message)

    def process_message_queue(self):
        logging.info("[PROCESSOR] Message processing thread started.")
        while not self.stop_event.is_set():
            try:
                message = self.message_queue.get(timeout=1)
                logging.info(f"[PROCESSOR] Processing message: {message.hex()}")

                try:
                    self._process_message_logic(message)
                    self.metrics["processed_successfully"] += 1
                    logging.info("[PROCESSOR] Message processed successfully.")
                except Exception as e:
                    self.metrics["failed_messages"] += 1
                    logging.error(f"[PROCESSOR] Failed to process message: {e}")
                    self.log_failed_message(message)

                self.message_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                logging.exception(f"[PROCESSOR] Unexpected error in processor: {e}")

    def mid_to_device_type_label(self, pti):
        match pti:
            case 178:
                return "SECURITY"
            case 192:
                return "ENVIRONMENTAL"
            case 160:
                return "SUBMETERING"
            case 1:
                return "REPEATERS"
            case 0:
                return "COORDINATORS"
            case _:
                return "UNKNOWN"
            
    def mid_and_pti_to_device_type_label(self, mid, pti):

        match mid:
            case 178:
                #"SECURITY"
                match pti:
                    case 0:
                        return "EN1210"
                    case 1:
                        return "EN1212"
                    case 2:
                        return "EN1210_60"
                    case 3:
                        return "EN1210W"
                    case 4:
                        return "EN1210SK"
                    case 5:
                        return "EN1210EOL"
                    case 6:
                        return "EN1210_240"
                    case 7:
                        return "EN1252"
                    case 8:
                        return "EE1215"
                    case 9:
                        return "EN1216"
                    case 10:
                        return "EN1212_60"
                    case 11:
                        return "EE1215W"
                    case 12:
                        return "EN1941"
                    case 13:
                        return "EN1215EOL"
                    case 14:
                        return "EN1215WEOL"
                    case 15:
                        return "EN1941_60"
                    case 16:
                        return "EN1235S"
                    case 17:
                        return "EN1235D"
                    case 18:
                        return "EN1235SF"
                    case 19:
                        return "EN1235DF"
                    case 20:
                        return "EN1233S"
                    case 21:
                        return "EN1233D"
                    case 22:
                        return "EN1224"
                    case 23:
                        return "EN1224_ON"
                    case 24:
                        return "EN1223S"
                    case 25:
                        return "EN1223D"
                    case 26:
                        return "EN1223S_60"
                    case 29:
                        return "EN1221S_60NW"
                    case 30:
                        return "EN1223SK"
                    case 32:
                        return "EN1210W_60"
                    case 33:
                        return "EN1244"
                    case 35:
                        return "EN1751"
                    case 37:
                        return "EN1752"
                    case 40:
                        return "EN1260"
                    case 41:
                        return "EN1262"
                    case 42:
                        return "EN1265"
                    case 43:
                        return "EN1261"
                    case 44:
                        return "EN1243"
                    case 45:
                        return "EN1241_60"
                    case 46:
                        return "EN1245_60"
                    case 48:
                        return "EN1249"
                    case 50:
                        return "EN1247"
                    case 57:
                        return "EN1236D"
                    case 58:
                        return "EN1238D"
                    case _:
                        return "UNKNOWN"
            case 1:
                #"REPEATERS"
                match pti:
                    case 0:
                        return "EN5040_B"
                    case 1:
                        return "EN5040_D"
                pass
            case 0:
                #"COORDINATOR"
                return "EN6040"
            
            #case 192:
            #case 160:
            case _:
                return "UNKNOWN"

    def mid_and_pti_and_flags_route(self,upperDeviceID, mid, pti, flags):
        logging.info(f"[PROCESSOR.LOGIC.mid_and_pti_and_flags_route] Device Payload Message START:[{upperDeviceID}] MID:[{mid}] PTI:[{pti}] FLAGS:[{flags.hex()}]")

        stat1 = BitArray(u=flags[0], length=8)
        stat1.reverse() # reverse bits to match documentation
        logging.info("[PROCESSOR.LOGIC] STAT1:"+ str(stat1[0]))
        stat0 = BitArray(u=flags[1], length=8)
        stat0.reverse() # reverse bits to match documentation
        logging.info("[PROCESSOR.LOGIC] STAT0:"+ str(stat0))

        self.update_homeassistant_component(upperDeviceID, 1, 1, self.bol_to_state(stat1[0]))
        self.update_homeassistant_component(upperDeviceID, 1, 2, self.bol_to_state(stat1[1]))
        self.update_homeassistant_component(upperDeviceID, 1, 3, self.bol_to_state(stat1[2]))
        self.update_homeassistant_component(upperDeviceID, 1, 4, self.bol_to_state(stat1[3]))
        self.update_homeassistant_component(upperDeviceID, 1, 5, self.bol_to_state(stat1[4]))
        self.update_homeassistant_component(upperDeviceID, 1, 6, self.bol_to_state(stat1[5]))
        self.update_homeassistant_component(upperDeviceID, 1, 7, self.bol_to_state(stat1[6]))
        self.update_homeassistant_component(upperDeviceID, 1, 8, self.bol_to_state(stat1[7]))

        self.update_homeassistant_component(upperDeviceID, 0, 1, self.bol_to_state(stat0[0]))
        self.update_homeassistant_component(upperDeviceID, 0, 2, self.bol_to_state(stat0[1]))
        self.update_homeassistant_component(upperDeviceID, 0, 3, self.bol_to_state(stat0[2]))
        self.update_homeassistant_component(upperDeviceID, 0, 4, self.bol_to_state(stat0[3]))
        self.update_homeassistant_component(upperDeviceID, 0, 5, self.bol_to_state(stat0[4]))
        self.update_homeassistant_component(upperDeviceID, 0, 6, self.bol_to_state(stat0[5]))
        self.update_homeassistant_component(upperDeviceID, 0, 7, self.bol_to_state(stat0[6]))
        self.update_homeassistant_component(upperDeviceID, 0, 8, self.bol_to_state(stat0[7]))
        
        match mid:
            case 178:
                #"SECURITY"
                match pti:
                    case 0:
                        #"EN1210"
                        
                        pass
                    case 1:
                        #"EN1212"
                        pass
                    case 2:
                        #"EN1210_60"
                        pass
                    case 3:
                        #"EN1210W"
                        pass
                    case 4:
                        #"EN1210SK"
                        pass
                    case 5:
                        #"EN1210EOL"
                        pass
                    case 6:
                        #"EN1210_240"
                        pass
                    case 7:
                        #"EN1252"
                        pass
                    case 8:
                        #"EE1215"
                        pass
                    case 9:
                        #"EN1216"
                        pass
                    case 10:
                        #"EN1212_60"
                        pass
                    case 11:
                        #"EE1215W"
                        pass
                    case 12:
                        #"EN1941"
                        pass
                    case 13:
                        #"EN1215EOL"
                        pass
                    case 14:
                        #"EN1215WEOL"
                        pass
                    case 15:
                        #"EN1941_60"
                        pass
                    case 16:
                        #"EN1235S"
                        pass
                    case 17:
                        #"EN1235D"
                        pass
                    case 18:
                        #"EN1235SF"
                        pass
                    case 19:
                        #"EN1235DF"
                        pass
                    case 20:
                        #"EN1233S"
                        pass
                    case 21:
                        #"EN1233D"
                        pass
                    case 22:
                        #"EN1224"
                        pass
                    case 23:
                        #"EN1224_ON"
                        pass
                    case 24:
                        #"EN1223S"
                        pass
                    case 25:
                        #"EN1223D"
                        pass
                    case 26:
                        #"EN1223S_60"
                        pass
                    case 29:
                        #"EN1221S_60NW"
                        pass
                    case 30:
                        #"EN1223SK"
                        pass
                    case 32:
                        #"EN1210W_60"
                        pass
                    case 33:
                        #"EN1244"
                        pass
                    case 35:
                        #"EN1751"
                        pass
                    case 37:
                        #"EN1752"
                        pass
                    case 40:
                        #"EN1260"
                        pass
                    case 41:
                        #"EN1262"
                        pass
                    case 42:
                        #"EN1265"
                        pass
                    case 43:
                        #"EN1261"
                        pass
                    case 44:
                        #"EN1243"
                        pass
                    case 45:
                        #"EN1241_60"
                        pass
                    case 46:
                        #"EN1245_60"
                        pass
                    case 48:
                        #"EN1249"
                        pass
                    case 50:
                        #"EN1247"
                        pass
                    case 57:
                        #"EN1236D"
                        pass
                    case 58:
                        #"EN1238D"
                        pass
                    case _:
                        #"UNKNOWN"
                        pass
            case 1:
                #"REPEATERS"
                match pti:
                    case 0:
                        #"EN5040_B"
                        pass
                    case 1:
                        #"EN5040_D"
                        pass
                pass
            case 0:
                #"COORDINATOR"
                #"EN6040"
                pass
            
            #case 192:
            #case 160:
            case _:
                #"UNKNOWN"                
                pass
  
    def bol_to_state(self, bol):
        return "ON" if bol else "OFF"

    def generate_homeassistant_device(self, deviceID, deviceMID, devicePTI, raw_message):
        logging.info(f"[PROCESSOR.LOGIC.generate_homeassistant_device] Device Payload Message START:[{deviceID}] MID:[{deviceMID}] PTI:[{devicePTI}]")
        

        upperDeviceID = raw_message[2:6].hex().upper() 

        topic = self.mqtt_config['topic_pub']+"/device/"+upperDeviceID+"/config"


        data = {
            "dev": {
                "ids": upperDeviceID,
                "name": self.mid_and_pti_to_device_type_label(deviceMID, devicePTI)+" - "+ str(deviceID),
                "mdl": self.mid_and_pti_to_device_type_label(deviceMID, devicePTI),
                "mf": "Inovonics",
                "sn": deviceID,
            },
            "o": {
                "name":"inovonics2mqtt",
                "sw": "0.1"
            },
            "cmps": {
                upperDeviceID+"_0_1": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "expire_after":60,
                    "unique_id":upperDeviceID+".STAT0.1",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/1/state",
                },
                upperDeviceID+"_0_2": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT0.2",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/2/state",
                },
                upperDeviceID+"_0_3": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT0.3",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/3/state",
                },
                upperDeviceID+"_0_4": {
                    "p": "binary_sensor",
                    "name":"Reset",
                    "unique_id":upperDeviceID+".STAT0.4",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/4/state",
                },
                upperDeviceID+"_0_5": {
                    "p": "binary_sensor",                                    
                    "name":"Idle",
                    "unique_id":upperDeviceID+".STAT0.5",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/5/state",
                },
                upperDeviceID+"_0_6": {
                    "p": "binary_sensor",
                    "device_class":"tamper",
                    "unique_id":upperDeviceID+".STAT0.6",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/6/state",
                },
                upperDeviceID+"_0_7": {
                    "p": "binary_sensor",
                    "device_class":"battery",
                    "unique_id":upperDeviceID+".STAT0.7",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/7/state",
                },
                upperDeviceID+"_0_8": {
                    "p": "binary_sensor",                                    
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT0.8",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/0/8/state",
                },
                
                upperDeviceID+"_1_1": {
                    "p": "binary_sensor",
                    "name":"Alarm 1",                    
                    #"expire_after":60,
                    "unique_id":upperDeviceID+".STAT1.1",
                    #"value_template": "{{ value_json[0] }}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/1/state",
                },
                upperDeviceID+"_1_2": {
                    "p": "binary_sensor",
                    "name":"Alarm 2",          
                    "unique_id":upperDeviceID+".STAT1.2",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/2/state",
                },
                upperDeviceID+"_1_3": {
                    "p": "binary_sensor",
                    "name":"Alarm 3",
                    "unique_id":upperDeviceID+".STAT1.3",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/3/state",
                },
                upperDeviceID+"_1_4": {
                    "p": "binary_sensor",
                    "name":"Alarm 4",
                    "unique_id":upperDeviceID+".STAT1.4",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/4/state",
                },
                upperDeviceID+"_1_5": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT1.5",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/5/state",
                },
                upperDeviceID+"_1_6": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT1.6",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/6/state",
                },
                upperDeviceID+"_1_7": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT1.7",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/7/state",
                },
                upperDeviceID+"_1_8": {
                    "p": "binary_sensor",
                    "name":"Reserved",
                    "unique_id":upperDeviceID+".STAT1.8",
                    "value_template": "{{ value_json[0] }}",
                    #"force_update":True,
                    "state_topic":self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/1/8/state",
                }                                
            }
        }
        
        #logging.info(f"[PROCESSOR.LOGIC] MQTT Publish Topic: {topic} Data: {data}")                       

        result = self.mqtt_client.publish(topic, json.dumps(data))
        
        if result.rc != 0:
            raise RuntimeError(f"MQTT publish failed: {result.rc}")

    def update_homeassistant_component(self, upperDeviceID, stat, bit, state):
        #logging.info(f"[PROCESSOR.LOGIC.update_homeassistant_component] Device Payload Message START:[{upperDeviceID}] STAT:[{stat}] BIT:[{bit}] STATE:[{state}]")
        #upperDeviceID = raw_message[2:6].hex().upper() 

        topic = self.mqtt_config['topic_state_pub']+"/"+upperDeviceID+"/"+str(stat)+"/"+str(bit)+"/state"
        
        result = self.mqtt_client.publish(topic, state)
        
        if result.rc != 0:
            raise RuntimeError(f"MQTT publish failed: {result.rc}")
        
    def _process_message_logic(self, message: bytes):
        logging.info(f"[PROCESSOR.LOGIC] Processing message: {message.hex()}")
        match message[0]:
            case 6: 
                #[0x06] - Header for data acknowledgement from application controller.
                #[0x02] - Message length, excluding checksum.
                #[0x08] - Checksum.                
                logging.info("[PROCESSOR.LOGIC] ACK")
            case 21: #0x15
                #[0x15] - Header for data non-acknowledgement from application controller.
                #[0x03] - Message length, excluding checksum.
                #[ERROR] - One byte error code
                #  [0x01] - Checksum incorrect
                #  [0x02] - Unrecognized header
                #  [0x03] - Serial buffer full
                #  [0x04] - Timeout(incomplete message)
                #  [0x05] - Write error
                #  [0x06] - Read error
                #  [0x07] - Invalid data
                #  [0x08] - Unrecognized command
                #  [0x09] - Outbound directed message fail
                #  [0x0A - 0xFF] - Reserved
                #[CKSUM] - Checksum.
                logging.info(f"[PROCESSOR.LOGIC] NAK Error = {message[2]} ")
            case 28: #0x1C
                # [0x1C] - Header for the check-in or status message.
                # [0x05] - Message length, excluding checksum.
                # [DATA] - The counter of unacknowledged messages sent to your application controller since the last check -in or status message.
                # [STAT1] - Status byte 1 is reserved.
                # [STAT0] - Status byte 0.
                #     Bit 7 - Receiver is jammed.All channels contain interfering signals above a predetermined level.
                #     Bit 6 - Reserved.
                #     Bit 5 - RF gateway case tamper.
                #     Bit 4 - Set when there has been no change in status since the last transmission.
                #     Bit 3 - Reset of the RF gateway microcontroller.
                #     Bit 2 - Reserved.
                #     Bit 1 - Reserved.
                #     Bit 0 - Link failure.
                # [CKSUM] - Checksum.
                logging.info(f"[PROCESSOR.LOGIC] Check-In or Status Message: {message[2:5].hex()} ")

                #stat0 = queue.peekAll()[4].toString(2).padStart(8, "0")
                s0 = BitArray(u=message[4], length=8)
                #s0.reverse() # reverse bits to match documentation
                logging.info("[PROCESSOR.LOGIC] STAT0:"+ str(s0))
                logging.info("[PROCESSOR.LOGIC] STAT0:0-Jammed="+ str(s0[0]))
                logging.info("[PROCESSOR.LOGIC] STAT0:2-CaseTamper="+ str(s0[2]))
                logging.info("[PROCESSOR.LOGIC] STAT0:3-Idle="+ str(s0[3]))
                logging.info("[PROCESSOR.LOGIC] STAT0:4-Reset="+ str(s0[4]))    
                                            
                #s1 = BitArray(u=message[4], length=8)
                #s1.reverse() # reverse bits to match documentation
                #logging.info(f"[PROCESSOR.LOGIC] Network Coordinator Message: [{message[0]}][{message[1]}][{message[2]}][{message[3]}][{message[4]} (0.{s1[0]} 3.{s1[3]} 4.{s1[4]} 5.{s1[5]} 7.{s1[7]})][{message[5]}] ")

                #device_registry.async_get_or_create(
                #    config_entry_id=config_entry.entry_id,
                #    connections={(dr.CONNECTION_NETWORK_MAC, "123ABC")},
                #    #identifiers={(DOMAIN, config.bridgeid)},
                #    manufacturer="Inovonics",
                #    model="EN6040",
                #    default_name="Coordinator",
                #)

                if(self._coordinatorSN is None):
                    try:
                        self.sock.send(b'\x34\x03\x90\xC7') # request SN
                        logging.info(f"[PROCESSOR.LOGIC] Network Coordinator SN Request Message Sent")
                    except e:
                        logging.error(f"[PROCESSOR.LOGIC] Error: {e} ")
                        pass
                else:
                    if(self._coordinatorNID is None):
                        try:
                            self.sock.send(b'\x34\x03\x82\xB9') # request NID
                            logging.info(f"[PROCESSOR.LOGIC] Network Coordinator NID Request Message Sent")
                        except e:
                            logging.error(f"[PROCESSOR.LOGIC] Error: {e} ")
                            pass
                    else:
                        pass
                        
                        # device_registry.async_get_or_create(
                        #     config_entry_id= config_entry.entry_id,
                        #     #connections={(dr.CONNECTION_NETWORK_MAC, "123ABC")},
                        #     identifiers={(DOMAIN, self._coordinatorSN)},
                        #     serial_number = int(self._coordinatorSN),
                        #     manufacturer= "Inovonics",
                        #     model= "EN6040",
                        #     default_name= "Coordinator",
                        #     name= "Inovonics Coordinator - EN6040"
                        # )

                    #self._coordinatorSN = "?"
            case 53: #0x35
                #[0x35] - Header for data non-acknowledgement from application controller.
                #[0x__] - Message length, excluding checksum.
                match (message[2]):
                    case 129: # 0x81 Report Inbound Message Format
                        logging.info("[PROCESSOR.LOGIC] Report Inbound Message Format")
                        pass
                    case 130: # 0x82 Report Network Coordinator NID
                        logging.info(f"[PROCESSOR.LOGIC] Report Network Coordinator NID: {message[3]}")
                        self._coordinatorNID = message[3]
                        pass
                    case 131: #0x83 Report List of Acceptable MID
                        logging.info("[PROCESSOR.LOGIC] Report List of Acceptable MID")
                        pass
                    case 133: #0x85 Report Check-In Setting (Network Coordinator to Application)
                        logging.info("[PROCESSOR.LOGIC] Report Check-In Setting (Network Coordinator to Application)")
                        pass
                    case 134: #0x86 Report System Outbound Status Setting (Network Coordinator to Two-Way End Devices)                                        
                        logging.info("[PROCESSOR.LOGIC] Report System Outbound Status Setting (Network Coordinator to Two-Way End Devices)")
                        pass
                    case 135: #0x87 Report Application Controller Link Supervision Time
                        logging.info("[PROCESSOR.LOGIC] Report Application Controller Link Supervision Time")
                        pass
                    case 144: #0x90 Report Network Coordinator Serial Number
                        logging.info(f"[PROCESSOR.LOGIC] Report Network Coordinator Serial Number: {int("".join([hex(i)[2:] for i in message[3:6]]), 16)}")
                        self._coordinatorSN = int("".join([hex(i)[2:] for i in message[3:6]]), 16)
                        pass                                    
                    case _:
                        pass
            case 114: #0x72 
                logging.info(f"[PROCESSOR.LOGIC] Device Payload Message START:[{message[0]}] LENGTH:[{message[1]}] ORIGINATOR:[{message[2:6].hex()}] FIRSTHOP:[{message[6:10].hex()}] TRACE_COUNT:[{message[10]}] HOP_COUNT: {message[11 + (message[10] * 4)]} MSG_CLASS: {message[12 + (message[10] * 4)]}")
                match (message[12 + (message[10] * 4)]):
                    case 0:
                        logging.info("[PROCESSOR.LOGIC] Repeater Reset Message From Device")
                        pass
                    case 2: 
                        #region Security Device - Aggregated Message
                        logging.info(f"[PROCESSOR.LOGIC] Aggregated Security Endpoint Message From Repeater:{message[2:6].hex()} FIRST_REPEATER_HOP:[{message[6:10].hex()} TRACE_COUNT:[{message[10]}] HOP_COUNT: {message[11 + (message[10] * 4)]} MSG_CLASS: {message[12 + (message[10] * 4)]}")
                        logging.info(f"[PROCESSOR.LOGIC] Aggregated Security Endpoint Message Payload MESSAGE_COUNT{message[13 + (message[10] * 4)]}")
                        pass
                    case 60: 
                        #region Temperature Device
                        logging.info("[PROCESSOR.LOGIC] Temperature SensorMessage From Device")
                        pass
                    case 62: 
                        #region Security Device - Default Message
                        logging.info(f"[PROCESSOR.LOGIC] Security Endpoint Message From Device:{message[2:6].hex()} PTI:{message[13 + (message[10] * 4)]} SIGNAL_LEVEL:{message[16 + (message[10] * 4)]} SIGNAL_MARGIN:{message[17 + (message[10] * 4)]}")    
                        #logging.info("[PROCESSOR.LOGIC] DEC SN." + str( binascii.hexlify(bytearray(message[2:6]))))  
                        
                        if not self.mqtt_connected:
                            raise RuntimeError("MQTT not connected")
                        


                        self.generate_homeassistant_device(int("".join([hex(i)[2:] for i in message[3:6]]), 16),  message[2], message[13 + (message[10] * 4)], message)
                        #self.update_homeassistant_device(message[2:6].hex().upper(),  message[2], message[13 + (message[10] * 4)], message)   
                        self.mid_and_pti_and_flags_route(message[2:6].hex().upper(), message[2], message[13 + (message[10] * 4)], message[14 + (message[10] * 4):16 + (message[10] * 4)])
                        




                    case 65:
                        #region Network Device Status Message
                        logging.info(f"[PROCESSOR.LOGIC] Network Device Status Message From Device={message[2:6].hex()} mode={message[13 + (message[10] * 4)]} level={message[16 + (message[10] * 4)]} margin={message[17 + (message[10] * 4)]}")
                        #s1 = BitArray(u=message[15 + (message[10] * 4)], length=8)
                        #s1.reverse() # reverse bits to match documentation
                        #logging.info(f"[PROCESSOR.LOGIC] STAT0 = 1.{s1[1]} 3.{s1[3]} 4.{s1[4]} 5.{s1[5]} 6.{s1[6]} 7.{s1[7]}) ")

                        
                        logging.info("[PROCESSOR.LOGIC] DEC SN - " + str( int("".join([hex(i)[2:] for i in message[3:6]]), 16)))   

                        #binascii.hexlify(bytearray(array_alpha))

                        pass
                    case _:
                        pass
            case _:
                pass







        # b64 = base64.b64encode(message).decode('ascii')

        # if not self.mqtt_connected:
        #     raise RuntimeError("MQTT not connected")

        # result = self.mqtt_client.publish(self.mqtt_config['topic_pub'], b64)
        # if result.rc != 0:
        #     raise RuntimeError(f"MQTT publish failed: {result.rc}")

    def log_failed_message(self, message: bytes):
        hex_str = message.hex()
        b64_str = base64.b64encode(message).decode('ascii')
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with open("failed_messages.log", "a") as f:
                f.write(f"[{timestamp}] Failed to process message\n")
                f.write(f"HEX:    {hex_str}\n")
                f.write(f"BASE64: {b64_str}\n\n")
        except Exception as log_error:
            logging.error(f"[LOGGING] Failed to write failed message: {log_error}")

    def log_metrics_periodically(self):
        while not self.stop_event.is_set():
            time.sleep(60)
            logging.info(f"[METRICS] Total: {self.metrics['total_messages']}, "
                         f"Success: {self.metrics['processed_successfully']}, "
                         f"Failed: {self.metrics['failed_messages']}, "
                         f"MQTT Reconnects: {self.metrics['mqtt_reconnects']}, "
                         f"Socket Reconnects: {self.metrics['socket_reconnects']}")

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
        backoff = 1
        max_backoff = self.mqtt_config.get('reconnect_interval', 60)

        while not self.mqtt_connected and self.running:
            try:
                self.mqtt_client.connect(
                    self.mqtt_config['broker'],
                    self.mqtt_config['port'],
                    keepalive=60
                )
                self.mqtt_client.loop_start()
                return
            except Exception as e:
                self.metrics['mqtt_reconnects'] += 1
                logging.error(f"[MQTT] Connection failed: {e}")
                logging.info(f"[MQTT] Retrying in {backoff} seconds...")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.mqtt_connected = True
            logging.info(f"[MQTT] Connected to {self.mqtt_config['broker']}:{self.mqtt_config['port']}")
            client.subscribe(self.mqtt_config['topic_sub'])
        else:
            logging.error(f"[MQTT] Failed to connect: {rc}")

    def on_mqtt_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        logging.warning("[MQTT] Disconnected. Reconnecting...")
        self.connect_mqtt_loop()

    def on_mqtt_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            logging.info(f"[MQTT] Received: {data}")
        except json.JSONDecodeError:
            logging.warning("[MQTT] Received invalid JSON")

    def shutdown(self):
        if self.running:
            logging.info("Shutting down client...")
            self.running = False
            self.stop_event.set()

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

            self.processor_thread.join(timeout=3)
            self.metrics_thread.join(timeout=3)

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
