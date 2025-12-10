<img src="beef2beef.png" alt="Logo" width="200">

Secure end-to-end encrypted chat with TCP (and optional Bluetooth on Linux) plus a PySide6 GUI.

## Quick Start

```sh
./run.sh
```

What it does:
- Activates `.venv` (make sure it exists) and installs `requirements.txt`.
- Launches GUI.

## CLI Mode

Requirements:
- `.venv` & `requirements.txt` dependencies installed
- Python3

```sh
python -m src.main --listen $PORT
# Or
python -m src.main --connect $HOST $PORT
```

## Notes
- Bluetooth transport requires Linux with `pybluez`.
- TCP works everywhere.
- Default launches to 127.0.0.1:8000
- Supports many-to-one connections