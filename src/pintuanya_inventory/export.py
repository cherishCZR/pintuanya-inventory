import csv
import json
from pathlib import Path

FIELDS = ["mode", "target_id", "product_id", "sku_id", "synthetic_sku", "product_name", "sku_name",
          "stock_remaining", "stock_total", "sold_quantity", "purchase_limit", "quantity_status",
          "availability", "inventory_change", "observed_at", "latest_attempt_at", "last_success_at",
          "latest_attempt_status", "latest_error", "stale", "coverage", "endpoint_alias", "mapping_version"]


def safe_text(v):
    if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + v
    if isinstance(v, str) and v.startswith(("\t", "\r", "\n")):
        return "'" + v
    return v


def export_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: safe_text(v) for k, v in row.items()} for row in rows)


def export_candidates(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["mode", "target_id", "product_id", "sku_id", "product_name", "sku_name", "field_alias", "value",
              "value_type", "semantics", "source_path", "observed_at", "latest_attempt_at", "latest_error", "stale", "endpoint_alias", "mapping_version"]
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row = {**row, "source_path":json.dumps(row["source_path"],ensure_ascii=False)}
            writer.writerow({k:safe_text(v) for k,v in row.items()})
