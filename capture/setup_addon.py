"""Five-minute self-service discovery. Only target-matched minimal projections."""
import json
from pathlib import Path
import sys
import time

from mitmproxy import ctx, exceptions

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"capture"))
from inventory_addon import bounded_decode
from pintuanya_inventory.models import utcnow
from pintuanya_inventory.self_service import load_profile, project_response, HOST, PATHS
from urllib.parse import urlsplit


class SetupAddon:
    def load(self,loader):
        loader.add_option("setup_profile",str,"","Absolute self-service profile path")

    def configure(self,updated):
        if "setup_profile" not in updated:
            return
        try:
            file=Path(ctx.options.setup_profile)
            if not file.is_absolute():
                raise ValueError
            data=json.loads(file.read_text(encoding="utf-8-sig"))
            self.profile=load_profile(data["profile_id"])
            if not self.profile["participant_declaration"] or not self.profile["observation_session"]:
                raise ValueError
            self.file=Path(self.profile["evidence_file"])
            self.started=time.monotonic()
            self.groups=set()
            self.roles={}
            self.pending=[]
            self.written=0
        except Exception:
            raise exceptions.OptionsError("Invalid self-service participant observation profile") from None

    def append(self,record):
        if self.written>=1000:
            return
        with self.file.open("a",encoding="utf-8",newline="\n") as f:
            f.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
        self.written+=1

    def accept(self,record):
        kind,group=record["kind"],record.get("group_id")
        if kind=="diagnostic":
            self.append(record)
        elif kind=="detail":
            self.groups.add(group)
            self.append(record)
            pending,self.pending=self.pending,[]
            for r in pending:
                self.accept(r)
        elif group not in self.groups:
            self.pending.append(record)
        elif kind=="visitor":
            ordinary=(record.get("admin_id_nonempty") is False and record.get("seller_id_nonempty") is False
                      and all(type(record.get("permissions",{}).get(k)) is int and record["permissions"][k]==0
                              for k in ("can_modify_groupon","can_modify_member","can_modify_membership")))
            self.roles[group]=ordinary
            self.append(record)
            pending,self.pending=self.pending,[]
            for r in pending:
                if r.get("group_id")!=group or ordinary:
                    self.accept(r)
        elif kind=="products":
            if self.roles.get(group) is True:
                self.append(record)
            elif group not in self.roles:
                self.pending.append(record)
        self.pending=self.pending[-64:]

    def response(self,flow):
        if not hasattr(self,"profile") or time.monotonic()-self.started>300 or flow.response is None:
            return
        request,response=flow.request,flow.response
        path=urlsplit(request.path).path
        if request.host!=HOST or request.method!="GET" or path not in PATHS:
            return
        try:
            if response.status_code in (401,403):
                record=project_response(self.profile,request.method,request.host,request.path,None,response.status_code,flow.id,utcnow())
                if record:
                    self.append(record)
                return
            raw=response.raw_content or b""
            if len(raw)>2097152:
                raise ValueError("body_too_large")
            if "json" not in response.headers.get("content-type","").lower():
                raise ValueError("unsupported_payload")
            payload=json.loads(bounded_decode(raw,response.headers.get("content-encoding","").lower(),2097152))
            record=project_response(self.profile,request.method,request.host,request.path,payload,response.status_code,flow.id,utcnow())
            if record is None:
                return
            self.accept(record)
        except (ValueError,TypeError,KeyError,OverflowError):
            self.append({"profile_id":self.profile["profile_id"],"session_id":self.profile["observation_session"],
                         "kind":"diagnostic","observed_at":utcnow(),"error_code":"unsupported_or_changed_response"})
        except OSError:
            ctx.log.warn("self-service: local evidence write failed; no response content logged")

    def tls_failed_client(self,data):
        if (hasattr(self,"profile") and time.monotonic()-self.started<=300
                and getattr(data.conn,"sni",None)==HOST):
            self.append({"profile_id":self.profile["profile_id"],"session_id":self.profile["observation_session"],
                         "kind":"diagnostic","observed_at":utcnow(),"error_code":"client_tls_failed"})

    def error(self,flow):
        if (hasattr(self,"profile") and time.monotonic()-self.started<=300
                and flow.request.host==HOST and urlsplit(flow.request.path).path in PATHS):
            self.append({"profile_id":self.profile["profile_id"],"session_id":self.profile["observation_session"],
                         "kind":"diagnostic","observed_at":utcnow(),"error_code":"transport_error"})


addons=[SetupAddon()]
