from pathlib import Path

from inovonics_python_app.config import load_config, render_config_for_logging


def test_bit_coalescing_defaults_to_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "processor:",
                "  host: 127.0.0.1",
                "  port: 10001",
                "mqtt:",
                "  broker: 127.0.0.1",
                "  port: 1883",
                "  client_id: inovonics-python-app",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.bit_coalescing.enabled is True
    assert config.bit_coalescing.quiet_period_ms == 500
    assert config.bit_coalescing.max_hold_ms == 2000
    assert config.bit_coalescing.idle_ttl_ms == 900000
    assert config.bit_coalescing.flush_interval_ms == 250


def test_render_config_for_logging_redacts_sensitive_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "processor:",
                "  host: 127.0.0.1",
                "  port: 10001",
                "mqtt:",
                "  broker: 127.0.0.1",
                "  port: 1883",
                "  client_id: inovonics-python-app",
                "  password: super-secret",
            ]
        ),
        encoding="utf-8",
    )

    resolved_path, rendered = render_config_for_logging(config_path)

    assert resolved_path == config_path
    assert "super-secret" not in rendered
    assert "***REDACTED***" in rendered
