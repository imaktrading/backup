# -*- coding: utf-8 -*-
"""入稿CSVから売り切れ行を落とす処理の回帰テスト (2026-08-17)。

売り切れた現物を出すと仕入れられず、キャンセル → Defect Rate → BAN リスク。
「落とす」判断は必ず**シートの売り切れ欄 (監視くんの巡回結果)**が根拠で、
照合できない行は落とさない (= 判定不能を破壊的動作に倒さない)。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from csv_drop_sold_rows import (cert_from_label, supply_index, _is_stale,  # noqa: E402
                               plan, STALE_DAYS)

TODAY = datetime.date(2026, 8, 17)
HEADER = ["*Action", "CustomLabel", "*Title"]


def _sheet(rows):
    """rows = [(url, itemid, sold, cert, checked)] → シート2次元配列。"""
    out = [["URL", "itemID", "タイトル", "売り切れ", "状態", "F", "G", "H", "cert",
            "J", "K", "L", "M", "N", "巡回時刻"]]
    for url, itemid, sold, cert, checked in rows:
        r = [""] * 15
        r[0], r[1], r[3], r[8], r[14] = url, itemid, sold, cert, checked
        out.append(r)
    return out


def _csv(labels):
    return [["Add", lb, "title"] for lb in labels]


def test_cert_from_label():
    assert cert_from_label("PSA10-153025508") == "153025508"
    assert cert_from_label("m21409027696") is None
    assert cert_from_label("") is None


def test_索引はcertとURL末尾の両方で引ける():
    idx = supply_index(_sheet([("https://jp.mercari.com/item/m111", "", "", "999", "2026-08-17")]))
    assert idx["999"]["url"].endswith("m111")
    assert idx["m111"]["row"] == 2


def test_shops_のURLも引ける():
    idx = supply_index(_sheet([("https://jp.mercari.com/shops/product/2JU9", "", "", "", "2026-08-17")]))
    assert "2JU9" in idx


def test_売り切れ行は落ちる():
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "○", "999", "2026-08-17")])
    keep, dropped, stale, unknown = plan(_csv(["PSA10-999"]), HEADER, supply_index(sheet), TODAY)
    assert keep == [] and len(dropped) == 1 and dropped[0][0] == "PSA10-999"


def test_売り切れていない行は残る():
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", "2026-08-17")])
    keep, dropped, stale, unknown = plan(_csv(["PSA10-999"]), HEADER, supply_index(sheet), TODAY)
    assert len(keep) == 1 and dropped == [] and stale == [] and unknown == []


def test_メルカリSKUのラベルでも照合できる():
    sheet = _sheet([("https://jp.mercari.com/item/m21409027696", "", "○", "", "2026-08-17")])
    keep, dropped, _s, _u = plan(_csv(["m21409027696"]), HEADER, supply_index(sheet), TODAY)
    assert keep == [] and len(dropped) == 1


def test_シートに無い行は落とさない_fail_openを明示する():
    """照合できないことを理由に出品を捨てない (機会損失を黙って作らない)。"""
    keep, dropped, _s, unknown = plan(_csv(["PSA10-404"]), HEADER, supply_index(_sheet([])), TODAY)
    assert len(keep) == 1 and dropped == [] and unknown == ["PSA10-404"]


def test_巡回が古い行は残すが警告に出る():
    old = (TODAY - datetime.timedelta(days=STALE_DAYS + 1)).strftime("%Y-%m-%d")
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", old)])
    keep, dropped, stale, _u = plan(_csv(["PSA10-999"]), HEADER, supply_index(sheet), TODAY)
    assert len(keep) == 1 and dropped == [] and len(stale) == 1


def test_巡回時刻が空でも落とさない_古い扱いにするだけ():
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", "")])
    keep, dropped, stale, _u = plan(_csv(["PSA10-999"]), HEADER, supply_index(sheet), TODAY)
    assert len(keep) == 1 and dropped == [] and len(stale) == 1


def test_stale判定の境界():
    assert _is_stale("2026-08-14", TODAY) is False        # ちょうど3日前 = まだ有効
    assert _is_stale("2026-08-13", TODAY) is True         # 4日前 = 古い
    assert _is_stale("", TODAY) is True
    assert _is_stale("2026/08/17 05:00", TODAY) is False  # スラッシュ表記も読む


def test_CustomLabel列が無いCSVは素通しする():
    keep, dropped, _s, _u = plan([["Add", "x"]], ["*Action", "*Title"], {}, TODAY)
    assert len(keep) == 1 and dropped == []


def test_出品くんのチェーンに組み込まれている():
    """手でやっていた入稿前チェックなので、走行に載っていないと意味が無い。"""
    cp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_panel.py")
    src = open(cp, encoding="utf-8").read()
    assert "csv_drop_sold_rows.py" in src
    # CSV を変える最後の step であること (この後に CSV を書き換える step を足すと、
    # 監査くんが見る CSV と落とした結果がズレる)
    assert src.index("csv_drop_sold_rows.py") > src.index("hoju_url_from_dupes.py")
