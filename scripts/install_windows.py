"""Project-local Windows bootstrap. Never changes proxies, trust stores or PATH."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]


def validate_runtime(info):
    if info.get("os")!="win32" or info.get("implementation")!="CPython":
        raise ValueError("This installer supports Windows CPython only.")
    if info.get("version",[])[:2]!=[3,12] or info.get("bits")!=64 or info.get("abi")!="win-amd64":
        raise ValueError("Install CPython 3.12 x64. Other Python versions/architectures are not supported by this alpha.")
    if info.get("windows_major",0)<10:
        raise ValueError("Windows 10/11 x64 is the target. Earlier Windows versions are not supported.")


def runtime_info():
    return {"os":sys.platform,"implementation":platform.python_implementation(),"version":list(sys.version_info[:3]),
            "bits":struct.calcsize("P")*8,"abi":sysconfig.get_platform(),
            "windows_major":sys.getwindowsversion().major if sys.platform=="win32" else 0}


def child_env():
    env=os.environ.copy()
    # Prevent an unrelated global Python configuration from leaking into .venv.
    env.pop("PYTHONHOME",None)
    env.pop("PYTHONPATH",None)
    env["PYTHONIOENCODING"]="utf-8"
    return env


def expected_versions(root=ROOT):
    versions={}
    for line in (root/"requirements.lock").read_text(encoding="utf-8-sig").splitlines():
        line=line.strip()
        if line and not line.startswith("#"):
            name,separator,version=line.partition("==")
            if (not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",name)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*",version) or name.lower() in {x.lower() for x in versions}):
                raise ValueError("The lock file must contain exact package==version entries only.")
            versions[name]=version
    return versions


def check_environment(root=ROOT):
    validate_runtime(runtime_info())
    expected=expected_versions(root)
    import tomllib
    expected["pintuanya-inventory"]=tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    missing=[]
    mismatched=[]
    for name,version in expected.items():
        try:
            actual=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
        else:
            if actual!=version:
                mismatched.append(name)
    if missing or mismatched:
        raise ValueError("Dependencies missing or different from requirements.lock. Run install-windows.cmd again. "
                         +"Missing: "+", ".join(missing)+"; mismatched: "+", ".join(mismatched))
    return {"python":".".join(map(str,sys.version_info[:3])),"abi":sysconfig.get_platform(),
            "project_version":expected["pintuanya-inventory"],"locked_packages_checked":len(expected)-1,
            "proxy_or_certificate_changes":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Check current interpreter and locked dependencies only")
    parser.add_argument("--cache-dir",type=Path,help="Optional pip cache, otherwise project-local .cache/pip")
    args=parser.parse_args(argv)
    try:
        if args.check:
            print(json.dumps(check_environment(),indent=2))
            return 0
        validate_runtime(runtime_info())
        python=ROOT/".venv/Scripts/python.exe"
        env=child_env()
        if not python.exists():
            print("Creating project-local .venv...",flush=True)
            subprocess.run([sys.executable,"-m","venv",str(ROOT/".venv")],cwd=ROOT,env=env,check=True)
        else:
            probe="import json,sys,struct,sysconfig; print(json.dumps([list(sys.version_info[:2]),struct.calcsize('P')*8,sysconfig.get_platform()]))"
            result=subprocess.run([str(python),"-c",probe],cwd=ROOT,env=env,check=True,capture_output=True,text=True)
            if json.loads(result.stdout)!=[[3,12],64,"win-amd64"]:
                raise ValueError("Existing .venv has an unsupported interpreter; keep a backup and recreate it with CPython 3.12 x64.")
        cache=(args.cache_dir or ROOT/".cache/pip").resolve()
        cache.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(python),"-m","pip","install","--disable-pip-version-check","--cache-dir",str(cache),
                        "-r",str(ROOT/"requirements.lock")],cwd=ROOT,env=env,check=True)
        subprocess.run([str(python),"-m","pip","install","--disable-pip-version-check","--no-deps","--no-build-isolation","-e",str(ROOT)],
                       cwd=ROOT,env=env,check=True)
        subprocess.run([str(python),"-m","pip","check"],cwd=ROOT,env=env,check=True)
        subprocess.run([str(python),str(Path(__file__).resolve()),"--check"],cwd=ROOT,env=env,check=True)
        print("Installation complete. Double-click start-self-service.cmd and open http://127.0.0.1:8502",flush=True)
        return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print("Installation/check failed: "+str(exc),file=sys.stderr)
        print("Use CPython 3.12 x64 and a writable extracted project folder. No system settings were changed.",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
