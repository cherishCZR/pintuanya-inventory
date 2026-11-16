from copy import deepcopy
from pintuanya_inventory.pipeline import event_from_payload
from pintuanya_inventory.storage import connect, current, write_event


def test_idempotency_and_source_isolation(tmp_path,mapping,payload):
    e = event_from_payload(payload,mapping)
    with connect(tmp_path/"db") as db:
        assert write_event(db,e)
        assert not write_event(db,e)
        assert len(current(db,"demo")) == 3
        assert current(db,"passive") == []


def test_failure_keeps_history_missing_success_clears(tmp_path,mapping,payload):
    with connect(tmp_path/"db") as db:
        good = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:00Z"})
        write_event(db,good)
        failed = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:01Z","http_status":500})
        write_event(db,failed)
        row = current(db,"demo")[0]
        assert row["stock_remaining"] == 7 and row["stale"] and row["latest_error"] == "http_error"
        del payload["data"]["items"][0]["variants"][0]["remaining"]
        unknown = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:02Z"})
        write_event(db,unknown)
        assert current(db,"demo")[0]["stock_remaining"] is None


def test_out_of_order_delta_and_mapping(tmp_path,mapping,payload):
    first = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:00Z"})
    payload["data"]["items"][0]["variants"][0]["remaining"] = 5
    second = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:01Z"})
    with connect(tmp_path/"db") as db:
        write_event(db,second)
        write_event(db,first)
        assert current(db,"demo")[0]["inventory_change"] == -2
        mapping["version"] = "different-semantics"
        third = event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:02Z"})
        write_event(db,third)
        assert current(db,"demo")[0]["inventory_change"] is None
