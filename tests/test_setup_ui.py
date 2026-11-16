"""Self-service UI offline checks. No new group has been tested online here."""
import json
import socket
from pathlib import Path
from streamlit.testing.v1 import AppTest
from pintuanya_inventory import config,self_service


def test_setup_ui_refresh_never_starts_proxy_or_remote_calls(tmp_path,monkeypatch):
    script=config.ROOT/"src/pintuanya_inventory/setup_ui.py"
    monkeypatch.setattr(config,"ROOT",tmp_path)
    monkeypatch.setattr(self_service,"ROOT",tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError("Rerun must not start a proxy or request a remote service")
    monkeypatch.setattr(self_service,"start_session",forbidden)
    monkeypatch.setattr(socket,"create_connection",forbidden)
    app=AppTest.from_file(str(script),default_timeout=20).run()
    assert not app.exception
    text={i.label:i for i in app.text_input}
    text["微信里显示的团单完整名称"].set_value("独立新团")
    text["保存代号（选填，留空自动生成）"].set_value("standalone")
    app.text_area[0].set_value("#小程序://测试/入口/NEW_SHARE")
    next(b for b in app.button if b.label=="创建新团").click().run()
    assert not app.exception
    assert self_service.load_profile("standalone")["group_id"] is None
    observe=next(b for b in app.button if b.label=="启动 / 重新开始5分钟观察")
    assert observe.disabled
    next(b for b in app.button if b.label=="读取观察结果（仅本地）").click().run()
    assert not app.exception
    assert not (tmp_path/"secrets/profiles/standalone/process.json").exists()
