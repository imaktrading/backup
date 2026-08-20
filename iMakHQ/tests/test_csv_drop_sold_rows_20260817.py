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


# ── 入稿直前の実在庫 (監視くんCLI・2026-08-18) ────────────────────────
def test_在庫CLIの呼び先が監視くん():
    """HQ で在庫判定を作らない (二重実装 + 偽陽性の元)。"""
    import csv_drop_sold_rows as M
    assert M.STOCK_CLI_DIR.endswith("iMakInventory")
    src = open(M.__file__, encoding="utf-8").read()
    assert "tools.stock_check_cli" in src


def test_CLIが呼べない時は巡回結果に落ちる():
    """CLI が無い環境でも走行を止めない (空 dict = シートの値のまま)。"""
    import csv_drop_sold_rows as M
    assert M.live_stock([]) == {}


def test_判定不能は上書きしない():
    """unknown を sold に寄せると出せたはずの商品を捨てる (監視くんの念押し)。"""
    src = open(__import__("csv_drop_sold_rows").__file__, encoding="utf-8").read()
    i = src.index("if use_live:")
    body = src[i:src.index("keep, dropped, stale, unknown = plan(", i)]
    assert 'st == "sold"' in body and 'st == "in_stock"' in body
    assert "unknown は触らない" in body


# ── 直前の在庫確認が動かなかった時 (2026-08-20 追記) ────────────────────
#
# ★実機で確認した事実: 監視くんの在庫チェックCLI は 2件のURLに対して 240秒 かけて
#   **出力ゼロ・結果ファイル無し** で終わる (orphan Chrome を掃除しても同じ)。
#   つまり入稿直前の在庫確認は **今まったく効いていない**。
#
#   それ自体は監視くん側の修正だが、HQ 側の問題は
#   「確認できなかった時に、古い巡回結果のまま出品していた」こと。
#   確認できていない物を出して仕入れられなければキャンセル → Defect Rate。

def test_直前確認が動かず巡回も古いなら落とす():
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", "2026-08-01")])
    keep, dropped, stale, _u = plan(_csv(["PSA10-999"]), HEADER,
                                    supply_index(sheet), TODAY, live_ok=False)
    assert keep == [] and len(dropped) == 1
    assert "直前の在庫確認が動かず" in dropped[0][2]
    assert stale == []                      # 警告で済ませず、落とした


def test_直前確認が動いていれば古くても落とさない():
    """実在庫で上書きされているので、巡回の日付が古いこと自体は問題にしない."""
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", "2026-08-01")])
    keep, dropped, stale, _u = plan(_csv(["PSA10-999"]), HEADER,
                                    supply_index(sheet), TODAY, live_ok=True)
    assert len(keep) == 1 and dropped == [] and len(stale) == 1


def test_確認が動かなくても巡回が新しければ出す():
    """出品を止めないため。3日以内の巡回結果は使える."""
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "", "999", TODAY.strftime("%Y-%m-%d"))])
    keep, dropped, _s, _u = plan(_csv(["PSA10-999"]), HEADER,
                                 supply_index(sheet), TODAY, live_ok=False)
    assert len(keep) == 1 and dropped == []


def test_落とした理由が必ず付く():
    """メールの内訳が『引き算』にならないよう、落ちた行は理由付きで返す."""
    sheet = _sheet([("https://jp.mercari.com/item/m111", "", "○", "999", "2026-08-17")])
    _k, dropped, _s, _u = plan(_csv(["PSA10-999"]), HEADER, supply_index(sheet), TODAY)
    assert dropped[0][2] == "仕入元が売り切れ"
