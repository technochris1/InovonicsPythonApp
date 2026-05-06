from __future__ import annotations

from inovonics_echostream_processor.events import SecurityMessageEvent


COMPONENT_DEFINITIONS: dict[tuple[int, int], dict[str, str]] = {
    (0, 1): {"name": "Reserved"},
    (0, 2): {"name": "Reserved"},
    (0, 3): {"name": "Reserved"},
    (0, 4): {"name": "Reset"},
    (0, 5): {"name": "Idle"},
    (0, 6): {"name": "Case Tamper", "device_class": "tamper"},
    (0, 7): {"name": "Battery Low", "device_class": "battery"},
    (0, 8): {"name": "Reserved"},
    (1, 1): {"name": "Alarm 1"},
    (1, 2): {"name": "Alarm 2"},
    (1, 3): {"name": "Alarm 3"},
    (1, 4): {"name": "Alarm 4"},
    (1, 5): {"name": "Reserved"},
    (1, 6): {"name": "Reserved"},
    (1, 7): {"name": "Reserved"},
    (1, 8): {"name": "Reserved"},
}


def discovery_topic(discovery_prefix: str, device_uid_hex: str) -> str:
    return f"{discovery_prefix}/device/{device_uid_hex}/config"


def state_topic(state_prefix: str, device_uid_hex: str, group: int, bit: int) -> str:
    return f"{state_prefix}/{device_uid_hex}/{group}/{bit}/state"


def bool_to_state(flag: bool) -> str:
    return "ON" if flag else "OFF"


def build_discovery_payload(
    event: SecurityMessageEvent,
    *,
    state_prefix: str,
    app_name: str,
    app_version: str,
) -> dict[str, object]:
    components: dict[str, dict[str, str]] = {}

    for (group, bit), metadata in COMPONENT_DEFINITIONS.items():
        component = {
            "p": "binary_sensor",
            "name": metadata["name"],
            "unique_id": f"{event.device_uid_hex}.STAT{group}.{bit}",
            "state_topic": state_topic(state_prefix, event.device_uid_hex, group, bit),
            "payload_on": "ON",
            "payload_off": "OFF",
        }
        if "device_class" in metadata:
            component["device_class"] = metadata["device_class"]
        components[f"{event.device_uid_hex}_{group}_{bit}"] = component

    return {
        "dev": {
            "ids": event.device_uid_hex,
            "name": f"{event.device_model} - {event.device_serial_number}",
            "mdl": event.device_model,
            "mf": "Inovonics",
            "sn": str(event.device_serial_number),
        },
        "o": {
            "name": app_name,
            "sw": app_version,
        },
        "cmps": components,
    }


def iter_state_messages(
    event: SecurityMessageEvent,
    *,
    state_prefix: str,
):
    for bit, value in enumerate(event.stat1_flags, start=1):
        yield state_topic(state_prefix, event.device_uid_hex, 1, bit), bool_to_state(value)

    for bit, value in enumerate(event.stat0_flags, start=1):
        yield state_topic(state_prefix, event.device_uid_hex, 0, bit), bool_to_state(value)


def topic_and_payload_for_bit_state_update(update, *, state_prefix: str):
    return (
        state_topic(state_prefix, update.device_uid_hex, update.stat_group, update.bit),
        bool_to_state(update.value),
    )
