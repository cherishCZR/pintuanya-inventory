import importlib.metadata
import os
import platform
import re
import shutil
import socket
import sys
from pathlib import Path


def doctor():
    info = {"python": sys.version.split()[0], "executable": sys.executable, "platform": platform.platform(),
            "tools": {name: shutil.which(name) or (str(Path(sys.executable).parent / (name + ".exe"))
                       if (Path(sys.executable).parent / (name + ".exe")).exists() else None)
                      for name in ("mitmweb", "mitmdump", "uv")},
            "packages": {}, "ports": {}, "proxy_environment": {},
            "ordinary_account_verification": "not_assessed_by_environment_doctor; see evidence_report.md"}
    for name in ("streamlit", "pytest", "mitmproxy"):
        try:
            info["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            info["packages"][name] = None
    for port in (8080, 8081, 8082, 8501, 8502):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
            info["ports"][str(port)] = "bind_available"
        except OSError:
            info["ports"][str(port)] = "occupied_or_permission_denied"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        info["proxy_environment"][name] = bool(os.environ.get(name))
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                def read(name):
                    try:
                        return winreg.QueryValueEx(key, name)[0]
                    except FileNotFoundError:
                        return None
                info["system_proxy"] = {"enabled": bool(read("ProxyEnable")),
                                        "server_configured": bool(read("ProxyServer")),
                                        "pac_configured": bool(read("AutoConfigURL"))}
                server = str(read("ProxyServer") or "")
                local = re.fullmatch(r"(?:http=)?(127\.0\.0\.1|localhost):(\d{1,5})", server)
                if local:
                    info["system_proxy"]["loopback_endpoint"] = local.group(1) + ":" + local.group(2)
        except OSError:
            info["system_proxy"] = "unavailable"
    info["note"] = "只检查，不修改代理、证书、防火墙；工具存在不代表已捕获微信响应"
    return info
