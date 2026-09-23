"""くじ再仕入れ・取下再出品②: 押し直しで確定分が消えたり、同じ出品を二重に作ったりしない (2026-09-24)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import ichibankuji_restock as K                                # noqa: E402
import relist_add_from_pending as RA                           # noqa: E402


def test_confirmed_is_merged_then_consumed(tmp_path, monkeypatch):
    f = str(tmp_path / "c.json")
    monkeypatch.setattr(K, "CONFIRMED_FILE", f)
    K._save_confirmed({5: {"item_id": "A"}})
    K._save_confirmed({7: {"item_id": "B"}})          # 2回目の ① で1回目が消えない
    assert set(K._load_confirmed()) == {5, 7}
    assert K._consume_confirmed(["A"]) == 1            # ② で CSV にした分だけ外れる
    assert set(K._load_confirmed()) == {7}
    assert json.load(open(f, encoding="utf-8"))["items"]["7"]["item_id"] == "B"


def test_refresh_write_consumes_after_output():
    s = open(os.path.join(HERE, "..", "tools", "ichibankuji_restock.py"), encoding="utf-8").read()
    body = s[s.index("def refresh_write"):]
    assert body.index("CSV 出力:") < body.index("_consume_confirmed(")


def test_relist_step2_stops_when_add_csv_already_in_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "REVISE_DIR", str(tmp_path))
    up = tmp_path / "UP_20260924_0800"
    up.mkdir()
    assert RA.existing_add_csvs() == []
    (up / "tcg_upload_20260924.csv").write_text("x", encoding="utf-8")
    assert RA.existing_add_csvs() == ["tcg_upload_20260924.csv"]
