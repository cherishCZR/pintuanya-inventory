import os
import pytest
from test_release import module

installer=module("install_windows")
SUPPORTED={"os":"win32","implementation":"CPython","version":[3,12,14],"bits":64,"abi":"win-amd64","windows_major":10}


@pytest.mark.parametrize("changes",[{"os":"linux"},{"implementation":"PyPy"},{"version":[3,13,0]},
    {"bits":32},{"abi":"win-arm64"},{"windows_major":6}])
def test_reject_unsupported_runtime(changes):
    with pytest.raises(ValueError):
        installer.validate_runtime({**SUPPORTED,**changes})


def test_supported_runtime_and_isolated_child_env(monkeypatch):
    installer.validate_runtime(SUPPORTED)
    monkeypatch.setenv("PYTHONHOME","unrelated")
    monkeypatch.setenv("PYTHONPATH","unrelated")
    env=installer.child_env()
    assert "PYTHONHOME" not in env and "PYTHONPATH" not in env
    assert env["PYTHONIOENCODING"]=="utf-8"
    assert os.environ["PYTHONHOME"]=="unrelated"


@pytest.mark.parametrize("line",["package>=1","package==1; other","package @ file://local","package==1==2","-e==local","a==1\nA==2"])
def test_lock_refuses_ranges_paths_and_duplicates(tmp_path,line):
    (tmp_path/"requirements.lock").write_text(line,encoding="utf-8")
    with pytest.raises(ValueError):
        installer.expected_versions(tmp_path)


def test_exact_versions(tmp_path):
    (tmp_path/"requirements.lock").write_text("# pinned\nBrotli==1.2.1\nfoo-bar==0.1.0a1\n",encoding="utf-8")
    assert installer.expected_versions(tmp_path)=={"Brotli":"1.2.1","foo-bar":"0.1.0a1"}
