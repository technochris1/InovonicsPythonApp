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

The image is published as `technochris1/inovonicspythonapp`. The container
command is `python -u App.py`. Application logs are written both to Docker's
container log and to `/app/logs/app.log`.

### Build and Publish Manually

Run these commands from the repository root after changing the code:

```bash
docker login
docker build --pull -t technochris1/inovonicspythonapp:latest .
docker push technochris1/inovonicspythonapp:latest
```

For a versioned release, publish an additional immutable tag:

```bash
docker build --pull \
  -t technochris1/inovonicspythonapp:1.3.2 \
  -t technochris1/inovonicspythonapp:latest .
docker push technochris1/inovonicspythonapp:1.3.2
docker push technochris1/inovonicspythonapp:latest
```

The repository also includes [Docker Hub automation](#docker-hub-automation).
That workflow publishes `latest` when `main` is updated and publishes the
matching tag when a version tag such as `v1.3.2` is pushed.

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
- `INOVONICS_LOGGING_FILE`
- `INOVONICS_CONFIG_PATH`

Example `docker-compose.yml` fragment:

```yaml
services:
  inovonics:
    image: technochris1/inovonicspythonapp:latest
    init: true
    restart: unless-stopped
    volumes:
      - inovonics-python-app-logs:/app/logs
    environment:
      INOVONICS_PROCESSOR_HOST: 192.168.1.60
      INOVONICS_PROCESSOR_PORT: "10001"
      INOVONICS_MQTT_BROKER: 192.168.1.31
      INOVONICS_MQTT_PORT: "1883"
      INOVONICS_MQTT_USERNAME: mqtt-user
      INOVONICS_MQTT_PASSWORD: super-secret

volumes:
  inovonics-python-app-logs:
```

### Deploy in Portainer

The recommended Portainer deployment is a Stack because the restart policy,
init process, and persistent log volume are saved as configuration.

1. Build and push the image, or wait for the GitHub workflow to finish.
2. Open the `local` Docker environment in Portainer.
3. Select **Stacks**, then **Add stack**.
4. Name the stack `inovonics-python-app`.
5. Paste the Compose definition above into the Web editor.
6. Replace the processor, MQTT, username, and password values with the values
   for the local network.
7. Select **Deploy the stack**.

To update an existing Stack after publishing a new `latest` image:

1. Open the Stack and select **Editor**.
2. Select **Update the stack** and enable **Pull latest image version** if the
   option is shown.
3. Deploy/update the Stack.
4. Open the container logs and confirm that it reports the loaded config and
   `Bridge started`.

If Portainer does not offer a pull option, manually pull
`technochris1/inovonicspythonapp:latest` from the **Images** page, then
recreate or redeploy the Stack. Docker will not automatically replace an
existing container just because the registry tag changed.

### Deploy as an Individual Container

If using **Containers > Add container** instead of a Stack, use:

- Image: `technochris1/inovonicspythonapp:latest`
- Restart policy: `Unless stopped`
- Init: enabled
- Volume: a named volume mounted at `/app/logs`
- Environment variables: the same `INOVONICS_*` values shown above

When changing the image, use **Recreate** and enable **Pull latest image**.
Editing an existing container does not change the image that was used to
create it.

### Verify and Troubleshoot

Check the container's **Logs** page first. Fatal Python errors now include a
traceback and end with `Fatal application error; exiting with status 1`.
Exceptions from worker threads include the thread name. The container's exit
code is still useful, but Docker does not generate a Python traceback itself;
the application must write that traceback to stderr, which this image now
does.

The persistent log file is available from the mounted volume at:

```text
/app/logs/app.log
```

In **Inspect**, these fields are useful:

- `State.Error`: Docker/runtime-level error, if any
- `State.ExitCode`: process exit status
- `State.OOMKilled`: whether the kernel killed the container for memory
- `State.StartedAt` and `State.FinishedAt`: exact runtime window
- `RestartCount`: whether the restart policy is repeatedly cycling

An exit code of `255` is not intentionally returned by this application. If
it appears again after redeployment, capture the final Docker log lines and
the Inspect values above; the new diagnostics should identify whether the
failure came from configuration, startup, a worker thread, or the runtime.

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
