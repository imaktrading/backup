"""PSA新規の選定: ポケモン70% + 各グループ内は売れ筋順 (2026-09-08 ユーザー確定).

> ポケモン７０％、売れ筋優先。それ以外は適当でいい

均等(1:1:1)をやめた根拠 (実測 / funnel + US live):
  ポケモン 273件/$53,439/売れた11 (=$1万あたり2.06) vs ワンピース 211件/$60,086/売れた3 (0.50)
  ガンダム15件・ドラゴンボール10件は 売れた0。
安い順の根拠: 出品価格 $100未満の売却率 5.2% / $400超 1.6%。棚(金額枠)は超過中。
"""
import collections
import sys
from pathlib import Path

TCG = Path(__file__).resolve().parent.parent.parent / "iMakTCG"
if str(TCG) not in sys.path:
    sys.path.insert(0, str(TCG))

from tcg_batch_select import balanced_sample, classify_franchise  # noqa: E402

NOSHUFFLE = lambda x: None  # noqa: E731  (並びを固定して比率だけ見る)


def _titles(n_pk=50, n_op=50, n_db=5):
    tm = {f"p{i}": "ポケモン" for i in range(n_pk)}
    tm.update({f"o{i}": "ワンピース" for i in range(n_op)})
    tm.update({f"d{i}": "ドラゴンボール" for i in range(n_db)})
    return tm


def test_pokemon_is_seventy_percent():
    tm = _titles()
    got = balanced_sample(list(tm), tm, 20, shuffle=NOSHUFFLE)
    dist = collections.Counter(classify_franchise(tm[c]) for c in got)
    assert dist["Pokemon"] == 14, dist          # 20 * 0.7
    assert sum(dist.values()) == 20


def test_others_share_the_rest_round_robin():
    """残り3割は ワンピース→ドラゴンボール→… で配る (0件にはしない = 需要の再確認枠)."""
    tm = _titles()
    got = balanced_sample(list(tm), tm, 20, shuffle=NOSHUFFLE)
    dist = collections.Counter(classify_franchise(tm[c]) for c in got)
    assert dist["OnePiece"] >= 1 and dist["DragonBall"] >= 1, dist


def test_slot_is_never_left_empty():
    """ポケモンが足りなければ他で、他が無ければポケモンで埋める."""
    tm = {f"p{i}": "ポケモン" for i in range(30)}
    got = balanced_sample(list(tm), tm, 20, shuffle=NOSHUFFLE)
    assert len(got) == 20
    tm2 = {"p0": "ポケモン", **{f"o{i}": "ワンピース" for i in range(30)}}
    assert len(balanced_sample(list(tm2), tm2, 20, shuffle=NOSHUFFLE)) == 20


def test_cheaper_first_within_group():
    """安い順は **今は使っていない** (売れ筋順に差し替え)。道具としては残す."""
    tm = {f"p{i}": "ポケモン" for i in range(10)}
    cost = {f"p{i}": (10 - i) * 1000 for i in range(10)}      # p0 が一番高い
    got = balanced_sample(list(tm), tm, 5, shuffle=NOSHUFFLE,
                          cost_of=lambda c: cost.get(c), explore=0)
    assert got == ["p9", "p8", "p7", "p6", "p5"], got


def test_unknown_cost_goes_last_not_first():
    """値段が分からない物を「安い」と決めつけない (推測で前に出さない)."""
    tm = {f"p{i}": "ポケモン" for i in range(3)}
    cost = {"p0": None, "p1": 5000, "p2": 1000}
    got = balanced_sample(list(tm), tm, 3, shuffle=NOSHUFFLE,
                          cost_of=lambda c: cost.get(c), explore=0)
    assert got == ["p2", "p1", "p0"], got


def test_explore_slice_keeps_random_entries():
    """探索枠のぶんは安い順に並べ替えない (データの無い物を順位で殺さない)."""
    tm = {f"p{i}": "ポケモン" for i in range(10)}
    cost = {f"p{i}": (10 - i) * 1000 for i in range(10)}
    got = balanced_sample(list(tm), tm, 10, shuffle=NOSHUFFLE,
                          cost_of=lambda c: cost.get(c), explore=0.2)
    assert got[:2] == ["p0", "p1"], got        # 先頭2件 = 探索枠 (元の並びのまま)


# ---- 売れ筋順 (2026-09-08 ユーザー確定) --------------------------------------
def test_demand_order_within_group():
    tm = {f"p{i}": "ポケモン" for i in range(4)}
    dm = {"p0": 1.0, "p1": 9.0, "p2": 5.0, "p3": 3.0}
    got = balanced_sample(list(tm), tm, 4, shuffle=NOSHUFFLE, demand_of=lambda c: dm[c])
    assert got == ["p1", "p2", "p3", "p0"], got


def test_unscored_go_last_in_original_order():
    """点が付かない物は後ろ。順不同でよい (「それ以外は適当でいい」)."""
    tm = {f"p{i}": "ポケモン" for i in range(4)}
    dm = {"p0": None, "p1": 9.0, "p2": None, "p3": 3.0}
    got = balanced_sample(list(tm), tm, 4, shuffle=NOSHUFFLE, demand_of=lambda c: dm[c])
    assert got[:2] == ["p1", "p3"], got
    assert set(got[2:]) == {"p0", "p2"}, got


def test_demand_by_set_reads_both_title_shapes():
    """ワンピは `#OP09-001`、ポケモンは `Sv8a:` からセットを取る."""
    from tcg_batch_select import demand_by_set, set_of_key
    rows = [{"title": "PSA 10 One Piece #OP09-001 Shanks", "sold_qty": "1",
             "watch": "0", "impr_total": "0"},
            {"title": "PSA 10 Pokemon Japanese Sv8a: Terastal #203/187 X",
             "sold_qty": "0", "watch": "10", "impr_total": "0"}]
    d = demand_by_set(rows)
    assert d["OP09"] == 100.0 and d["SV8A"] == 80.0, d
    assert set_of_key("pokemon_tcg:SV8a-203") == "SV8A"
    assert set_of_key("item:m123") is None


def test_demand_scoring_is_not_reimplemented():
    """配点は demand_winners と同じ (実売*100 + watch*8 + 表示*0.05)."""
    src = (TCG / "tcg_batch_select.py").read_text(encoding="utf-8")
    i = src.index("def demand_by_set(")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    assert "* 100" in body and "* 8" in body and "0.05" in body
