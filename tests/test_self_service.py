"""Synthetic offline contracts, NOT evidence of a new group's real capture."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from pintuanya_inventory import self_service as s
from pintuanya_inventory.storage import connect,current,candidate_current


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path)
    return tmp_path


def profile(workspace,name="newgroup",title="新团甲"):
    p=s.create_profile(title,"#小程序://测试/原始入口/SHARE_CODE",name,8082,"")
    p.update(observation_session="TEST-OBSERVATION",participant_declaration=True,
             evidence_file=str(workspace/"secrets/profiles"/name/"observed.jsonl"))
    s.save_profile(p)
    return p


def payloads(group="REAL-FROM-RESPONSE",title="新团甲"):
    detail={"code":0,"data":{"title":title,"groupon_uuid":group,"seller_phone":"DO-NOT-SAVE"}}
    visitor={"code":0,"data":{"admin":{"admin_id":"","seller_id":"",**{k:0 for k in s.PERMISSIONS}},"openid":"DO-NOT-SAVE"}}
    products={"code":0,"data":{"page":1,"size":20,"next":False,"list":[
        {"groupon_uuid":group,"goods_uuid":"PRODUCT-1","title":"新商品","cost_price":9999,
         "sku_list":[{"sku_uuid":"SKU-1","title":"甲","stock":11,"sale":0,"secret":"DO-NOT-SAVE"},
                     {"sku_uuid":"SKU-2","title":"乙","stock":0,"sale":2}]}
    ]},"user":{"token":"DO-NOT-SAVE"}}
    return detail,visitor,products


def observed(p,payload,path,event_id="FLOW"):
    return s.project_response(p,"GET",s.HOST,path,payload,200,event_id,"2026-11-16T12:00:00+00:00")


def enroll_events(p,group="REAL-FROM-RESPONSE",title="新团甲",admin=False):
    detail,visitor,products=payloads(group,title)
    if admin:
        visitor["data"]["admin"]["admin_id"]="PRIVATE-ADMIN-ID"
        visitor["data"]["admin"]["can_modify_groupon"]=1
    records=[observed(p,detail,s.DETAIL,"DETAIL"),
             observed(p,visitor,s.VISITOR+"?groupon_uuid="+group,"ROLE"),
             observed(p,products,s.GOODS+"?groupon_uuid="+group,"PRODUCTS")]
    file=Path(p["evidence_file"])
    file.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in records if r),encoding="utf-8")
    return records


def test_create_does_not_resolve_share_code_or_overwrite(workspace):
    p=profile(workspace)
    assert p["group_id"] is None and p["phase"]=="new"
    with pytest.raises(ValueError,match="已存在"):
        s.create_profile("另一个","another link",p["profile_id"])
    assert s.load_profile(p["profile_id"])["title"]=="新团甲"
    with pytest.raises(ValueError):
        s.create_profile("团","link","../../outside")
    with pytest.raises(ValueError):
        s.validate_network(8082,"http://127.0.0.1:8082")
    with pytest.raises(ValueError):
        s.validate_network(8082,"http://user:password@localhost:7897")


def test_new_names_and_products_are_not_hardcoded_and_no_credentials(workspace):
    p=profile(workspace)
    enroll_events(p)
    text=Path(p["evidence_file"]).read_text(encoding="utf-8")
    assert "DO-NOT-SAVE" not in text and "cost_price" not in text and "openid" not in text
    result=s.analyze(p)
    assert result["groups"][0]["ready"]
    assert [r["stock_candidate"] for r in result["groups"][0]["products"]]==[11,0]
    detail,_,goods=payloads(title="其他团")
    assert observed(p,detail,s.DETAIL) is None
    assert s.project_response(p,"GET","other.invalid",s.GOODS,goods,200,"ID","2026-01-01T00:00:00Z") is None
    assert s.project_response(p,"POST",s.HOST,s.GOODS,goods,200,"ID","2026-01-01T00:00:00Z") is None
    assert observed(p,goods,"/api/v1/common/groupon/order/cart") is None


def test_admin_or_unknown_role_cannot_be_confirmed(workspace):
    p=profile(workspace)
    enroll_events(p,admin=True)
    assert not s.analyze(p)["groups"][0]["ready"]
    assert "PRIVATE-ADMIN-ID" not in Path(p["evidence_file"]).read_text(encoding="utf-8")
    with pytest.raises(ValueError,match="证据不足"):
        s.confirm_profile(p["profile_id"],"REAL-FROM-RESPONSE",reviewed=True)
    assert not s.config_for(p).exists()
    _,visitor,_=payloads()
    del visitor["data"]["admin"]["seller_id"]
    with pytest.raises(ValueError,match="role_unconfirmed"):
        observed(p,visitor,s.VISITOR+"?groupon_uuid=REAL-FROM-RESPONSE")


def test_structure_identity_and_business_errors_do_not_become_stock(workspace):
    p=profile(workspace)
    _,_,goods=payloads()
    goods["data"]["list"][0]["sku_list"][0].pop("sku_uuid")
    with pytest.raises(ValueError,match="identity_unconfirmed"):
        observed(p,goods,s.GOODS)
    assert observed(p,{"code":1},s.GOODS)["error_code"]=="http_or_business_failure"
    assert s.project_response(p,"GET",s.HOST,s.GOODS,None,403,"ID","2026-01-01T00:00:00Z")["error_code"]=="access_denied"
    assert not s.analyze(p)["groups"]


def test_confirm_import_sync_export_are_independent_and_idempotent(workspace):
    p=profile(workspace)
    enroll_events(p)
    with pytest.raises(ValueError,match="先核对"):
        s.confirm_profile(p["profile_id"],"REAL-FROM-RESPONSE")
    result=s.confirm_profile(p["profile_id"],"REAL-FROM-RESPONSE",True)
    assert result["product_skus"]==2
    s.confirm_profile(p["profile_id"],"REAL-FROM-RESPONSE",True)
    with connect(s.db_for(p),readonly=True) as db:
        assert db.execute("SELECT count(*) FROM collection_runs").fetchone()[0]==1
        assert all(r["stock_remaining"] is None for r in current(db,"passive"))
        assert len(candidate_current(db,"passive"))==4
    result=s.sync_profile(p["profile_id"])
    assert result["products"]==2
    assert (workspace/"exports/newgroup/candidates.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    other=profile(workspace,"other","另一团")
    enroll_events(other,group="OTHER-GROUP",title="另一团")
    s.confirm_profile("other","OTHER-GROUP",True)
    assert s.db_for(p)!=s.db_for(other)
    assert s.config_for(p)!=s.config_for(other)
    with connect(s.db_for(other),readonly=True) as db:
        assert all(r["target_id"]=="participant:OTHER-GROUP" for r in current(db,"passive"))
    assert not (workspace/"configs/target.local.json").exists()


def test_ambiguous_same_title_requires_reviewed_group_selection(workspace):
    p=profile(workspace)
    one=enroll_events(p,group="GROUP-A")
    two=enroll_events(p,group="GROUP-B")
    Path(p["evidence_file"]).write_text("".join(json.dumps(r)+"\n" for r in one+two),encoding="utf-8")
    assert len(s.analyze(p)["groups"])==2
    with pytest.raises(ValueError):
        s.confirm_profile(p["profile_id"],"NON-OBSERVED-GROUP",True)
    s.confirm_profile(p["profile_id"],"GROUP-A",True)
    with pytest.raises(ValueError,match="已绑定其他"):
        s.confirm_profile(p["profile_id"],"GROUP-B",True)


def test_process_ownership_is_required(workspace):
    state={"marker":str(workspace/"configs/profile.mine.local.json"),"addon":str(workspace/"capture/setup_addon.py"),
           "expected_executables":[str(workspace/".venv/python.exe")]}
    info={"ExecutablePath":str(workspace/".venv/python.exe"),"CommandLine":"mitmdump "+state["marker"]+" "+state["addon"]}
    assert s.owned_process(info,state)
    assert not s.owned_process({**info,"ExecutablePath":"C:/Windows/unrelated.exe"},state)
    assert not s.owned_process({**info,"CommandLine":"mitmdump different-profile"},state)


def test_external_python_is_allowed_only_for_exact_profile(workspace):
    external=workspace.parent/"External Python 中文"/"python.exe"
    state={"marker":str(workspace/"configs/profile.mine.local.json"),"addon":str(workspace/"capture/setup_addon.py"),
           "expected_executables":[str(external)]}
    info={"ExecutablePath":str(external),"CommandLine":"mitmdump "+state["marker"]+" "+state["addon"]}
    assert s.owned_process(info,state)
    assert not s.owned_process({**info,"CommandLine":"mitmdump unrelated-project"},state)
    assert not s.owned_process({**info,"ExecutablePath":str(workspace.parent/"foreign/python.exe")},state)


def test_service_does_not_start_without_role_declaration(workspace,monkeypatch):
    p=profile(workspace)
    monkeypatch.setattr(s.subprocess,"Popen",lambda *args,**kwargs:pytest.fail("must not start"))
    with pytest.raises(ValueError,match="普通账号"):
        s.start_session(p["profile_id"],"observe",participant=False)
