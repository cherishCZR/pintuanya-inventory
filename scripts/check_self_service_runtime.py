"""Actual local process/listener check. Never claims any new group was captured.

Creates a temporary empty profile, starts a loopback proxy without configuring
the OS/browser/WeChat to use it, stops only its own process, and removes the
temporary profile entry. It does not send a business request.
"""
import json
import time
import uuid
from pintuanya_inventory import self_service as s

key="runtime_"+uuid.uuid4().hex[:10]
p=s.create_profile("运行环境检查（不采集团单）","LOCAL-RUNTIME-CHECK-NO-LINK",key,8082,"")
started=False
try:
    status=s.start_session(key,"observe",participant=True)
    started=status["started"]
    loaded=s.load_profile(key)
    count=s.analyze(loaded)["record_count"]
    assert count==0
    # Simulate a UI restart: ownership must be established using saved process
    # identity even when the base interpreter is installed outside the source.
    child=s._managed.pop(key)
    result=s.stop_session(key)
    child.wait(timeout=10)
    for _ in range(50):
        if s.listening_pid(8082) is None:
            break
        time.sleep(.1)
    assert result["stopped"] and s.listening_pid(8082) is None
    status=s.start_session(key,"observe",participant=True)
    assert status["started"]
    result=s.stop_session(key)
    assert result["stopped"] and s.listening_pid(8082) is None
    print(json.dumps({"local_proxy_started":started,"observation_records":count,"own_process_stopped":True,"restart_same_port_verified":True,
                      "restored_process_identity_verified":True,"new_group_capture_verified":False,"system_proxy_changed":False},indent=2))
finally:
    if s.state_path(p).exists():
        s.stop_session(key)
    s.profile_path(key).unlink(missing_ok=True)
