"""Diagnostics deliberately output no arbitrary string values or sibling context."""
import hashlib
import re

WORDS = re.compile(r"stock|inventory|remain|left|available|availability|quantity|sale|sold|limit|库存|剩余|可售|销量|限购", re.I)
SENSITIVE = re.compile(r"token|secret|sign|auth|cookie|openid|unionid|session|phone|mobile|address|order|user|buyer|customer|密码|手机|地址|订单|用户", re.I)


def safe_key(key):
    if re.fullmatch(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{0,63}", key):
        return key
    return "[key:" + hashlib.sha256(key.encode()).hexdigest()[:8] + "]"


def discover(payload):
    found = []

    def walk(value, path, depth):
        if depth > 30 or len(found) >= 500:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if SENSITIVE.search(key):
                    continue
                p = path + [safe_key(key)]
                if WORDS.search(key) and not isinstance(child, (dict, list)):
                    shown = child if child is None or type(child) in (int, float, bool) else "[string redacted]"
                    found.append({"path": p, "type": type(child).__name__, "candidate_value": shown,
                                  "semantics": "unconfirmed"})
                walk(child, p, depth + 1)
        elif isinstance(value, list):
            for i, child in enumerate(value[:1000]):
                walk(child, path + [i], depth + 1)
    walk(payload, [], 0)
    return {"kind": "candidates_only", "source": "unverified", "candidates": found,
            "note": "候选不是库存结论；字符串及敏感上下文已隐藏；扫描有深度/数量上限"}
