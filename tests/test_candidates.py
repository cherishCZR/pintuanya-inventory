from pintuanya_inventory.extract import extract
from pintuanya_inventory.pipeline import event_from_payload
from pintuanya_inventory.storage import connect, write_event, current, candidate_current


def test_item_group_association_is_atomic(mapping, payload):
    mapping.update(group_scope="item", group_path=["group"])
    for item in payload["data"]["items"]:
        item["group"] = "TEST-GROUP"
    assert len(extract(payload,mapping,expected_group="TEST-GROUP").observations) == 3
    payload["data"]["items"][1]["group"] = "WRONG-GROUP"
    result = extract(payload,mapping,expected_group="TEST-GROUP")
    assert result.error_code == "wrong_or_unconfirmed_group"
    assert result.observations == [] and result.candidates == []


def test_candidates_stay_separate_from_quantities(tmp_path, mapping, payload):
    mapping["metrics"] = {}
    mapping["candidates"] = {"raw_remaining":{"path":["remaining"]}}
    result = extract(payload,mapping)
    assert result.status == "inconclusive"
    assert [r["value"] for r in result.candidates] == [7,0,"3"]
    assert all(r["stock_remaining"] is None for r in result.observations)
    with connect(tmp_path/"db") as db:
        write_event(db,event_from_payload(payload,mapping))
        assert all(r["stock_remaining"] is None for r in current(db,"demo"))
        assert len(candidate_current(db,"demo")) == 3
        assert all(r["semantics"] == "unconfirmed" for r in candidate_current(db,"demo"))
        assert candidate_current(db,"passive") == []
    assert extract({"ok":False},mapping).candidates == []


def test_arbitrary_candidate_text_is_not_persisted(mapping, payload):
    mapping["candidates"] = {"raw":{"path":["remaining"]}}
    payload["data"]["items"][0]["variants"][0]["remaining"] = "credential-like-value"
    result = extract(payload,mapping)
    candidate = result.candidates[0]
    assert candidate["value"] is None and candidate["value_type"] == "str"


def test_candidate_failure_keeps_historical_value_and_marks_stale(tmp_path, mapping, payload):
    mapping["metrics"] = {}
    mapping["candidates"] = {"stock":{"path":["remaining"]}}
    with connect(tmp_path/"db") as db:
        write_event(db,event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:00Z"}))
        write_event(db,event_from_payload(payload,mapping,metadata={"observed_at":"2026-01-01T00:00:01Z","http_status":500}))
        candidate = candidate_current(db,"demo")[0]
        assert candidate["value"] == 7 and candidate["stale"]
        assert candidate["latest_error"] == "http_error"
