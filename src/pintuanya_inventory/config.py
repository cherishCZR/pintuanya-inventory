import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_json(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return json.load(f)


def load_config(path):
    path = Path(path).resolve()
    c = load_json(path)
    c["_base"] = str(path.parent)
    c["_path"] = str(path)
    return c


def resolve(c, key, default):
    value = Path(c.get(key) or default)
    return value if value.is_absolute() else Path(c.get("_base", ROOT)) / value


def validate_capture(c):
    if not c.get("capture", {}).get("enabled"):
        raise ValueError("采集未启用：尚未确认主机/端点/字段，普通账号验证尚未完成")
    if c.get("role") != "participant" or not c.get("role_evidence", {}).get("confirmed"):
        raise ValueError("需要普通参团账号角色确认记录（角色声明本身不能证明权限）")
    if not c.get("target", {}).get("resolved_group_id") or not c.get("target", {}).get("association_evidence"):
        raise ValueError("尚未确认团单标识及关联依据；分享短码不能充当团单 ID")
    capture = c["capture"]
    hosts = capture.get("allowed_hosts", [])
    rules = capture.get("endpoint_rules", [])
    if not hosts or not rules:
        raise ValueError("尚未确认主机/端点/字段")
    for host in hosts:
        if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", host) or ".." in host:
            raise ValueError("主机必须是已确认的完整域名或 IP，不接受 URL/通配符")
    aliases = set()
    for rule in rules:
        alias = rule.get("alias", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias) or alias in aliases:
            raise ValueError("端点别名无效或重复")
        aliases.add(alias)
        if rule.get("host") not in hosts or not rule.get("readonly_confirmed") or not rule.get("evidence"):
            raise ValueError("端点必须在白名单内且有只读语义确认依据")
        if not str(rule.get("path", "")).startswith("/") or "?" in rule["path"] or "#" in rule["path"]:
            raise ValueError("端点 path 只接受已确认的精确路径，不含查询串")
        if rule.get("method") not in ("GET", "POST"):
            raise ValueError("只支持已确认的 GET/POST 查询")
    mapping = load_json(resolve(c, "mapping_file", ""))
    if mapping.get("demo") or not mapping.get("source_confirmed") or not mapping.get("group_path"):
        raise ValueError("正式采集需要依据普通账号响应建立的映射及团单响应关联路径")
    from .extract import validate_mapping
    validate_mapping(mapping)
    if not c.get("session_id") or not c["role_evidence"].get("method") or not c["role_evidence"].get("observed_at"):
        raise ValueError("需要采样会话 ID、角色验证方法和时间")
    return mapping
