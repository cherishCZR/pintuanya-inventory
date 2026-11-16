"""Checked local UI launcher. Does not alter network or trust settings."""
import argparse
from pathlib import Path
import socket
import subprocess
import sys
from install_windows import check_environment, child_env

ROOT=Path(__file__).resolve().parents[1]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view",choices=("setup","inventory"),default="setup")
    parser.add_argument("--port",type=int)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args(argv)
    try:
        check_environment(ROOT)
        if args.check:
            print("Environment ready; no service started.")
            return 0
        port=args.port or (8502 if args.view=="setup" else 8501)
        if not 1024<=port<=65535:
            raise ValueError("UI port must be 1024..65535.")
        try:
            with socket.socket() as server:
                server.bind(("127.0.0.1",port))
        except OSError:
            raise ValueError(f"Port {port} is occupied or unavailable. Use the existing instance or choose --port; no process was stopped.") from None
        script=ROOT/"src/pintuanya_inventory"/("setup_ui.py" if args.view=="setup" else "ui.py")
        print(f"Open http://127.0.0.1:{port} in your browser. Keep this window open.",flush=True)
        return subprocess.call([sys.executable,"-m","streamlit","run",str(script),"--server.address","127.0.0.1",
            "--server.port",str(port),"--server.headless","true","--browser.gatherUsageStats","false"],cwd=ROOT,env=child_env())
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr)
        print("If installation is incomplete, run install-windows.cmd first.",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
