import csv
from pintuanya_inventory.export import export_csv


def test_bom_formula_and_unknown(tmp_path):
    path = tmp_path/"中文.csv"
    export_csv([{"product_name":" =HYPERLINK(\"bad\")","stock_remaining":None},
                {"product_name":"@x","stock_remaining":0}],path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert rows[0]["product_name"].startswith("'")
    assert rows[0]["stock_remaining"] == ""
    assert rows[1]["stock_remaining"] == "0"
