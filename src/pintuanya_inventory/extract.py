"""Explicit JSON mapping. Candidate names never establish inventory semantics."""
import re
import math
from .models import MISSING, Result, path_get


def quantity(value):
    if value is MISSING:
        return None, "missing"
    if value is None:
        return None, "null"
    if type(value) is int and 0 <= value < 2**63:
        return value, "valid"
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) and len(value) < 19:
        number = int(value)
        return (number, "valid") if number < 2**63 else (None, "invalid_type_or_sentinel")
    return None, "invalid_type_or_sentinel"


def stable_id(value):
    return str(value) if (type(value) is int or isinstance(value, str)) and str(value) else None


def validate_mapping(m):
    if not m.get("version") or not isinstance(m.get("items_path"), list):
        raise ValueError("映射需要 version/items_path")
    if not m.get("success") or not isinstance(m["success"].get("path"), list):
        raise ValueError("必须显式配置业务成功条件")
    if not isinstance(m.get("fields", {}).get("product_id"), list):
        raise ValueError("必须配置可靠商品 ID 路径")
    if m.get("sku_path") is not None and not isinstance(m.get("sku_fields", {}).get("sku_id"), list):
        raise ValueError("多规格映射需要 SKU ID")
    if m.get("group_scope", "response") not in ("response", "item"):
        raise ValueError("团单关联范围只能为 response/item")
    for alias, spec in m.get("candidates", {}).items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", alias) or not isinstance(spec.get("path"), list):
            raise ValueError("候选映射需要固定别名和显式路径")
    for name, spec in m.get("metrics", {}).items():
        if not isinstance(spec.get("path"), list):
            raise ValueError("指标映射需要显式路径")
        if name == "stock_remaining" and not m.get("demo") and spec.get("missing_behavior") not in ("unknown", "mapping_changed"):
            raise ValueError("真实数量映射必须配置缺失字段语义 unknown/mapping_changed")


def extract(payload, m, http_status=200, expected_group=None):
    validate_mapping(m)
    if http_status in (401, 403):
        return Result("access_denied", error_code="authentication_required")
    if http_status == 429:
        return Result("failed", error_code="rate_limited")
    if http_status == 304:
        return Result("inconclusive", error_code="cached_not_modified")
    if http_status == 204:
        return Result("inconclusive", error_code="empty_response")
    if not 200 <= http_status < 300:
        return Result("failed", error_code="http_error")
    if not isinstance(payload, (dict, list)):
        return Result("inconclusive", error_code="unsupported_payload")
    success = m["success"]
    business = path_get(payload, success["path"])
    if business is MISSING:
        return Result("inconclusive", error_code="mapping_changed")
    if type(business) is not type(success["equals"]) or business != success["equals"]:
        login = m.get("login_failure_values", [])
        return Result("access_denied" if business in login else "failed", error_code="business_error")
    if expected_group is not None and m.get("group_scope", "response") == "response":
        actual = path_get(payload, m.get("group_path"))
        if stable_id(actual) != str(expected_group):
            return Result("inconclusive", error_code="wrong_or_unconfirmed_group")
    items = path_get(payload, m["items_path"])
    if not isinstance(items, list):
        return Result("inconclusive", error_code="mapping_changed")
    observations = []
    candidates = []
    identities = set()
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            return Result("inconclusive", error_code="mapping_changed")
        if expected_group is not None and m.get("group_scope") == "item":
            if stable_id(path_get(item, m.get("group_path"))) != str(expected_group):
                return Result("inconclusive", error_code="wrong_or_unconfirmed_group")
        fields = m["fields"]
        pid = stable_id(path_get(item, fields["product_id"]))
        if pid is None:
            return Result("inconclusive", error_code="identity_unconfirmed")
        skus = path_get(item, m["sku_path"]) if m.get("sku_path") is not None else [item]
        if not isinstance(skus, list) or not skus:
            return Result("inconclusive", error_code="mapping_changed")
        for sku_index, sku in enumerate(skus):
            sf = m.get("sku_fields", {}) if m.get("sku_path") is not None else fields
            synthetic = m.get("sku_path") is None
            sid = "__single__" if synthetic else stable_id(path_get(sku, sf.get("sku_id")))
            if sid is None:
                return Result("inconclusive", error_code="identity_unconfirmed")
            if (pid, sid) in identities:
                return Result("inconclusive", error_code="duplicate_identity")
            identities.add((pid, sid))
            row = {"product_id": pid, "sku_id": sid, "synthetic_sku": synthetic,
                   "product_name": str(path_get(item, fields.get("product_name"), ""))[:200],
                   "sku_name": str(path_get(sku, sf.get("sku_name"), ""))[:200],
                   "stock_remaining": None, "stock_total": None, "sold_quantity": None,
                   "purchase_limit": None, "availability": "unknown", "quantity_status": "unconfirmed",
                   "visibility_flag": None, "raw_display_text": None}
            for name in ("stock_remaining", "stock_total", "sold_quantity", "purchase_limit"):
                spec = m.get("metrics", {}).get(name)
                if spec:
                    if spec.get("confirmed") and spec.get("evidence"):
                        value, state = quantity(path_get(sku, spec["path"]))
                        if state == "missing" and spec.get("missing_behavior") == "mapping_changed":
                            return Result("inconclusive", error_code="mapping_changed")
                        row[name] = value
                        if name == "stock_remaining":
                            row["quantity_status"] = state
            spec = m.get("metrics", {}).get("availability")
            if spec and spec.get("confirmed") and spec.get("evidence"):
                value = path_get(sku, spec["path"])
                for pair in spec.get("values", []):
                    if type(value) is type(pair["raw"]) and value == pair["raw"]:
                        if pair["normalized"] in ("in_stock", "out_of_stock", "unknown"):
                            row["availability"] = pair["normalized"]
            for name in ("visibility_flag", "raw_display_text"):
                spec = m.get("metrics", {}).get(name)
                if spec and spec.get("confirmed") and spec.get("evidence"):
                    value = path_get(sku, spec["path"], None)
                    if name == "visibility_flag" and type(value) is bool:
                        row[name] = value
                    elif name == "raw_display_text" and isinstance(value, str):
                        row[name] = value[:200]
            observations.append(row)
            for alias, spec in m.get("candidates", {}).items():
                value = path_get(sku, spec["path"])
                value_type = "missing" if value is MISSING else type(value).__name__
                safe = value is None or type(value) in (int, bool) or (type(value) is float and math.isfinite(value))
                safe = safe or (isinstance(value, str) and len(value) <= 32 and re.fullmatch(r"[-+]?[0-9]+(?:\.[0-9]+)?", value))
                prefix = m["items_path"] + [item_index]
                if not synthetic:
                    prefix += m["sku_path"] + [sku_index]
                candidates.append({"product_id": pid, "sku_id": sid, "field_alias": alias,
                                   "source_path": prefix + spec["path"], "value": value if safe else None,
                                   "value_type": value_type, "semantics": "unconfirmed"})
    if not observations:
        return Result("inconclusive", error_code="no_items")
    if any(r["stock_remaining"] is not None for r in observations):
        status = "exact_stock"
    elif any(r["availability"] != "unknown" for r in observations):
        status = "availability_only"
    else:
        status = "inconclusive"
    return Result(status, observations, coverage="partial", candidates=candidates)
