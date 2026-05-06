# Inovonics Python App

`InovonicsPythonApp` is the production MQTT and Home Assistant bridge for
Inovonics EchoStream traffic. It depends on the reusable
`InovonicsEchostreamProcessor` package for transport and protocol processing and
owns only application concerns such as MQTT connectivity, Home Assistant
discovery, and state publication.

## Architecture

- `InovonicsEchostreamProcessor` core: transport-free frame decoding,
  protocol parsing, normalized EchoStream events, runtime detection
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
2. `config.local.yaml`
3. `config.yaml`

Use [config.example.yaml](config.example.yaml)
as the tracked baseline and keep environment-specific credentials in
`config.local.yaml`.

## Run

```bash
python App.py
```

or

```bash
python -m inovonics_python_app
```
