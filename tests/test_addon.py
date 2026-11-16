"""Offline addon contract tests. These are NOT WeChat traffic evidence."""
import gzip
import brotli
import importlib.util
import json
from types import SimpleNamespace
import pytest
from pintuanya_inventory.config import ROOT

spec = importlib.util.spec_from_file_location("inventory_addon", ROOT/"capture/inventory_addon.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def flow(payload, path="/test", status=200, encoding="", content_type="application/json"):
    raw = json.dumps(payload).encode()
    if encoding == "gzip":
        raw = gzip.compress(raw)
    return SimpleNamespace(id="OFFLINE-TEST-FLOW", request=SimpleNamespace(host="unit.invalid", path=path, method="POST"),
                           response=SimpleNamespace(raw_content=raw,status_code=status,
                               headers={"content-type":content_type,"content-encoding":encoding}))


def test_passive_filters_redaction_no_mutation(tmp_path,confirmed,payload):
    c,m,_ = confirmed
    addon = module.InventoryAddon()
    addon.config,addon.mapping,addon.queue = c,m,tmp_path/"queue"
    payload["authorization"] = "secret"
    payload["user"] = {"phone":"sensitive"}
    f = flow(payload,path="/test?token=must-not-persist")
    before = f.response.raw_content
    addon.response(f)
    assert f.response.raw_content == before
    text = addon.queue.read_text(encoding="utf-8")
    assert "secret" not in text and "sensitive" not in text and "token" not in text
    assert json.loads(text)["status"] == "exact_stock"
    count = len(text)
    addon.response(flow(payload,path="/orders"))
    payload["group"] = "other"
    addon.response(flow(payload))
    assert len(addon.queue.read_text(encoding="utf-8")) == count


def test_compression_bound():
    assert module.bounded_decode(gzip.compress(b"abc"),"gzip",100) == b"abc"
    with pytest.raises(OverflowError):
        module.bounded_decode(gzip.compress(b"a"*100_000),"gzip",100)
    with pytest.raises(ValueError):
        module.bounded_decode(b"opaque","br",100)


def test_actual_brotli_response_encoding_bound():
    assert module.bounded_decode(brotli.compress(b'{"code":0}'),"br",100) == b'{"code":0}'
    with pytest.raises(OverflowError):
        module.bounded_decode(brotli.compress(b"a"*100_000),"br",100)


def test_self_service_capture_requires_current_ordinary_role(tmp_path,confirmed,payload):
    c,m,_=confirmed
    c["capture"].update(require_participant_role=True,role_check_path="/role")
    addon=module.InventoryAddon()
    addon.config,addon.mapping,addon.queue=c,m,tmp_path/"queue"
    addon.response(flow(payload))
    assert not addon.queue.exists()
    admin={"admin_id":"","seller_id":"","can_modify_groupon":0,"can_modify_member":0,"can_modify_membership":0}
    role={"code":0,"data":{"admin":admin}}
    role_flow=flow(role,path="/role?groupon_uuid=DEMO")
    role_flow.request.method="GET"
    addon.response(role_flow)
    addon.response(flow(payload))
    assert addon.queue.exists()
    before=addon.queue.read_text(encoding="utf-8")
    admin["admin_id"]="ACCOUNT-SECRET"
    admin["can_modify_groupon"]=1
    role_flow=flow(role,path="/role?groupon_uuid=DEMO")
    role_flow.request.method="GET"
    addon.response(role_flow)
    addon.response(flow(payload))
    assert addon.queue.read_text(encoding="utf-8")==before
    assert "ACCOUNT-SECRET" not in before


@pytest.mark.parametrize("http,error", [(304,"cached_not_modified"),(204,"empty_response"),(401,"authentication_required")])
def test_diagnostics_no_observations(tmp_path,confirmed,payload,http,error):
    c,m,_ = confirmed
    addon = module.InventoryAddon()
    addon.config,addon.mapping,addon.queue = c,m,tmp_path/"queue"
    addon.response(flow(payload,status=http))
    e = json.loads(addon.queue.read_text(encoding="utf-8"))
    assert e["error_code"] == error and e["observations"] == []
