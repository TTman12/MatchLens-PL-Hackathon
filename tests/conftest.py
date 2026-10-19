from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
SCHEMAS = ROOT / "schemas"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample() -> dict[str, Any]:
    """Every file of the sample match, parsed."""
    data = {p.stem: load_json(p) for p in SAMPLE.glob("*.json")}
    with (SAMPLE / "frames.jsonl").open(encoding="utf-8") as fh:
        data["frames"] = [json.loads(line) for line in fh]
    return data


@pytest.fixture(scope="session")
def sample_builder() -> ModuleType:
    """The script that builds the sample match, imported as a module."""
    path = ROOT / "scripts" / "make_sample_match.py"
    spec = importlib.util.spec_from_file_location("make_sample_match", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module
