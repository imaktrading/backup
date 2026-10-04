"""棚② PSA の新しい表 + 市場の門 (2026-10-04 ユーザー確定)。表の正本は管理表タブ「棚②の新ルール案 (HQ)」。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import shelf_psa_rules as R  # noqa: E402
import shelf_evict as S  # noqa: E402
import psa_hoju_fill as H  # noqa: E402

UP, DOWN = [10, 5, 0, 3], [-60, -70, -55, 10]


def test_table_rows():
    t = R.table_verdict
    assert t(40, True, True, False, 50, None) == (R.DROP, "①③ 値下げ済・ウォッチ無")
    assert t(40, True, False, False, 50, None)[0] == R.HOJU          # ②④ まだ下げていない
    assert t(40, True, True, True, 50, None)[0] == R.HOJU            # ⑤ ウォッチあり
    assert t(70, True, True, False, 50, None)[1].startswith("⑦⑧")
    assert t(70, True, False, False, 50, None)[1].startswith("⑩ ")
    assert t(70, True, True, True, 50, None) == (R.HOJU, "⑨ 補優先")
    assert t(70, True, False, True, 50, None) == (R.HOJU, "⑩b 補優先")
    assert t(95, True, False, True, 50, None) == (R.DROP, "⑪ 90日")
    assert t(40, False, False, False, 3, None)[1].startswith("⑫")
    assert t(40, False, False, False, 6, None)[0] == R.HOJU          # ⑬ 見られた
    assert t(40, False, False, False, None, None)[0] == R.KEEP       # 閲覧不明は落とさない
    assert t(65, False, False, True, 99, None)[1].startswith("⑭")
    assert t(95, True, True, False, 0, UP) == (R.KEEP, "0b 伸びている")
    assert t(95, False, False, False, 0, DOWN) == (R.DROP, "11b 埋もれた")
    assert t(60, True, False, True, 0, DOWN)[0] == R.HOJU            # 伸び/埋もれは90日以上だけ


def test_market_gate():
    m = R.market_verdict
    assert m(95, 100, (0, None)) == (R.DROP, "M0 90日・ケツ")     # 90日を過ぎたら市場に関係なく
    assert m(40, 100, None)[0] == R.KEEP                          # 取れない = 落とさない
    assert m(40, 100, (0, None))[1].startswith("M1")
    assert m(40, 100, (9, 50.0))[1].startswith("M2")              # 10件未満 = 少ない
    assert m(40, 121, (10, 100.0))[1].startswith("M3")            # 1.2倍超 = 高い
    assert m(40, 120, (10, 100.0))[1].startswith("M4")


def test_same_listing_counts_only_japanese_same_print():
    ours = "PSA 10 Pokemon Japanese Sv8a: Terastal Fest Ex #092/187 Umbreon 2024"
    ok = R.same_listing
    assert ok(ours, "PSA 10 Umbreon 092/187 Terastal Festival Japanese", "092/187")
    assert not ok(ours, "Umbreon 092/187 Master Ball Reverse Holo Japanese PSA 10", "092/187")
    assert not ok(ours, "PSA 10 Umbreon 092/187 Terastal Festival", "092/187")      # 言語が書いていない
    assert not ok(ours, "PSA 9 Umbreon 092/187 Japanese", "092/187")
    n, med = R.market_stats(ours, "1", [
        {"itemId": "v1|2|0", "title": "PSA 10 Umbreon 092/187 Japanese", "price": {"value": "100"}},
        {"itemId": "v1|1|0", "title": "PSA 10 Umbreon 092/187 Japanese", "price": {"value": "999"}},  # 自分
        {"itemId": "v1|3|0", "title": "PSA 10 Umbreon 092/187 JP SV8a", "price": {"value": "200"}}])
    assert (n, med) == (2, 150.0)


def test_judge_skips_market_after_cap_and_without_api():
    row = {"item_id": "9", "title": "PSA 10 X #001/100 Pika", "age_days": 95, "price": 50, "watch": 0}

    class Boom:
        def stat(self, *a):
            raise AssertionError("90日以上は市場を引かない")
    assert R.judge(row, True, True, {}, Boom())["code"] == "M0 90日・ケツ"
    row["age_days"] = 40
    d = R.judge(row, True, True, {}, None)
    assert d["verdict"] == R.KEEP                                  # 市場を見ていない = 落とさない


def test_pick_uses_psa_judge_only_for_tcg():
    rows = [{"item_id": "P1", "qty": 1, "age_days": 40, "title": "a", "price": 10},
            {"item_id": "P2", "qty": 1, "age_days": 40, "title": "b", "price": 10},
            {"item_id": "G1", "qty": 1, "age_days": 40, "title": "c", "price": 10}]
    cat = {"P1": "TCG", "P2": "TCG", "G1": "G-shock"}
    judge = lambda r: {"item_id": r["item_id"], "verdict": "取下げ" if r["item_id"] == "P1" else "補優先"}
    dec = []
    picked, _ = S.pick(rows, float("inf"), lambda r: 10.0, lambda r: cat[r["item_id"]],
                       price_downs={"G1": (100.0, 10.0)}, psa_judge=judge, decisions=dec)
    assert [r["item_id"] for _t, r in picked] == ["P1", "G1"]      # G-SHOCK は今までどおり値下げ済みで落とす
    assert [d["item_id"] for d in dec] == ["P1", "P2"]


def test_hoju_priority_goes_first_and_is_searched_even_when_full():
    t = [{"itemID": "a"}, {"itemID": "b"}, {"itemID": "c"}]
    assert [x["itemID"] for x in H.put_priority_first(t, ["c"])] == ["c", "a", "b"]
    hdr = [""] * 40
    full = [""] * 40
    full[H.B], full[H.CERT], full[H.CATEGORY], full[H.KEY] = "X1", "12345678", "TCG", "k"
    for k in range(H.AUXN):
        full[H.AUX0 + k] = f"https://jp.mercari.com/item/m{k}"
    vals = [hdr, full]
    assert H.select_backfill_targets(vals, max_backups=5) == []           # 補5本 = 夜の検索の対象外
    got = H.add_shelf_priority_targets([], vals, ["X1"])
    assert [x["itemID"] for x in got] == ["X1"]                           # 補優先なら探す


def test_priority_files_roundtrip(tmp_path):
    p = str(tmp_path / "prio.json")
    R.write_hoju_priority([{"item_id": "1", "verdict": R.HOJU}, {"item_id": "2", "verdict": R.DROP}], p)
    assert R.load_hoju_priority(p) == ["1"]
    assert R.load_hoju_priority(str(tmp_path / "none.json")) == []
