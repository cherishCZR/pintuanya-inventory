import hashlib
import json
import re
import math
from dataclasses import asdict
from datetime import datetime, timezone
from .extract import extract
from .models import utcnow


def endpoint_rule(c, host, path, method):
    # No query strings, headers, credentials or body values in metadata.
    for r in c["capture"]["endpoint_rules"]:
        if r["host"] == host and r["path"] == path and r["method"] == method:
            return r
    raise ValueError("非白名单端点；不保存响应")


def event_from_payload(payload, m, *, mode="demo", config=None, metadata=None):
    metadata = metadata or {}
    group = "DEMO"
    rule = {"alias": "DEMO"}
    session = "DEMO"
    if mode != "demo":
        if mode != "passive" or config is None:
            raise ValueError("真实输入需要配置和普通账号采样元信息")
        rule = endpoint_rule(config, metadata.get("host"), metadata.get("path"), metadata.get("method"))
        group = str(config["target"]["resolved_group_id"])
        session = config.get("session_id")
        if not session or metadata.get("session_id") != session or metadata.get("role") != "participant":
            raise ValueError("采样会话/普通账号声明不匹配")
    elif not m.get("demo"):
        raise ValueError("demo 路线仅接受明确标注的 DEMO 映射")
    observed = metadata.get("observed_at", utcnow())
    dt = datetime.fromisoformat(observed)
    if dt.tzinfo is None:
        raise ValueError("观察时间必须包含时区")
    observed = dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    result = extract(payload, m, metadata.get("http_status", 200), None if mode == "demo" else group)
    flow_id = metadata.get("event_id")
    if mode != "demo" and not flow_id:
        raise ValueError("缺少真实采样 event_id")
    digest = hashlib.sha256(json.dumps([session, flow_id or observed], ensure_ascii=False).encode()).hexdigest()
    return {"schema_version": 2, "event_id": digest, "session_id": session,
            "target_id": "demo:DEMO" if mode == "demo" else "participant:" + group,
            "target_label": "DEMO 模拟团单" if mode == "demo" else config["target"]["label"],
            "group_id": group, "mode": mode, "role": "demo" if mode == "demo" else "participant",
            "observed_at": observed, "endpoint_alias": rule["alias"], "mapping_version": m["version"],
            **asdict(result)}


