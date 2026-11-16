import argparse
import json
import re
import sys
import subprocess
from pathlib import Path
from .config import ROOT, load_config, load_json, resolve, validate_capture
from .discover import discover
from .doctor import doctor
from .export import export_csv, export_candidates
from .ingest import ingest
from .pipeline import event_from_payload
from .storage import connect, current, run_summary, write_event, candidate_current


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(description="普通参团账号诊断；所有 DEMO 数据均为模拟，不代表线上成功")
    p.add_argument("--db", type=Path, default=ROOT / "data/inventory.sqlite3")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("demo")
    d = sub.add_parser("discover")
    d.add_argument("--input", type=Path, required=True)
    i = sub.add_parser("import-json")
    i.add_argument("--input", type=Path, required=True)
    i.add_argument("--mapping", type=Path)
    i.add_argument("--mode", choices=("demo", "passive"), required=True)
    i.add_argument("--config", type=Path)
    i.add_argument("--metadata", type=Path)
    for name in ("ingest", "capture-command", "fetch-once", "poll"):
        c = sub.add_parser(name)
        c.add_argument("--config", type=Path, required=True)
        if name == "poll":
            c.add_argument("--max-cycles", type=int, default=5)
    for name in ("status", "export", "export-candidates"):
        c = sub.add_parser(name)
        c.add_argument("--mode", choices=("demo", "passive", "active"), default="passive")
        if name in ("export", "export-candidates"):
            c.add_argument("--output", type=Path, required=True)
    sub.add_parser("init-config")
    sub.add_parser("profile-list")
    new=sub.add_parser("profile-new")
    new.add_argument("--title",required=True)
    new.add_argument("--share-text",required=True)
    new.add_argument("--name")
    new.add_argument("--proxy-port",type=int,default=8082)
    new.add_argument("--upstream",default="")
    for name in ("profile-observe","profile-confirm","profile-start","profile-stop","profile-sync","profile-status"):
        c=sub.add_parser(name)
        c.add_argument("--profile",required=True)
        if name=="profile-observe":
            c.add_argument("--participant",action="store_true")
        if name=="profile-confirm":
            c.add_argument("--group-id",required=True)
            c.add_argument("--reviewed",action="store_true")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command.startswith("profile-"):
            from . import self_service as service
            if args.command=="profile-list":
                output([{"profile_id":p["profile_id"],"title":p["title"],"phase":p["phase"]} for p in service.profiles()])
            elif args.command=="profile-new":
                p=service.create_profile(args.title,args.share_text,args.name,args.proxy_port,args.upstream)
                output({"profile_id":p["profile_id"],"title":p["title"],"phase":p["phase"]})
            elif args.command=="profile-observe":
                output(service.start_session(args.profile,"observe",participant=args.participant))
            elif args.command=="profile-confirm":
                output(service.confirm_profile(args.profile,args.group_id,args.reviewed))
            elif args.command=="profile-start":
                output(service.start_session(args.profile,"capture"))
            elif args.command=="profile-stop":
                output(service.stop_session(args.profile))
            elif args.command=="profile-sync":
                output(service.sync_profile(args.profile))
            elif args.command=="profile-status":
                result=service.analyze(service.load_profile(args.profile))
                for group in result["groups"]:
                    group.pop("product_events",None)
                    group.pop("role_evidence",None)
                output(result)
        elif args.command == "doctor":
            output(doctor())
        elif args.command == "init-config":
            path = ROOT / "configs/target.local.json"
            if path.exists():
                output({"config": str(path), "note": "已存在，保留原文件"})
            else:
                path.write_text((ROOT / "configs/target.example.json").read_text(encoding="utf-8"), encoding="utf-8")
                output({"config": str(path), "note": "尚未确认角色/团单/主机/端点/映射；采集关闭"})
        elif args.command == "discover":
            output(discover(load_json(args.input)))
        elif args.command in ("demo", "import-json"):
            if args.command == "demo":
                payload = load_json(ROOT / "tests/fixtures/demo_exact.json")
                mapping = load_json(ROOT / "configs/mapping.demo.json")
                event = event_from_payload(payload, mapping)
            else:
                payload = load_json(args.input)
                if args.mode == "demo":
                    if not args.mapping:
                        raise ValueError("demo 导入需要 --mapping")
                    event = event_from_payload(payload, load_json(args.mapping))
                else:
                    if not args.config or not args.metadata:
                        raise ValueError("真实导入需要 --config 和 --metadata；不能仅声明 participant")
                    c = load_config(args.config)
                    mapping = validate_capture(c)
                    event = event_from_payload(payload, mapping, mode="passive", config=c, metadata=load_json(args.metadata))
                    if event["error_code"] == "wrong_or_unconfirmed_group":
                        raise ValueError("错误或未确认团单关联，拒绝入库")
            with connect(args.db) as db:
                inserted = write_event(db, event)
            if args.command == "demo":
                with connect(args.db, readonly=True) as db:
                    export_csv(current(db, "demo"), ROOT / "exports/demo_inventory.csv")
            output({"mode": event["mode"], "status": event["status"], "error_code": event["error_code"],
                    "observed_count": len(event["observations"]), "inserted": inserted,
                    "note": "模拟演示，不是普通账号实测" if event["mode"] == "demo" else "本地导入；来源以采样证据为准"})
        elif args.command == "ingest":
            output(ingest(load_config(args.config), args.db))
        elif args.command in ("fetch-once", "poll"):
            raise ValueError("主动查询尚未实现：没有普通账号真实只读端点、会话独立调用及字段语义证据；保留离线与被动模式")
        elif args.command == "capture-command":
            c = load_config(args.config)
            validate_capture(c)
            addon = ROOT / "capture/inventory_addon.py"
            # PowerShell single quotes protect paths and literal regex characters.
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            executable = Path(sys.executable).parent / "mitmdump.exe"
            network=c.get("network",{})
            from .self_service import validate_network
            listen_port=network.get("listen_port",8080)
            upstream=network.get("upstream","")
            validate_network(listen_port,upstream)
            parts = ["&", quote(executable), "-q", "--listen-host", "127.0.0.1", "--listen-port", str(listen_port),
                     "--set", quote("confdir=" + str(ROOT / "secrets/mitmproxy")),
                     "--set", quote("inventory_config=" + c["_path"]), "-s", quote(addon)]
            if upstream:
                parts.extend(["--mode",quote("upstream:"+upstream.rstrip("/"))])
            for host in c["capture"]["allowed_hosts"]:
                parts.extend(["--allow-hosts", quote("^" + re.escape(host) + "(:[0-9]+)?$")])
            print(" ".join(parts))
        elif args.command in ("status", "export", "export-candidates"):
            if args.db.exists():
                with connect(args.db, readonly=True) as db:
                    rows = current(db, args.mode)
                    runs = run_summary(db, args.mode)
                    candidates = candidate_current(db, args.mode)
            else:
                rows, runs, candidates = [], [], []
            if args.command == "export":
                export_csv(rows, args.output)
                output({"mode": args.mode, "rows": len(rows), "output": str(args.output.resolve())})
            elif args.command == "export-candidates":
                export_candidates(candidates,args.output)
                output({"mode":args.mode,"rows":len(candidates),"semantics":"unconfirmed","output":str(args.output.resolve())})
            else:
                output({"mode": args.mode, "verification": "普通账号验证尚未完成" if not runs else "查看采样证据；运行结果不自动证明账号权限",
                        "observations": rows, "candidate_evidence": candidates, "latest_runs": runs})
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        # Never echo arbitrary values or raw JSON decode errors into a report.
        if type(exc) is ValueError and not any(s in str(exc).lower() for s in ("isoformat", "invalid literal", "decode")):
            print(str(exc), file=sys.stderr)
        else:
            print("输入/配置/文件不可用；请检查格式和本地路径（未输出原始内容）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
