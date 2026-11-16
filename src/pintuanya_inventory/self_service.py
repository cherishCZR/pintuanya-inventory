"""Self-service enrollment from real passive responses of the observed adapter.

No share-code resolution, remote requests, guessing of endpoints or quantity
semantics. Discovery only recognizes the platform structure previously observed
in this project and refuses unsupported structures.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from .config import ROOT, load_config, load_json, resolve, validate_capture
from .export import export_csv, export_candidates
from .extract import extract
from .ingest import ingest
from .models import utcnow
from .pipeline import event_from_payload
from .storage import connect, current, candidate_current, write_event

# These are previously observed paths, not newly invented platform API calls.
HOST = "server.pintuanya.com"
DETAIL = "/api/v1/common/groupon/v2/detail"
VISITOR = "/api/v1/common/groupon/v2/visitor"
GOODS = "/api/v1/common/groupon/goods/batch"
PATHS = {DETAIL, VISITOR, GOODS}
PERMISSIONS = ("can_modify_groupon", "can_modify_member", "can_modify_membership")
_managed = {}


def slug(value):
    if not isinstance(value,str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}",value):
        raise ValueError("团单代号只允许小写字母、数字、下划线和短横线，最多40字")
    return value


def profile_path(profile_id):
    return ROOT / "configs" / ("profile." + slug(profile_id) + ".local.json")


def save_profile(p):
    path = profile_path(p["profile_id"])
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(path)


def load_profile(profile_id):
    p = load_json(profile_path(profile_id))
    if p.get("profile_id") != profile_id or p.get("adapter") != "observed_pintuanya_v1":
        raise ValueError("团单设置无效或适配器不支持")
    validate_network(p["proxy_port"],p.get("upstream",""))
    return p


def profiles():
    found=[]
    for path in sorted((ROOT/"configs").glob("profile.*.local.json")):
        try:
            p=load_json(path)
            if profile_path(p["profile_id"]).resolve()==path.resolve():
                found.append(load_profile(p["profile_id"]))
        except (ValueError,KeyError,OSError,TypeError):
            continue
    return found


def validate_network(port,upstream):
    if type(port) is not int or not 1024 <= port <= 65535 or port in (8501,8502):
        raise ValueError("代理端口需要在1024至65535之间，且不能使用界面端口8501/8502")
    if not upstream:
        return
    u=urlsplit(upstream)
    if (u.scheme not in ("http","https") or not u.hostname or u.username or u.password
            or u.query or u.fragment or u.path not in ("","/") or not u.port):
        raise ValueError("上游填写你实际使用的HTTP(S)代理地址和端口；无上游则留空，不填写账号密码")
    if u.hostname.lower() in ("localhost","127.0.0.1","::1") and u.port==port:
        raise ValueError("上游不能指回本工具的监听端口")


def create_profile(title,share_text,profile_id=None,proxy_port=8082,upstream=""):
    title,share_text=title.strip(),share_text.strip()
    if not title or len(title)>200 or not share_text or len(share_text)>4096:
        raise ValueError("请填写实际团单名称和分享链接；链接仅保存为入口说明，不当作业务ID")
    validate_network(proxy_port,upstream)
    profile_id=slug(profile_id or ("g"+datetime.now(timezone.utc).strftime("%m%d%H%M%S")+uuid.uuid4().hex[:4]))
    if profile_path(profile_id).exists():
        raise ValueError("该团单代号已存在，请选择已有团单或使用新代号")
    p={"profile_id":profile_id,"title":title,"share_text":share_text,"adapter":"observed_pintuanya_v1",
       "phase":"new","created_at":utcnow(),"proxy_port":proxy_port,"upstream":upstream.rstrip("/"),
       "participant_declaration":False,"observation_session":None,"evidence_file":None,"group_id":None}
    for folder in (ROOT/"secrets/profiles"/profile_id,ROOT/"data/profiles"/profile_id,ROOT/"exports"/profile_id):
        folder.mkdir(parents=True,exist_ok=True)
    save_profile(p)
    return p


def identity(value):
    return isinstance(value,str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,200}",value))


def quantity_fragment(value):
    if value is None or type(value) is bool or (type(value) is int and abs(value)<2**63):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value,str):
        return value if len(value)<=32 and re.fullmatch(r"[-+]?[0-9]+(?:\.[0-9]+)?",value) else "[redacted]"
    return {} if isinstance(value,dict) else [] if isinstance(value,list) else None


def project_response(p,method,host,request_path,payload,status,event_id,observed_at):
    """Minimal white-list projection; caller never writes original payloads."""
    url=urlsplit(request_path)
    if method!="GET" or host!=HOST or url.path not in PATHS:
        return None
    base={"profile_id":p["profile_id"],"session_id":p["observation_session"],"event_id":str(event_id),
          "observed_at":observed_at,"host":host,"path":url.path,"method":"GET","http_status":status}
    if status in (401,403):
        return {**base,"kind":"diagnostic","error_code":"access_denied"}
    if status!=200 or not isinstance(payload,dict) or type(payload.get("code")) is not int or payload["code"]!=0:
        return {**base,"kind":"diagnostic","error_code":"http_or_business_failure"}
    data=payload.get("data")
    if not isinstance(data,dict):
        raise ValueError("mapping_changed")
    if url.path==DETAIL:
        if data.get("title")!=p["title"]:
            return None
        group=data.get("groupon_uuid")
        if not identity(group):
            raise ValueError("identity_unconfirmed")
        return {**base,"kind":"detail","group_id":group,"title":data["title"],
                "can_view_stock":quantity_fragment(data.get("groupon_option",{}).get("can_view_stock"))}
    if url.path==VISITOR:
        group=parse_qs(url.query).get("groupon_uuid",[None])[0]
        admin=data.get("admin")
        if not identity(group) or not isinstance(admin,dict) or not all(k in admin for k in ("admin_id","seller_id")):
            raise ValueError("role_unconfirmed")
        permissions={k:admin.get(k) if type(admin.get(k)) is int else None for k in PERMISSIONS}
        return {**base,"kind":"visitor","group_id":group,"admin_id_nonempty":bool(admin.get("admin_id")),
                "seller_id_nonempty":bool(admin.get("seller_id")),"permissions":permissions}
    items=data.get("list")
    if not isinstance(items,list):
        raise ValueError("mapping_changed")
    if not items:
        return {**base,"kind":"diagnostic","error_code":"no_items_in_response"}
    selected=[]
    groups=set()
    for item in items:
        if not isinstance(item,dict) or not identity(item.get("groupon_uuid")) or not identity(item.get("goods_uuid")) or not isinstance(item.get("title"),str):
            raise ValueError("identity_unconfirmed")
        groups.add(item["groupon_uuid"])
        skus=item.get("sku_list")
        if not isinstance(skus,list) or not skus:
            raise ValueError("unsupported_sku_structure")
        out={k:item[k] for k in ("groupon_uuid","goods_uuid","title")}
        out["sku_list"]=[]
        for sku in skus:
            if not isinstance(sku,dict) or not identity(sku.get("sku_uuid")) or not isinstance(sku.get("title",""),str):
                raise ValueError("identity_unconfirmed")
            target={"sku_uuid":sku["sku_uuid"],"title":sku.get("title","")}
            for field in ("stock","sale"):
                if field in sku:
                    target[field]=quantity_fragment(sku[field])
            out["sku_list"].append(target)
        selected.append(out)
    if len(groups)!=1:
        raise ValueError("mixed_group_response")
    fragment={"code":0,"data":{"list":selected}}
    for field in ("page","size","next"):
        if type(data.get(field)) in (int,bool):
            fragment["data"][field]=data[field]
    return {**base,"kind":"products","group_id":next(iter(groups)),"payload":fragment}


def observation_records(p):
    if not p.get("evidence_file"):
        return []
    file=Path(p["evidence_file"])
    if not file.exists():
        return []
    records=[]
    with file.open("rb") as f:
        for line in f:
            if not line.endswith(b"\n"):
                break
            r=json.loads(line)
            if r.get("profile_id")==p["profile_id"] and r.get("session_id")==p["observation_session"]:
                records.append(r)
    return records


def analyze(p):
    records=observation_records(p)
    groups={}
    for r in records:
        if r.get("kind")=="detail" and r.get("title")==p["title"]:
            groups[r["group_id"]]={"group_id":r["group_id"],"title":r["title"],"role_confirmed":False,
                                   "products":{},"product_events":[],"role_evidence":None}
    for r in records:
        group=groups.get(r.get("group_id"))
        if group is None:
            continue
        if r.get("kind")=="visitor":
            okay=(r.get("admin_id_nonempty") is False and r.get("seller_id_nonempty") is False
                  and all(type(r.get("permissions",{}).get(k)) is int and r["permissions"][k]==0 for k in PERMISSIONS))
            group.update(role_confirmed=okay,role_evidence=r)
        elif r.get("kind")=="products":
            group["product_events"].append(r)
            for item in r["payload"]["data"]["list"]:
                if item["groupon_uuid"]!=r["group_id"]:
                    raise ValueError("观察文件团单关联不一致")
                for sku in item["sku_list"]:
                    group["products"][(item["goods_uuid"],sku["sku_uuid"])]=dict(
                        product_id=item["goods_uuid"],sku_id=sku["sku_uuid"],product_name=item["title"],
                        sku_name=sku.get("title",""),stock_candidate=sku.get("stock"),sale_candidate=sku.get("sale"),
                        semantics="unconfirmed")
    result=[]
    for g in groups.values():
        g["products"]=list(g["products"].values())
        g["ready"]=bool(g["role_confirmed"] and g["products"] and p.get("participant_declaration"))
        result.append(g)
    return {"groups":result,"diagnostics":[r["error_code"] for r in records if r.get("kind")=="diagnostic"],
            "record_count":len(records),"sample_kind":"actual_passive_observation"}


def mapping_for_profile(profile_id):
    return {"demo":False,"source_confirmed":True,"version":"observed-candidates-1-"+slug(profile_id),
        "success":{"path":["code"],"equals":0},"group_scope":"item","group_path":["groupon_uuid"],
        "items_path":["data","list"],"fields":{"product_id":["goods_uuid"],"product_name":["title"]},
        "sku_path":["sku_list"],"sku_fields":{"sku_id":["sku_uuid"],"sku_name":["title"]},
        "metrics":{},"candidates":{"stock":{"path":["stock"]},"sale":{"path":["sale"]}}}


def config_for(p):
    return ROOT/"configs"/("target."+p["profile_id"]+".local.json")


def db_for(p):
    return ROOT/"data/profiles"/p["profile_id"]/"inventory.sqlite3"


def confirm_profile(profile_id,group_id,reviewed=False):
    p=load_profile(profile_id)
    if not reviewed:
        raise ValueError("请先核对观察到的团单名称与商品，再确认绑定")
    group=next((g for g in analyze(p)["groups"] if g["group_id"]==group_id),None)
    if group is None or not group["ready"]:
        raise ValueError("真实团单、普通角色或商品证据不足，不能启用此团采集")
    if p.get("group_id") and p["group_id"]!=group_id:
        raise ValueError("此档案已绑定其他团单，请新建档案以保留旧数据")
    mapping=mapping_for_profile(profile_id)
    for r in group["product_events"]:
        result=extract(r["payload"],mapping,expected_group=group_id)
        if result.error_code or not result.observations:
            raise ValueError("实际商品结构不符合当前适配器，未启用采集")
    mapping_path=ROOT/"configs"/("mapping."+profile_id+".local.json")
    mapping_path.write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding="utf-8")
    c={"target":{"label":p["title"],"share_text":p["share_text"],"resolved_group_id":group_id,
        "association_evidence":"用户核对分享入口名称/商品；本次详情与商品响应group一致，证据在独立采样文件。"},
       "role":"participant","role_evidence":{"confirmed":True,"method":"用户普通账号声明；本次visitor标识为空且修改权限为0。","observed_at":utcnow()},
       "session_id":"profile-"+profile_id,"mapping_file":mapping_path.name,
       "queue_file":str(ROOT/"data/profiles"/profile_id/"events.jsonl"),
       "database_file":str(db_for(p)),"network":{"listen_port":p["proxy_port"],"upstream":p.get("upstream","")},
       "capture":{"enabled":True,"allowed_hosts":[HOST],"max_decoded_body_bytes":2097152,"endpoint_rules":[
           {"alias":"participant_goods_batch","host":HOST,"path":GOODS,"method":"GET","readonly_confirmed":True,
            "evidence":"本次从分享入口正常进入后实际收到的商品查询响应，未调用/重放任何业务请求。"}],
           "require_participant_role":True,"role_check_path":VISITOR,
           "role_state_file":str(ROOT/"secrets/profiles"/profile_id/"role-state.json")},
       "polling":{"enabled":False}}
    path=config_for(p)
    path.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")
    loaded=load_config(path)
    validate_capture(loaded)
    db=connect(db_for(p))
    try:
        with db:
            for r in group["product_events"]:
                meta={k:r[k] for k in ("event_id","observed_at","host","path","method","http_status")}
                meta.update(session_id=c["session_id"],role="participant")
                write_event(db,event_from_payload(r["payload"],mapping,mode="passive",config=loaded,metadata=meta))
    finally:
        db.close()
    p.update(group_id=group_id,phase="ready",confirmed_at=utcnow())
    save_profile(p)
    return {"profile_id":profile_id,"product_skus":len(group["products"]),"quantity_semantics":"unconfirmed"}


def sync_profile(profile_id):
    p=load_profile(profile_id)
    if not p.get("group_id"):
        raise ValueError("请先观察并确认绑定新团")
    result=ingest(load_config(config_for(p)),db_for(p))
    db=connect(db_for(p),readonly=True)
    try:
        rows=current(db,"passive")
        candidates=candidate_current(db,"passive")
    finally:
        db.close()
    folder=ROOT/"exports"/profile_id
    folder.mkdir(parents=True,exist_ok=True)
    export_csv(rows,folder/"inventory.csv")
    export_candidates(candidates,folder/"candidates.csv")
    return {**result,"products":len(rows),"candidate_fields":len(candidates),"export_folder":str(folder)}


def state_path(p):
    return ROOT/"secrets/profiles"/p["profile_id"]/"process.json"


def process_info(pid):
    if os.name!="nt":
        raise ValueError("当前服务管理入口用于Windows")
    command=("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
             "Get-CimInstance Win32_Process -Filter 'ProcessId="+str(int(pid))+"' | "
             "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
    result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
        capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError("无法核对本地进程身份；请在任务管理器核对本团记录的PID后手动停止，工具不会结束未知进程")
    output=result.stdout.decode("utf-8-sig").strip()
    return json.loads(output) if output else None


def owned_process(info,state):
    if not info:
        return False
    def normalized(path):
        return os.path.normcase(os.path.realpath(str(path)))
    exe=normalized(info.get("ExecutablePath") or "")
    cmd=str(info.get("CommandLine") or "")
    expected=state.get("expected_executables") or [sys.executable,getattr(sys,"_base_executable",sys.executable)]
    try:
        Path(state["marker"]).resolve().relative_to(ROOT.resolve())
        Path(state["addon"]).resolve().relative_to(ROOT.resolve())
    except (ValueError,KeyError,TypeError):
        return False
    return (exe in {normalized(path) for path in expected}
            and "mitmdump" in cmd and state["marker"] in cmd and state["addon"] in cmd)


def stop_session(profile_id):
    p=load_profile(profile_id)
    path=state_path(p)
    if not path.exists():
        return {"stopped":False,"note":"此团没有由自助入口启动的进程"}
    state=load_json(path)
    owned=_managed.get(profile_id)
    if owned is not None and owned.pid==state["pid"]:
        if owned.poll() is None:
            owned.terminate()
            owned.wait(timeout=10)
        _managed.pop(profile_id,None)
        path.unlink(missing_ok=True)
        return {"stopped":True,"note":"本团服务已停止；请确认Windows代理已恢复原设置"}
    info=process_info(state["pid"])
    if info is not None:
        if not owned_process(info,state):
            raise ValueError("进程身份已变化，未停止任何进程")
        os.kill(int(state["pid"]),signal.SIGTERM)
    path.unlink(missing_ok=True)
    return {"stopped":True,"note":"请将Windows代理恢复到原设置；工具没有自动修改系统代理"}


def port_available(port):
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1",port))
        return True
    except OSError:
        return False


def listening_pid(port):
    """Inspect local listener state without opening a TCP probe connection."""
    if os.name!="nt":
        raise ValueError("当前服务管理入口用于Windows")
    binary=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/netstat.exe"
    result=subprocess.run([str(binary),"-ano","-p","tcp"],capture_output=True,timeout=5,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError("无法检查本地监听状态")
    for line in result.stdout.decode("ascii",errors="ignore").splitlines():
        parts=line.split()
        if len(parts)>=5 and parts[0]=="TCP" and parts[1]=="127.0.0.1:"+str(port) and parts[3]=="LISTENING" and parts[4].isdigit():
            return int(parts[4])
    return None


def start_session(profile_id,phase,participant=False):
    p=load_profile(profile_id)
    if phase not in ("observe","capture"):
        raise ValueError("未知启动阶段")
    if phase=="observe" and not participant:
        raise ValueError("请确认已用普通账号从该链接进入且无管理权限")
    if phase=="capture":
        capture_config=load_config(config_for(p))
        validate_capture(capture_config)
        if p.get("group_id")!=capture_config["target"]["resolved_group_id"]:
            raise ValueError("此档案尚未绑定相同的真实团单")
    if state_path(p).exists():
        stop_session(profile_id)
    port=p["proxy_port"]
    # Windows may briefly hold an accepted socket after a previous process exits.
    # Do not create another client connection just to test startup readiness.
    for _ in range(20):
        if port_available(port):
            break
        if listening_pid(port) is not None:
            break
        time.sleep(.1)
    if not port_available(port):
        raise ValueError("代理端口被占用或无权限；先停止对应团单的自助服务，或新建时选择其他空闲端口")
    folder=ROOT/"secrets/profiles"/profile_id
    folder.mkdir(parents=True,exist_ok=True)
    if phase=="observe":
        session=uuid.uuid4().hex
        p.update(observation_session=session,evidence_file=str(folder/("observe-"+session+".jsonl")),
                 participant_declaration=True,phase="observing")
        save_profile(p)
        addon=ROOT/"capture/setup_addon.py"
        marker=str(profile_path(profile_id).resolve())
        addon_options=["--set","setup_profile="+marker]
    else:
        addon=ROOT/"capture/inventory_addon.py"
        marker=str(config_for(p).resolve())
        addon_options=["--set","inventory_config="+marker]
    args=[sys.executable,"-u","-c","from mitmproxy.tools.main import mitmdump; mitmdump()","-q",
          "--listen-host","127.0.0.1","--listen-port",str(port),"--set","confdir="+str(ROOT/"secrets/mitmproxy"),
          "--allow-hosts","^"+re.escape(HOST)+"(:[0-9]+)?$","-s",str(addon),*addon_options]
    if p.get("upstream"):
        args += ["--mode","upstream:"+p["upstream"]]
    with (folder/"proxy.log").open("ab",buffering=0) as log:
        proc=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    state={"pid":proc.pid,"phase":phase,"marker":marker,"addon":str(addon),"started_at":utcnow(),
           "expected_executables":list({str(Path(sys.executable).resolve()),str(Path(getattr(sys,"_base_executable",sys.executable)).resolve())})}
    _managed[profile_id]=proc
    state_path(p).write_text(json.dumps(state,indent=2),encoding="utf-8")
    for _ in range(50):
        if proc.poll() is not None:
            state_path(p).unlink(missing_ok=True)
            _managed.pop(profile_id,None)
            p["phase"]="observation_failed" if phase=="observe" else "ready"
            save_profile(p)
            raise ValueError("代理未能启动，请查看本团本地proxy.log；不会修改系统代理或关闭证书校验")
        listener=listening_pid(port)
        if listener is not None:
            state["listener_pid"]=listener
            state_path(p).write_text(json.dumps(state,indent=2),encoding="utf-8")
            break
        time.sleep(.1)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        state_path(p).unlink(missing_ok=True)
        _managed.pop(profile_id,None)
        p["phase"]="observation_failed" if phase=="observe" else "ready"
        save_profile(p)
        raise ValueError("代理启动超时，已停止本次启动的进程")
    if phase=="capture":
        p["phase"]="capturing"
        save_profile(p)
    return {"started":True,"profile_id":profile_id,"phase":phase,"proxy_port":port}
