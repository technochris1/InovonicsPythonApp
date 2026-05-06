from inovonics_echostream_processor.events import SecurityMessageEvent

from inovonics_python_app.home_assistant import (
    build_discovery_payload,
    discovery_topic,
    iter_state_messages,
    topic_and_payload_for_bit_state_update,
)


def _event() -> SecurityMessageEvent:
    return SecurityMessageEvent(
        raw_message=b"\x72",
        device_uid_hex="B2010203",
        device_serial_number=66051,
        first_hop_hex="11223344",
        trace_count=0,
        hop_count=1,
        mid=178,
        pti=4,
        device_category="SECURITY",
        device_model="EN1210SK",
        signal_level=100,
        signal_margin=50,
        stat1_flags=(True, False, False, True, False, False, False, False),
        stat0_flags=(False, False, False, True, False, True, False, False),
    )


def test_build_discovery_payload() -> None:
    payload = build_discovery_payload(
        _event(),
        state_prefix="inovonics",
        app_name="inovonics-python-app",
        app_version="1.0.0",
    )

    assert payload["dev"]["ids"] == "B2010203"
    assert payload["dev"]["mdl"] == "EN1210SK"
    assert "B2010203_1_1" in payload["cmps"]
    assert payload["cmps"]["B2010203_0_6"]["device_class"] == "tamper"


def test_discovery_topic_and_state_messages() -> None:
    topic = discovery_topic("homeassistant", "B2010203")
    messages = list(iter_state_messages(_event(), state_prefix="inovonics"))

    assert topic == "homeassistant/device/B2010203/config"
    assert messages[0] == ("inovonics/B2010203/1/1/state", "ON")
    assert messages[11] == ("inovonics/B2010203/0/4/state", "ON")


def test_topic_and_payload_for_bit_state_update() -> None:
    topic, payload = topic_and_payload_for_bit_state_update(
        type(
            "Update",
            (),
            {
                "device_uid_hex": "B2010203",
                "stat_group": 0,
                "bit": 6,
                "value": True,
            },
        )(),
        state_prefix="inovonics",
    )

    assert topic == "inovonics/B2010203/0/6/state"
    assert payload == "ON"
