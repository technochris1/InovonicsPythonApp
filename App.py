from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PROCESSOR_SRC = ROOT.parent / "InovonicsEchostreamProcessor" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if PROCESSOR_SRC.exists() and str(PROCESSOR_SRC) not in sys.path:
    sys.path.insert(0, str(PROCESSOR_SRC))

from inovonics_python_app.mqtt_app import main


if __name__ == "__main__":
    raise SystemExit(main())
