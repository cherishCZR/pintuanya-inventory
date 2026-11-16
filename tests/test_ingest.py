import json
from copy import deepcopy
import pytest
from pintuanya_inventory.ingest import ingest
from pintuanya_inventory.pipeline import event_from_payload, validate_event
from pintuanya_inventory.config import ROOT, load_config, validate_capture
from pintuanya_inventory.storage import connect, current


def test_default_rejected():
    with pytest.raises(ValueError,match="采集未启用"):
        validate_capture(load_config(ROOT/"configs/target.example.json"))


def test_whitelist_role_and_group(confirmed,payload):
    c,m,meta = confirmed
    event = event_from_payload(payload,m,mode="passive",config=c,metadata=meta)
    assert validate_event(event,c,m)
    for key,value in [("role","admin"),("host","other.invalid"),("path","/orders")]:
        with pytest.raises(ValueError):
            event_from_payload(payload,m,mode="passive",config=c,metadata={**meta,key:value})
    event["group_id"] = "wrong"
    with pytest.raises(ValueError):
        validate_event(event,c,m)


def test_queue_partial_dedup_restart_and_replacement(tmp_path,confirmed,payload):
    c,m,meta = confirmed
    event = event_from_payload(payload,m,mode="passive",config=c,metadata=meta)
    line = json.dumps(event).encode()+b"\n"
    queue = tmp_path/"events.jsonl"
    queue.write_bytes(line+line[:80])
    db_path = tmp_path/"inventory.db"
    result = ingest(c,db_path)
    assert result["inserted"] == 1 and result["partial_tail"]
    with queue.open("ab") as f:
        f.write(line[80:])
    assert ingest(c,db_path)["duplicates"] == 1
    assert ingest(c,db_path)["inserted"] == 0
    queue.write_bytes(line)
    assert ingest(c,db_path)["duplicates"] == 1
    with connect(db_path,readonly=True) as db:
        assert len(current(db,"passive")) == 3


def test_queue_rejects_extra_sensitive_payload(tmp_path,confirmed,payload):
    c,m,meta = confirmed
    event = event_from_payload(payload,m,mode="passive",config=c,metadata=meta)
    event["authorization"] = "secret"
    (tmp_path/"events.jsonl").write_text(json.dumps(event)+"\n",encoding="utf-8")
    assert ingest(c,tmp_path/"db")["rejected"] == 1
    with connect(tmp_path/"db",readonly=True) as db:
        assert current(db,"passive") == []
