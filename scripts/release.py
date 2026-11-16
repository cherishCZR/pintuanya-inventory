"""Build only the reviewed static public file list. Never package a workspace."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BLOCKED_PARTS={"secrets","data","exports","local_notes",".venv",".tools",".cache",".git","dist","__pycache__",".pytest_cache"}
RULES={
    "private_key":re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "github_token":re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "api_key":re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "query_credential":re.compile(r"[?&](?:token|access_token|authorization|session_key)=[A-Za-z0-9._~-]{24,}",re.I),
    "bearer_credential":re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{24,}",re.I),
    "personal_windows_path":re.compile(r"\b[A-Za-z]:[\\/](?:Users[\\/][^\\/\s\"']+|study[\\/])",re.I),
    "real_share_link":re.compile(r"#小程序://"+r"拼团呀/[^\s\"'<>]+")
}


def safe_relative(name):
    if not isinstance(name,str) or not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("Invalid public file path")
    p=PurePosixPath(name)
    if ("\\" in name or p.is_absolute() or ":" in name
            or any(part in ("..",".") or part.lower() in BLOCKED_PARTS or part.endswith(".egg-info") for part in p.parts)
            or ".local." in p.name or p.name.startswith(".env")
            or p.suffix.lower() in (".pem",".key",".p12",".pfx",".har",".mitm",".pyc",".sqlite3")
            or p.name.lower().endswith((".har.gz",".sqlite3-wal",".sqlite3-shm"))):
        raise ValueError("Forbidden public file path: "+str(name))
    return p


def scan_text(name,text):
    return [name+": "+label for label,pattern in RULES.items() if pattern.search(text)]


def load_manifest(root=ROOT):
    document=json.loads((root/"release-files.json").read_text(encoding="utf-8"))
    paths=document["files"]
    if not isinstance(paths,list) or not all(isinstance(x,str) for x in paths) or len(paths)!=len({x.lower() for x in paths}):
        raise ValueError("Release manifest contains invalid/duplicate paths")
    for name in paths:
        safe_relative(name)
    if not {"LICENSE","README.md","install-windows.cmd","start-self-service.cmd","requirements.lock","release-files.json"}.issubset(paths):
        raise ValueError("Release manifest lacks required public files")
    if not re.fullmatch(r"[0-9A-Za-z.-]+",document["release_version"]):
        raise ValueError("Invalid release version")
    project=tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]
    if document["package_version"]!=project["version"]:
        raise ValueError("Manifest/package version mismatch")
    return document


def verify(root=ROOT,check_index=False):
    root=root.resolve()
    document=load_manifest(root)
    failures=[]
    total=0
    for name in document["files"]:
        path=root.joinpath(*safe_relative(name).parts)
        path.resolve().relative_to(root)
        if not path.is_file():
            failures.append(name+": missing")
            continue
        for component in (path,*path.parents):
            if component==root:
                break
            if component.is_symlink() or (hasattr(component,"is_junction") and component.is_junction()):
                failures.append(name+": symlink/junction is not a release source")
        content=path.read_bytes()
        total+=len(content)
        if len(content)>2_097_152:
            failures.append(name+": unexpected source file size")
        try:
            text=content.decode("utf-8-sig")
        except UnicodeError:
            failures.append(name+": source must be UTF-8 text")
        else:
            failures.extend(scan_text(name,text))
    if check_index:
        tracked=subprocess.run(["git","ls-files","-z"],cwd=root,check=True,capture_output=True).stdout.decode("utf-8").split("\0")
        allowed=set(document["files"])
        failures.extend(name+": outside reviewed public list" for name in tracked if name and name not in allowed)
    if failures:
        # Print rule names and filenames only, never a matched credential value.
        raise ValueError("Release verification failed:\n"+"\n".join(failures))
    return {"release_version":document["release_version"],"files":len(document["files"]),"source_bytes":total,
            "sensitive_pattern_matches":0,"git_index_checked":check_index}


def verify_archive(archive,root=ROOT):
    document=load_manifest(root)
    prefix="pintuanya-inventory-"+document["release_version"]+"/"
    expected={prefix+name for name in document["files"]}|{prefix+"FILE_MANIFEST.sha256"}
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist())!=expected or len(z.namelist())!=len(expected):
            raise ValueError("Archive member list differs from the reviewed manifest")
        checks={}
        for line in z.read(prefix+"FILE_MANIFEST.sha256").decode("ascii").splitlines():
            digest,name=line.split("  ",1)
            checks[name]=digest
        if set(checks)!=set(document["files"]):
            raise ValueError("Archive checksum manifest is incomplete")
        for name in document["files"]:
            info=z.getinfo(prefix+name)
            if info.file_size>2_097_152:
                raise ValueError("Archive source member too large")
            content=z.read(prefix+name)
            if hashlib.sha256(content).hexdigest()!=checks[name]:
                raise ValueError("Archive checksum mismatch: "+name)
            if content!=(root/name).read_bytes():
                raise ValueError("Archive is stale or differs from reviewed source: "+name)
            failures=scan_text(name,content.decode("utf-8-sig"))
            if failures:
                raise ValueError("\n".join(failures))
    return {"archive_verified":True,"files":len(document["files"])}


def build(root=ROOT):
    summary=verify(root)
    document=load_manifest(root)
    folder=root/"dist"
    folder.mkdir(exist_ok=True)
    archive=folder/("pintuanya-inventory-"+document["release_version"]+"-windows-source.zip")
    prefix="pintuanya-inventory-"+document["release_version"]+"/"
    hashes=[]
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for name in document["files"]:
            content=(root/name).read_bytes()
            z.writestr(prefix+name,content)
            hashes.append(hashlib.sha256(content).hexdigest()+"  "+name)
        z.writestr(prefix+"FILE_MANIFEST.sha256","\n".join(hashes)+"\n")
    verify_archive(archive,root)
    (folder/"SHA256SUMS.txt").write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+"  "+archive.name+"\n",encoding="ascii")
    return {**summary,"archive":str(archive.resolve()),"archive_verified":True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("verify","build","verify-archive"))
    parser.add_argument("--git-index",action="store_true")
    parser.add_argument("--archive",type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=="build":
            result=build()
        elif args.command=="verify-archive":
            if not args.archive:
                raise ValueError("--archive is required")
            result=verify_archive(args.archive)
        else:
            result=verify(check_index=args.git_index)
        print(json.dumps(result,indent=2))
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print(str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
