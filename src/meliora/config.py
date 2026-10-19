"""Loads config.toml from the repo root."""

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"


def load() -> dict:
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)