def validate_event(e, c, m):
    """Queue is a local boundary: reject unknown columns and unsanitized records."""
    expected = {"schema_version", "event_id", "session_id", "target_id", "target_label", "group_id", "mode",
                "role", "observed_at", "endpoint_alias", "mapping_version", "status", "observations",
                "error_code", "coverage", "expected_count", "candidates"}
    if set(e) != expected or e["schema_version"] != 2:
        raise ValueError("event_schema_invalid")
    if (e["mode"] != "passive" or e["role"] != "participant" or e["session_id"] != c.get("session_id")
            or e["group_id"] != str(c["target"]["resolved_group_id"])
            or e["target_id"] != "participant:" + e["group_id"]
            or e["target_label"] != c["target"]["label"] or e["mapping_version"] != m["version"]
            or e["endpoint_alias"] not in [r["alias"] for r in c["capture"]["endpoint_rules"]]):
        raise ValueError("event_source_invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", e["event_id"]):
        raise ValueError("event_id_invalid")
    dt = datetime.fromisoformat(e["observed_at"])
    if dt.tzinfo is None:
        raise ValueError("event_time_invalid")
    if e["coverage"] not in ("partial", "unknown") or e["expected_count"] is not None:
        raise ValueError("coverage_unconfirmed")
    if e["status"] not in ("exact_stock", "availability_only", "inconclusive", "failed", "access_denied"):
        raise ValueError("event_status_invalid")
    errors = {None, "authentication_required", "rate_limited", "cached_not_modified", "empty_response",
              "http_error", "unsupported_payload", "mapping_changed", "wrong_or_unconfirmed_group",
              "business_error", "no_items", "identity_unconfirmed", "duplicate_identity", "body_too_large"}
    if e["error_code"] not in errors:
        raise ValueError("event_error_invalid")
    row_keys = {"product_id", "sku_id", "synthetic_sku", "product_name", "sku_name", "stock_remaining",
                "stock_total", "sold_quantity", "purchase_limit", "availability", "quantity_status",
                "visibility_flag", "raw_display_text"}
    seen = set()
    for row in e["observations"]:
        if set(row) != row_keys or not row["product_id"] or not row["sku_id"]:
            raise ValueError("observation_invalid")
        for k in ("product_id", "sku_id", "product_name", "sku_name"):
            if not isinstance(row[k], str) or len(row[k]) > 200:
                raise ValueError("text_invalid")
        for k in ("stock_remaining", "stock_total", "sold_quantity", "purchase_limit"):
            if row[k] is not None and (type(row[k]) is not int or not 0 <= row[k] < 2**63):
                raise ValueError("quantity_invalid")
            if row[k] is not None:
                metric = m.get("metrics", {}).get(k, {})
                if not metric.get("confirmed") or not metric.get("evidence"):
                    raise ValueError("unconfirmed_metric")
        if type(row["synthetic_sku"]) is not bool or (row["visibility_flag"] is not None and type(row["visibility_flag"]) is not bool):
            raise ValueError("flag_invalid")
        if row["raw_display_text"] is not None and (not isinstance(row["raw_display_text"], str) or len(row["raw_display_text"]) > 200):
            raise ValueError("text_invalid")
        if row["availability"] not in ("in_stock", "out_of_stock", "unknown"):
            raise ValueError("availability_invalid")
        for k in ("availability", "visibility_flag", "raw_display_text"):
            if row[k] is not None and row[k] != "unknown":
                metric = m.get("metrics", {}).get(k, {})
                if not metric.get("confirmed") or not metric.get("evidence"):
                    raise ValueError("unconfirmed_metric")
        if row["quantity_status"] not in ("valid", "unconfirmed", "missing", "null", "invalid_type_or_sentinel"):
            raise ValueError("quantity_status_invalid")
        if row["quantity_status"] == "valid" and row["stock_remaining"] is None:
            raise ValueError("quantity_inconsistent")
        if row["stock_remaining"] is not None and row["quantity_status"] != "valid":
            raise ValueError("quantity_inconsistent")
        identity = (row["product_id"], row["sku_id"])
        if identity in seen:
            raise ValueError("duplicate_identity")
        seen.add(identity)
    if e["error_code"] and e["observations"]:
        raise ValueError("failed_event_contains_observations")
    if e["error_code"] and e["candidates"]:
        raise ValueError("failed_event_contains_candidates")
    for candidate in e["candidates"]:
        if set(candidate) != {"product_id", "sku_id", "field_alias", "source_path", "value", "value_type", "semantics"}:
            raise ValueError("candidate_invalid")
        if (candidate["product_id"], candidate["sku_id"]) not in seen or candidate["semantics"] != "unconfirmed":
            raise ValueError("candidate_identity_invalid")
        if candidate["field_alias"] not in m.get("candidates", {}) or not isinstance(candidate["source_path"], list):
            raise ValueError("candidate_mapping_invalid")
        if candidate["value_type"] not in ("int", "float", "bool", "str", "NoneType", "missing", "dict", "list"):
            raise ValueError("candidate_type_invalid")
        v = candidate["value"]
        if type(v) is float and not math.isfinite(v):
            raise ValueError("candidate_number_invalid")
        if v is not None and type(v) not in (int, float, bool):
            if not isinstance(v, str) or len(v) > 32 or not re.fullmatch(r"[-+]?[0-9]+(?:\.[0-9]+)?", v):
                raise ValueError("candidate_text_invalid")
        if len(candidate["source_path"]) > 64 or any(type(p) not in (str, int) or (isinstance(p,str) and len(p)>100) for p in candidate["source_path"]):
            raise ValueError("candidate_path_invalid")
        path = candidate["source_path"]
        prefix = m["items_path"]
        if path[:len(prefix)] != prefix or len(path) <= len(prefix) or type(path[len(prefix)]) is not int or path[len(prefix)] < 0:
            raise ValueError("candidate_path_invalid")
        position = len(prefix) + 1
        if m.get("sku_path") is not None:
            sku_path = m["sku_path"]
            if path[position:position+len(sku_path)] != sku_path:
                raise ValueError("candidate_path_invalid")
            position += len(sku_path)
            if len(path) <= position or type(path[position]) is not int or path[position] < 0:
                raise ValueError("candidate_path_invalid")
            position += 1
        if path[position:] != m["candidates"][candidate["field_alias"]]["path"]:
            raise ValueError("candidate_path_invalid")
    derived = "exact_stock" if any(r["stock_remaining"] is not None for r in e["observations"]) else (
        "availability_only" if any(r["availability"] != "unknown" for r in e["observations"]) else "inconclusive")
    if e["observations"] and e["status"] != derived:
        raise ValueError("status_inconsistent")
    if not e["observations"] and e["status"] in ("exact_stock", "availability_only"):
        raise ValueError("empty_evidence")
    return e
