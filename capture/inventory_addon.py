"""Passive, standard-library-only addon. No requests, mutation or HTTPFlow dumps."""
import codecs
import json
from pathlib import Path
import sys
import zlib
from urllib.parse import urlsplit, parse_qs

from mitmproxy import ctx, exceptions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pintuanya_inventory.config import load_config, resolve, validate_capture
from pintuanya_inventory.models import utcnow
from pintuanya_inventory.pipeline import endpoint_rule, event_from_payload


def bounded_decode(raw, encoding, limit):
    if encoding in ("", "identity"):
        if len(raw) > limit:
            raise OverflowError
        return raw
    if encoding == "br":
        # Brotli is a dependency of mitmproxy. Require its bounded-output API;
        # never fall back to unbounded decompress on older installations.
        try:
            import brotli
            decoder = brotli.Decompressor()
            result = decoder.process(raw, output_buffer_limit=limit + 1)
            while not decoder.can_accept_more_data():
                if len(result) > limit:
                    raise OverflowError
                chunk = decoder.process(b"", output_buffer_limit=limit + 1 - len(result))
                result += chunk
                if not chunk and not decoder.can_accept_more_data():
                    raise ValueError("unsupported_payload")
            if len(result) > limit:
                raise OverflowError
            if not decoder.is_finished():
                raise ValueError("unsupported_payload")
            return result
        except (ImportError, AttributeError, TypeError):
            raise ValueError("unsupported_payload") from None
        except Exception as exc:
            if isinstance(exc, (OverflowError, ValueError)):
                raise
            raise ValueError("unsupported_payload") from None
    if encoding not in ("gzip", "deflate"):
        raise ValueError("unsupported_payload")
    decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
    decoded = decoder.decompress(raw, limit + 1)
    if len(decoded) > limit or decoder.unconsumed_tail:
        raise OverflowError
    decoded += decoder.flush(limit + 1 - len(decoded))
    if len(decoded) > limit:
        raise OverflowError
    if not decoder.eof or decoder.unused_data:
        raise ValueError("unsupported_payload")
    return decoded


class InventoryAddon:
    def load(self, loader):
        loader.add_option("inventory_config", str, "", "Absolute path to confirmed participant configuration")

    def configure(self, updated):
        if "inventory_config" not in updated:
            return
        path = ctx.options.inventory_config
        if not path or not Path(path).is_absolute():
            raise exceptions.OptionsError("inventory_config must be an absolute path")
        try:
            self.config = load_config(path)
            self.mapping = validate_capture(self.config)
            self.participant_role_confirmed = False
            self.queue = resolve(self.config, "queue_file", "../data/events.jsonl")
            self.queue.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            raise exceptions.OptionsError("Participant host/endpoint/group/mapping evidence is not configured") from None

    def response(self, flow):
        if not hasattr(self, "config") or flow.response is None:
            return
        request, response = flow.request, flow.response
        path = request.path.split("?", 1)[0]
        capture=self.config["capture"]
        if capture.get("require_participant_role") and request.host in capture["allowed_hosts"]:
            if request.method=="GET" and path==capture.get("role_check_path"):
                group=parse_qs(urlsplit(request.path).query).get("groupon_uuid",[None])[0]
                if group!=str(self.config["target"]["resolved_group_id"]):
                    return
                ordinary=False
                try:
                    raw=response.raw_content or b""
                    if len(raw)>2097152:
                        raise ValueError
                    payload=json.loads(bounded_decode(raw,response.headers.get("content-encoding","").lower(),2097152))
                    admin=payload["data"]["admin"]
                    ordinary=(response.status_code==200 and type(payload.get("code")) is int and payload["code"]==0
                              and isinstance(admin,dict) and "admin_id" in admin and "seller_id" in admin
                              and not admin["admin_id"] and not admin["seller_id"]
                              and all(type(admin.get(k)) is int and admin[k]==0
                                      for k in ("can_modify_groupon","can_modify_member","can_modify_membership")))
                except (ValueError,KeyError,TypeError,OverflowError,zlib.error):
                    ordinary=False
                self.participant_role_confirmed=ordinary
                if capture.get("role_state_file"):
                    try:
                        Path(capture["role_state_file"]).write_text(json.dumps({"ordinary_role_confirmed":ordinary,"observed_at":utcnow()}),encoding="utf-8")
                    except OSError:
                        ctx.log.warn("inventory: role status write failed; no account data logged")
                return
        try:
            endpoint_rule(self.config, request.host, path, request.method)
        except ValueError:
            return
        if capture.get("require_participant_role") and not getattr(self,"participant_role_confirmed",False):
            return
        # Cookies/headers/query/body never enter the persisted event.
        meta = {"event_id": flow.id, "session_id": self.config["session_id"], "role": "participant",
                "host": request.host, "path": path, "method": request.method,
                "observed_at": utcnow(), "http_status": response.status_code}
        limit = min(int(self.config["capture"].get("max_decoded_body_bytes", 2097152)), 2097152)
        payload = None
        error = None
        try:
            raw = response.raw_content or b""
            if len(raw) > limit:
                raise OverflowError
            if "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("unsupported_payload")
            decoded = bounded_decode(raw, response.headers.get("content-encoding", "").lower(), limit)
            payload = json.loads(decoded)
        except OverflowError:
            error = "body_too_large"
        except (ValueError, UnicodeError, zlib.error):
            error = "unsupported_payload" if response.raw_content else "empty_response"
        try:
            event = event_from_payload(payload, self.mapping, mode="passive", config=self.config, metadata=meta)
            # A successfully decoded body must correlate to the target group. Drop mismatches.
            if event["error_code"] == "wrong_or_unconfirmed_group":
                return
            if error and event["error_code"] not in ("authentication_required", "http_error", "rate_limited", "cached_not_modified", "empty_response"):
                event.update(status="inconclusive", observations=[], candidates=[], error_code=error)
            # Undecodable/error bodies are endpoint-scoped diagnostics, never inventory evidence.
            with self.queue.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except (OSError, ValueError, KeyError, TypeError):
            ctx.log.warn("inventory: local extraction/write failed; no response content logged")


addons = [InventoryAddon()]
