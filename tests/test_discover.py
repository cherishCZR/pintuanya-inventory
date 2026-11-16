import json
from pintuanya_inventory.discover import discover


def test_candidates_redaction():
    result = discover({"stock":7,"remaining":"secret-token", "user":{"stock":99},
                       "order":{"quantity":33},"phone":"123456", "token":"credential"})
    text = json.dumps(result)
    assert "secret-token" not in text and "credential" not in text and "123456" not in text
    assert len(result["candidates"]) == 2
    assert all(c["semantics"] == "unconfirmed" for c in result["candidates"])
