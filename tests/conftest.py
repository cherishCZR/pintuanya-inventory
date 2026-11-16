from copy import deepcopy
import json
from pathlib import Path
import pytest
from pintuanya_inventory.config import ROOT, load_json


def pytest_configure(config):
    # A source ZIP has no runtime directories; --cache-dir may also keep pip's
    # cache outside it. pytest creates basetemp itself, but not its parent.
    if config.option.basetemp:
        Path(config.option.basetemp).parent.mkdir(parents=True,exist_ok=True)


@pytest.fixture
def mapping():
    return load_json(ROOT / "configs/mapping.demo.json")


@pytest.fixture
def payload():
    return load_json(ROOT / "tests/fixtures/demo_exact.json")


@pytest.fixture
def confirmed(tmp_path, mapping):
    # Entirely synthetic test-only source; never a real endpoint or participant claim.
    m = deepcopy(mapping)
    m.update(demo=False, source_confirmed=True, version="TEST-ONLY")
    m["metrics"]["stock_remaining"]["missing_behavior"] = "unknown"
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(m), encoding="utf-8")
    c = {"_base": str(tmp_path), "target": {"label": "TEST ONLY", "resolved_group_id": "DEMO", "association_evidence": "test only"},
         "role": "participant", "session_id": "TEST-SESSION", "role_evidence": {"confirmed": True, "method": "TEST ONLY", "observed_at": "2026-01-01T00:00:00+00:00"},
         "mapping_file": str(path), "queue_file": "events.jsonl",
         "capture": {"enabled": True, "allowed_hosts": ["unit.invalid"], "endpoint_rules": [
             {"host": "unit.invalid", "path": "/test", "method": "POST", "alias": "TEST", "readonly_confirmed": True, "evidence": "test only"}]}}
    meta = {"host": "unit.invalid", "path": "/test", "method": "POST", "role": "participant", "session_id": "TEST-SESSION", "event_id": "TEST-FLOW"}
    return c, m, meta
