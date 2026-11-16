from copy import deepcopy
import pytest
from pintuanya_inventory.extract import extract, quantity
from pintuanya_inventory.config import ROOT, load_json


@pytest.mark.parametrize("value,state,expected", [(0,"valid",0), (None,"null",None), (True,"invalid_type_or_sentinel",None),
    (-1,"invalid_type_or_sentinel",None), ("8","valid",8), ("8.2","invalid_type_or_sentinel",None),
    (1.5,"invalid_type_or_sentinel",None), (2**100,"invalid_type_or_sentinel",None)])
def test_quantity(value, state, expected):
    assert quantity(value) == (expected,state)


def test_multi_sku_same_names_zero(mapping,payload):
    r = extract(payload,mapping)
    assert r.status == "exact_stock"
    assert [o["stock_remaining"] for o in r.observations] == [7,0,3]
    assert len({(o["product_id"],o["sku_id"]) for o in r.observations}) == 3
    assert r.coverage == "partial"


@pytest.mark.parametrize("name,status", [("demo_availability","availability_only"), ("demo_missing","inconclusive"), ("demo_business_error","failed")])
def test_status(mapping,name,status):
    r = extract(load_json(ROOT / f"tests/fixtures/{name}.json"),mapping)
    assert r.status == status
    assert all(x["stock_remaining"] is None for x in r.observations)


@pytest.mark.parametrize("http,error", [(401,"authentication_required"),(403,"authentication_required"),(429,"rate_limited"),
    (304,"cached_not_modified"),(204,"empty_response"),(500,"http_error")])
def test_http(mapping,payload,http,error):
    r = extract(payload,mapping,http)
    assert r.error_code == error
    assert r.observations == []


def test_candidate_not_confirmation(mapping,payload):
    mapping["metrics"]["stock_remaining"]["confirmed"] = False
    r = extract(payload,mapping)
    assert r.status == "availability_only"
    assert all(o["stock_remaining"] is None for o in r.observations)


def test_structure_identity_group(mapping,payload):
    assert extract({},mapping).error_code == "mapping_changed"
    assert extract(payload,mapping,expected_group="other").error_code == "wrong_or_unconfirmed_group"
    del payload["data"]["items"][0]["id"]
    assert extract(payload,mapping).error_code == "identity_unconfirmed"


def test_missing_null_bool_and_sentinel(mapping,payload):
    variants = payload["data"]["items"][0]["variants"]
    del variants[0]["remaining"]
    variants[1]["remaining"] = None
    payload["data"]["items"][1]["variants"][0]["remaining"] = False
    r = extract(payload,mapping)
    assert [o["quantity_status"] for o in r.observations] == ["missing","null","invalid_type_or_sentinel"]
    assert all(o["stock_remaining"] is None for o in r.observations)


def test_mapping_change_atomic(mapping,payload):
    mapping["metrics"]["stock_remaining"]["missing_behavior"] = "mapping_changed"
    del payload["data"]["items"][1]["variants"][0]["remaining"]
    r = extract(payload,mapping)
    assert r.error_code == "mapping_changed" and not r.observations


def test_single_sku(mapping):
    mapping.pop("sku_path")
    mapping["metrics"] = {}
    result = extract({"ok":True,"data":{"items":[{"id":"x","name":"x"}]}},mapping)
    assert result.observations[0]["synthetic_sku"]
    assert result.observations[0]["sku_id"] == "__single__"
