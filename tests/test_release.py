"""Public packaging contracts use synthetic source only, never local captures."""
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest


def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/"scripts"/(name+".py"))
    loaded=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


release=module("release")


@pytest.fixture
def source(tmp_path):
    root=tmp_path/"源代码 with spaces"
    root.mkdir()
    files=["LICENSE","README.md","install-windows.cmd","start-self-service.cmd","requirements.lock","pyproject.toml","release-files.json"]
    for name in files[:-1]:
        (root/name).write_text("Public synthetic test source\n",encoding="utf-8")
    (root/"pyproject.toml").write_text('[project]\nversion="0.1.0a1"\n',encoding="utf-8")
    (root/"release-files.json").write_text(json.dumps({"release_version":"0.1.0-alpha.1","package_version":"0.1.0a1","files":files}),encoding="utf-8")
    return root


@pytest.mark.parametrize("name",[None,12,"","../secret","/absolute","a/../b","a/./b","a//b","C:/secret","a\\b",
    "SECRETS/file.json","configs/target.local.json",".env","sample.har.gz","db.sqlite3-wal","x.pem","src/a.egg-info/meta"])
def test_reject_forbidden_paths(name):
    with pytest.raises(ValueError):
        release.safe_relative(name)


def test_allowlist_excludes_unlisted_private_files(source):
    private=source/"secrets"
    private.mkdir()
    (private/"private.txt").write_text("must remain local",encoding="utf-8")
    result=release.build(source)
    assert result["sensitive_pattern_matches"]==0
    assert release.verify_archive(result["archive"],source)["archive_verified"]
    with zipfile.ZipFile(result["archive"]) as archive:
        assert not any("secrets" in name for name in archive.namelist())
        assert len(archive.namelist())==result["files"]+1
    assert (source/"dist/SHA256SUMS.txt").is_file()


def test_sensitive_content_blocks_release_without_echoing_value(source):
    credential="ghp"+"_"+"A"*30
    (source/"README.md").write_text(credential,encoding="utf-8")
    with pytest.raises(ValueError) as error:
        release.build(source)
    assert "github_token" in str(error.value)
    assert credential not in str(error.value)
    assert not (source/"dist").exists()


@pytest.mark.parametrize("mode",["extra","modified","duplicate"])
def test_archive_rejects_tampering(source,mode):
    archive=Path(release.build(source)["archive"])
    with zipfile.ZipFile(archive) as z:
        members={name:z.read(name) for name in z.namelist()}
    readme=next(name for name in members if name.endswith("/README.md"))
    if mode=="extra":
        members["extra.txt"]=b"unreviewed"
    elif mode=="modified":
        members[readme]=b"changed"
    with zipfile.ZipFile(archive,"w") as z:
        for name,content in members.items():
            z.writestr(name,content)
        if mode=="duplicate":
            with pytest.warns(UserWarning):
                z.writestr(readme,b"duplicate")
    with pytest.raises(ValueError):
        release.verify_archive(archive,source)


def test_manifest_rejects_invalid_or_duplicate_entries(source):
    path=source/"release-files.json"
    document=json.loads(path.read_text())
    for extra in ("readme.MD",42,"secrets/capture.json"):
        altered={**document,"files":document["files"]+[extra]}
        path.write_text(json.dumps(altered))
        with pytest.raises(ValueError):
            release.load_manifest(source)


def test_symlink_is_not_publishable(source,tmp_path):
    target=tmp_path/"outside.txt"
    target.write_text("outside",encoding="utf-8")
    readme=source/"README.md"
    readme.unlink()
    try:
        readme.symlink_to(target)
    except OSError:
        pytest.skip("Creating a symlink requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError):
        release.verify(source)

