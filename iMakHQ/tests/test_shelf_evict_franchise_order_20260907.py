"""②(在庫あり・30日超) は 売れない作品から落とす (2026-09-07 ユーザー確定).

根拠 (実測 8/07〜9/05 の注文 と live 出品数):
  ポケモン 273→17 (6.2%) / G-SHOCK 217→3 (1.4%) / ワンピース 211→2 (0.9%) /
  ガンダム 15→0 / ドラゴンボール 10→0
**ポケモンは最後まで残す**。逆順にすると一番売れている作品から捨てることになる。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import shelf_evict as se  # noqa: E402


def test_order_is_gundam_db_first_pokemon_last():
    r = se.franchise_rank
    assert r("PSA 10 Gundam CCG Dual Impact #GD02-070") == 0
    assert r("PSA 10 Dragon Ball Fusion World #FB01-001") == 0
    assert r("PSA 10 One Piece Japanese OP07-118") == 1
    assert r("CASIO G-Shock GST-W110MS-1A Mens Watch") == 2
    assert r("PSA 10 Pokemon Japanese SV5a #067/066") == 3
    # ガンダム/DB < ワンピ < G-SHOCK < ポケモン
    assert r("Gundam") < r("One Piece") < r("G-Shock") < r("Pokemon")


def test_unknown_title_is_middle_not_extreme():
    """判定できないものを 0 にすると真っ先に落ちる。真ん中に置く."""
    assert se.franchise_rank("Weiss Schwarz NIKKE Ludmilla") == se.FRANCHISE_OTHER
    assert se.franchise_rank("") == se.FRANCHISE_OTHER
    assert 0 < se.FRANCHISE_OTHER < 3


def test_pick_drops_gundam_before_pokemon():
    """同じウォッチ/表示なら、ポケモンより先にガンダムが選ばれること."""
    rows = [
        {"item_id": "1", "title": "PSA 10 Pokemon Japanese SV5a", "qty": 1,
         "watch": 0, "impr_total": 10, "age_days": 60, "sold_qty": 0, "sales90": 0,
         "price": 100},
        {"item_id": "2", "title": "PSA 10 Gundam CCG Beta", "qty": 1,
         "watch": 0, "impr_total": 10, "age_days": 60, "sold_qty": 0, "sales90": 0,
         "price": 100},
    ]
    picked, _ = se.pick(rows, target=100, shelf_of=lambda r: float(r["price"]),
                        cat_of=lambda r: "TCG", only_tier=se.TIER_STALE)
    assert [r["item_id"] for _t, r in picked] == ["2"]
