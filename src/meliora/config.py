"""Settings and private data files.

Each file is read from data/ (private, gitignored) when it exists, otherwise from
data-sample/ (public, fake). A fresh clone runs on the sample with no setup.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SAMPLE_DIR = ROOT / "data-sample"


def find(name: str) -> Path:
    private = DATA_DIR / name
    return private if private.exists() else SAMPLE_DIR / name


def load() -> dict:
    with find("config.toml").open("rb") as f:
        return tomllib.load(f)


def home() -> dict:
    return next(p for p in load()["places"] if p["kind"] == "home")


def vault_path() -> Path:
    return Path(load()["vault"]["path"]).expanduser()
