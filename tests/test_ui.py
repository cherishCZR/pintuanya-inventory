"""Offline UI acceptance: source separation, refresh and read-only storage."""
import socket
from streamlit.testing.v1 import AppTest
from pintuanya_inventory import config
from pintuanya_inventory.pipeline import event_from_payload
from pintuanya_inventory.storage import connect, write_event


def test_ui_source_refresh_and_no_network(tmp_path,monkeypatch,mapping,payload):
    ui = config.ROOT/"src/pintuanya_inventory/ui.py"
    db_path = tmp_path/"data/inventory.sqlite3"
    with connect(db_path) as db:
        write_event(db,event_from_payload(payload,mapping))
    monkeypatch.setattr(config,"ROOT",tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError("UI must not make remote connections")
    monkeypatch.setattr(socket,"create_connection",forbidden)
    app = AppTest.from_file(str(ui),default_timeout=15).run()
    assert not app.exception
    assert not app.dataframe
    assert any("普通账号验证尚未完成" in w.value for w in app.warning)
    app.radio[0].set_value("DEMO 模拟演示").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 3
    app.button[0].click().run()
    assert not app.exception
    with connect(db_path,readonly=True) as db:
        assert db.execute("SELECT count(*) FROM collection_runs").fetchone()[0] == 1
