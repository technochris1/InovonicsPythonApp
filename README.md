# Inovonics Python App

`InovonicsPythonApp` is the production MQTT and Home Assistant bridge for
Inovonics EchoStream traffic. It depends on the reusable
`InovonicsEchostreamProcessor` package for transport and protocol processing and
owns only application concerns such as MQTT connectivity, Home Assistant
discovery, and state publication.

## Architecture

- `InovonicsEchostreamProcessor` core: transport-free frame decoding,
  protocol parsing, normalized EchoStream events, runtime detection, optional
  bit-state coalescing
- `InovonicsEchostreamProcessor` CPython transport: threaded TCP socket adapter
- `InovonicsPythonApp`: MQTT lifecycle, Home Assistant discovery/state topics,
  application logging, and deployment packaging

## Install

### Production

```bash
pip install .
```

### Local Development With Sibling Repos

```bash
pip install -e ../InovonicsEchostreamProcessor
pip install -e .
```

## Configuration

The app resolves configuration in this order:

1. `--config <path>`
2. `INOVONICS_CONFIG_PATH`
3. `config.local.yaml`
4. `config.yaml`

Use [config.example.yaml](config.example.yaml)
as the tracked baseline and keep environment-specific credentials in
`config.local.yaml`.

After the file is selected, `INOVONICS_*` environment variables override the
matching config values. That makes Docker and Compose the clean deployment path
without needing to rewrite `config.yaml` in the container.

Bit-state coalescing is enabled by default. The app buffers rapid per-device,
per-bit changes before publishing retained MQTT state, and the coalescer
evicts idle bit entries automatically so memory stays bounded over time.

## Docker

The runtime image ships with Docker-oriented defaults through environment
variables. By default it assumes:

- the EchoStream socket endpoint is reachable as `processor:10001`
- the MQTT broker is reachable as `mqtt:1883`
- the MQTT password placeholder default is `password`
- if a password is set, the app applies it even when the username is blank

Those defaults can be overridden with standard Docker environment variables,
for example:

```bash
docker run --rm \
  -e INOVONICS_PROCESSOR_HOST=192.168.1.60 \
  -e INOVONICS_MQTT_BROKER=192.168.1.31 \
  -e INOVONICS_MQTT_USERNAME=mqtt-user \
  -e INOVONICS_MQTT_PASSWORD=super-secret \
  <image>
```

Use [.env.example](.env.example) as the standard template when supplying real
IP addresses, usernames, and passwords. It shows the expected format without
hardcoding live credentials into the image.

Common environment variables:

- `INOVONICS_PROCESSOR_HOST`
- `INOVONICS_PROCESSOR_PORT`
- `INOVONICS_MQTT_BROKER`
- `INOVONICS_MQTT_PORT`
- `INOVONICS_MQTT_CLIENT_ID`
- `INOVONICS_MQTT_USERNAME`
- `INOVONICS_MQTT_PASSWORD`
- `INOVONICS_MQTT_COMMAND_TOPIC`
- `INOVONICS_MQTT_DISCOVERY_PREFIX`
- `INOVONICS_MQTT_STATE_PREFIX`
- `INOVONICS_BIT_COALESCING_ENABLED`
- `INOVONICS_BIT_COALESCING_QUIET_PERIOD_MS`
- `INOVONICS_BIT_COALESCING_MAX_HOLD_MS`
- `INOVONICS_BIT_COALESCING_IDLE_TTL_MS`
- `INOVONICS_BIT_COALESCING_FLUSH_INTERVAL_MS`
- `INOVONICS_LOGGING_LEVEL`
- `INOVONICS_CONFIG_PATH`

Example `docker-compose.yml` fragment:

```yaml
services:
  inovonics:
    image: technochris1/inovonicspythonapp:latest
    environment:
      INOVONICS_PROCESSOR_HOST: 192.168.1.60
      INOVONICS_PROCESSOR_PORT: "10001"
      INOVONICS_MQTT_BROKER: 192.168.1.31
      INOVONICS_MQTT_PORT: "1883"
      INOVONICS_MQTT_USERNAME: mqtt-user
      INOVONICS_MQTT_PASSWORD: super-secret
```

Example `.env` format:

```dotenv
INOVONICS_PROCESSOR_HOST=192.168.1.60
INOVONICS_PROCESSOR_PORT=10001
INOVONICS_MQTT_BROKER=192.168.1.31
INOVONICS_MQTT_PORT=1883
INOVONICS_MQTT_CLIENT_ID=inovonics-python-app
INOVONICS_MQTT_USERNAME=mqtt-user
INOVONICS_MQTT_PASSWORD=password
INOVONICS_MQTT_COMMAND_TOPIC=homeassistant
INOVONICS_MQTT_DISCOVERY_PREFIX=homeassistant
INOVONICS_MQTT_STATE_PREFIX=inovonics
INOVONICS_BIT_COALESCING_ENABLED=true
INOVONICS_BIT_COALESCING_QUIET_PERIOD_MS=500
INOVONICS_BIT_COALESCING_MAX_HOLD_MS=2000
INOVONICS_BIT_COALESCING_IDLE_TTL_MS=900000
INOVONICS_BIT_COALESCING_FLUSH_INTERVAL_MS=250
INOVONICS_LOGGING_LEVEL=INFO
```

### Docker Hub Automation

The repository now includes [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml).

- pushes to `main` publish `technochris1/inovonicspythonapp:latest`
- pushed Git tags like `v1.3.1` publish the matching Docker tag

Required GitHub repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

`DOCKERHUB_TOKEN` should be a Docker Hub access token, not your Docker Hub
password.

## Run

```bash
python App.py
```

or

```bash
python -m inovonics_python_app
```

<!-- CODEX-REPO-MAP START -->
# InovonicsPythonApp

This repository contains the `InovonicsPythonApp` project.

Primary languages and file types: Python.

## Root files

| Item | Role |
| --- | --- |
| `.dockerignore` | Supporting file. |
| `.env.example` | Supporting file. |
| `.gitattributes` | Supporting file. |
| `.gitignore` | Supporting file. |
| `App.py` | Main Python app entrypoint. |
| `config.example.yaml` | YAML configuration. |
| `config.yaml` | YAML configuration. |
| `Dockerfile` | Container build instructions. |
| `pyproject.toml` | Python project metadata. |
| `requirements.txt` | Python dependency list. |

## App folders

| Folder | Summary |
| --- | --- |
| `src/inovonics_python_app` | Code folder for `inovonics_python_app`; contains `config.py`, `home_assistant.py`, `mqtt_app.py`, `version.py`, `__init__.py`. |
| `tests` | Code folder for `tests`; contains `test_config.py`, `test_home_assistant.py`. |

## Folder docs

| Path | Role |
| --- | --- |
| `src/inovonics_python_app/README.md` | Folder-level summary for the code in that directory. |
| `tests/README.md` | Folder-level summary for the code in that directory. |

<!-- CODEX-REPO-MAP END -->
