"""Offline hook tests only; no actual WeChat or proxy traffic."""
import importlib.util
import json
from types import SimpleNamespace
from pintuanya_inventory.config import ROOT

spec = importlib.util.spec_from_file_location("host_observer", ROOT / "capture/host_observer.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_connect_metadata_only_bounded_and_unattributed(tmp_path, monkeypatch):
    path = tmp_path / "hosts.jsonl"
    monkeypatch.setattr(module, "ctx", SimpleNamespace(options=SimpleNamespace(
        host_observation_file=str(path), host_observation_seconds=180)))
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    timer = SimpleNamespace(cancel=lambda: None)
    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: SimpleNamespace(call_later=lambda *args: timer))
    observer = module.HostObserver()
    observer.configure({"host_observation_file", "host_observation_seconds"})
    observer.running()
    class Request:
        method, host, port = "CONNECT", "unit.invalid", 443
        def __getattr__(self, key):
            raise AssertionError("Must never read request content: " + key)
    flow = SimpleNamespace(request=Request())
    observer.http_connect(flow)
    observer.http_connect(flow)  # short-interval duplicate omitted
    clock[0] = 120.0
    observer.http_connect(flow)
    clock[0] = 281.0
    observer.http_connect(flow)
    observer.done()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["window_start", "connect", "connect", "window_end"]
    assert rows[1]["phase"] == "baseline" and rows[2]["phase"] == "observation"
    assert all(r["attribution"] == "unconfirmed" for r in rows)
    assert rows[0]["body_capture"] is False
    assert rows[-1]["events"] == 2
    assert not any(k in r for r in rows for k in ("headers", "url", "body", "cookie", "authorization"))


def test_malformed_authority_not_saved():
    assert module.safe_host("UNIT.invalid") == "unit.invalid"
    for value in ("user:secret@host.invalid", "host.invalid/path?token=secret", "a" * 254, None):
        assert module.safe_host(value) is None
