"""補URL の1点もの共有を防ぐ (2026-10-06 ADV 依頼・ユーザー「目視に間違う可能性を出す作りが悪いなら直せよ」)。

実害: ゾロ OP06-118 の _p / _p1 の2出品が、スニダンの同じ個体 2本を補に持っていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import sheet_io as S  # noqa: E402
import psa_hoju_fill as H  # noqa: E402
import shared_supply_cleanup as C  # noqa: E402

SN1 = "https://snkrdunk.com/apparels/159663/used/50819943"
SN2 = "https://snkrdunk.com/apparels/159663/used/50823486"
SHOP = "https://jp.mercari.com/shops/product/abc"
AUX0 = S.PRODUCT_COL_AUX_START


def _row(a, aux=()):
    r = [""] * 40
    r[0] = a
    for i, u in enumerate(aux):
        r[AUX0 + i] = u
    return r


def test_append_strips_claimed_aux_and_keeps_row():
    keep, dropped = S.drop_claimed_supply([_row("https://jp.mercari.com/item/m1", [SN1, SN2])], {SN1})
    assert len(keep) == 1
    assert keep[0][AUX0] == SN2 and keep[0][AUX0 + 1] == ""          # 押さえられた SN1 を外して前に詰める
    assert [u for u, _w in dropped] == [SN1]


def test_append_same_aux_in_two_new_rows_only_first_keeps():
    keep, _d = S.drop_claimed_supply([_row("https://jp.mercari.com/item/m1", [SN1]),
                                      _row("https://jp.mercari.com/item/m2", [SN1])], set())
    assert keep[0][AUX0] == SN1 and keep[1][AUX0] == ""


def test_non_one_of_a_kind_aux_is_kept():
    keep, _d = S.drop_claimed_supply([_row("https://jp.mercari.com/item/m1", [SHOP])], {SHOP})
    assert keep[0][AUX0] == SHOP


def test_cleanup_plan_splits_live_pair_alternately():
    own = {SN1: [(3858, AUX0 + 2, "820153394178"), (3859, AUX0 + 1, "820185511455")],
           SN2: [(3858, AUX0 + 3, "820153394178"), (3859, AUX0 + 2, "820185511455")]}
    rm = C.plan(own)
    kept_rows = {}
    for u, hs in own.items():
        left = [n for n, c, _i in hs if (n, c, u) not in rm]
        assert len(left) == 1
        kept_rows[u] = left[0]
    assert set(kept_rows.values()) == {3858, 3859}                    # 両方に1本ずつ残る


def test_cleanup_plan_keeps_dupe_record_in_a_column():
    """重複くんが止めている2枚目の行の A列 + 出品中の補 = 作りどおり。消さない。"""
    own = {SN1: [(2614, 0, ""), (320, AUX0, "358524282718")]}
    assert C.plan(own) == []


def test_current_supply_lists_prices():
    r = _row("https://jp.mercari.com/item/m1", [SN1])
    got = H.current_supply(r, {H._norm_url(SN1): 12000})
    assert got[0][0] == "仕入元" and got[0][2] is None
    assert got[1] == ("補1", SN1, 12000)
