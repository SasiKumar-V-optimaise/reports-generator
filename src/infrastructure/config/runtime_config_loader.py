from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]

def load_runtime_config() -> dict:
    with open(ROOT / "config" / "runtime.yaml") as f:
        return yaml.safe_load(f) or {}


def load_config():
    return load_runtime_config()



