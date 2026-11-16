"""Offline response staging/privacy tests; no real platform traffic."""
import importlib.util
import json
from pathlib import Path
from pintuanya_inventory.config import ROOT

spec=importlib.util.spec_from_file_location("setup_addon_test",ROOT/"capture/setup_addon.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def observer(tmp_path):
    addon=module.SetupAddon()
    addon.file=tmp_path/"evidence.jsonl"
    addon.groups=set()
    addon.roles={}
    addon.pending=[]
    addon.written=0
    return addon


def test_out_of_order_products_wait_for_matching_title_and_ordinary_role(tmp_path):
    addon=observer(tmp_path)
    addon.accept({"kind":"products","group_id":"A","payload":{"stock":"candidate"}})
    assert not addon.file.exists()
    addon.accept({"kind":"detail","group_id":"A","title":"新团"})
    assert "products" not in addon.file.read_text(encoding="utf-8")
    addon.accept({"kind":"visitor","group_id":"A","admin_id_nonempty":False,"seller_id_nonempty":False,
                  "permissions":{"can_modify_groupon":0,"can_modify_member":0,"can_modify_membership":0}})
    rows=[json.loads(line) for line in addon.file.read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in rows]==["detail","visitor","products"]


def test_admin_candidate_values_are_not_persisted(tmp_path):
    addon=observer(tmp_path)
    addon.accept({"kind":"detail","group_id":"A","title":"新团"})
    addon.accept({"kind":"products","group_id":"A","payload":{"stock":"ADMIN-ONLY-VALUE"}})
    addon.accept({"kind":"visitor","group_id":"A","admin_id_nonempty":True,"seller_id_nonempty":False,
                  "permissions":{"can_modify_groupon":1,"can_modify_member":0,"can_modify_membership":0}})
    addon.accept({"kind":"products","group_id":"A","payload":{"stock":"ADMIN-ONLY-VALUE"}})
    text=addon.file.read_text(encoding="utf-8")
    assert "ADMIN-ONLY-VALUE" not in text and '"kind":"products"' not in text
