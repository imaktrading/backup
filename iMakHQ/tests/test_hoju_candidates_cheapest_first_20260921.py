"""補充の画面で安い候補を後ろに隠さない (2026-09-21)。

ユーザー「補充で出たカードが入れ替えで何で出てくるの？」。
候補を各6件で切ってから既存の補URLを除いていたので、補充では枠が既存URLに食われて
安い候補が7件目以降に隠れ、補URLが入った後の入れ替え画面で繰り上がって出ていた
(実測: 5出品が両方の画面に出た)。除く物を先に除き、安い順に並べてから切る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_resource_gate as G  # noqa: E402


def _merc(n, base=10000):
    return [(base + i * 1000, f"https://jp.mercari.com/item/m{i:011d}", "PSA10") for i in range(n)]


def test_既に付いている補URLは枠を食わない():
    cands = _merc(9)
    known = [u for _p, u, _n in cands[:6]]           # 安い6本は既に補URLに入っている
    out = G._build_visual_candidates({"all_cands": cands}, {}, exclude=known)
    urls = [c["url"] for c in out]
    assert urls == [u for _p, u, _n in cands[6:9]]   # 7〜9件目が補充の画面に出る


def test_メルカリは安い順に出る():
    cands = list(reversed(_merc(8)))                 # 高い順で来ても
    out = G._build_visual_candidates({"all_cands": cands}, {})
    prices = [c["price"] for c in out]
    assert prices == sorted(prices) and prices[0] == 10000 and len(prices) == 6


def test_スニダンも安い順で既存を除いてから切る():
    snk = [{"url": f"https://snkrdunk.com/apparels/1/used/{i}", "price": 30000 - i * 1000}
           for i in range(9)]
    known = [snk[8]["url"]]                          # 一番安いのは既に付いている
    out = G._build_visual_candidates({}, {"snkrdunk_urls": snk}, exclude=known)
    prices = [c["price"] for c in out if c["channel"] == "snkrdunk"]
    assert prices == [23000, 24000, 25000, 26000, 27000, 28000]


# ── 押し出した候補を「見送り」に残す (同日 ユーザー「入れ替えで1回目に見た候補がまた出る」) ──
import psa_hoju_fill as H  # noqa: E402


def _vals_with_aux(aux):
    ncol = H.AUX0 + H.AUXN + 1
    row = [""] * ncol
    row[H.A] = "https://jp.mercari.com/item/mMAIN"
    for k, u in enumerate(aux):
        row[H.AUX0 + k] = u
    return [[""] * ncol, row]


def test_5本から押し出した既存と入らなかった候補は見送りに残る():
    old = [f"https://snkrdunk.com/apparels/1/used/{i}" for i in range(5)]
    new = ["https://snkrdunk.com/apparels/1/used/new1", "https://snkrdunk.com/apparels/1/used/new2"]
    vals = _vals_with_aux(old)
    t = [{"row": 2, "itemID": "111", "cert": "9", "title": "x"}]
    full = [new[0]] + old[:4]                        # new1 が入り old4 が押し出され new2 は入らず
    rows = H.pushed_out_as_skipped({0: new}, t, vals, {2: full},
                                   {0: {new[1]: 20000}}, "2026-09-21")
    got = {r[2]: r[6] for r in rows}
    assert got == {old[4]: "", new[1]: 20000}
    assert all(r[7] == "見送り" for r in rows)


def test_書込が無い行は何も記録しない():
    vals = _vals_with_aux(["https://a/1"])
    t = [{"row": 2, "itemID": "111"}]
    assert H.pushed_out_as_skipped({0: ["https://a/2"]}, t, vals, {}, {}, "d") == []


def test_見送りは枠を食わず値段が下がった物だけ出る():
    cands = _merc(8)
    skipped = {cands[0][1]: 10000, cands[1][1]: 12000}   # 0番は同額 / 1番は 11000 に値下がり
    out = G._build_visual_candidates({"all_cands": cands}, {}, skipped=skipped)
    urls = [c["url"] for c in out]
    assert cands[0][1] not in urls and cands[1][1] in urls and len(urls) == 6


# ── 入れ替えは今の5本の一番高い物と比べる (同日 ユーザー「再走しても同じ候補」) ──
def test_入れ替えの基準は今の5本の一番高い値段():
    aux = [f"https://snkrdunk.com/apparels/1/used/{i}" for i in range(5)]
    vals = _vals_with_aux(aux)
    prices = {H._norm_url(u): 5800 for u in aux}
    t = {"row": 2}
    base = H.swap_baseline(9000, t, vals, prices)
    assert base == 5800
    # 同額の ¥5,800 は出さない / ¥4,800 は出す
    assert H.candidate_cost_conflicts(5800, base, False, H.SWAP_MIN_GAIN) is True
    assert H.candidate_cost_conflicts(4800, base, False, H.SWAP_MIN_GAIN) is False


def test_補URLの値段が1本でも分からなければ仕入値のまま():
    aux = [f"https://a/{i}" for i in range(5)]
    prices = {H._norm_url(u): 5800 for u in aux[:4]}
    assert H.swap_baseline(9000, {"row": 2}, _vals_with_aux(aux), prices) == 9000


# ── 安い既存の補URLを押し出さない (同日 ユーザー「安いのを捨てたらあかんやろ」) ──
def test_高い候補を選んでも安い既存は残る():
    aux = [f"https://snkrdunk.com/apparels/1/used/{i}" for i in range(5)]
    vals = _vals_with_aux(aux)
    t = [{"row": 2, "itemID": "111"}]
    new = "https://jp.mercari.com/item/mEXPENSIVE"
    table = {H._norm_url(u): 5000 for u in aux}
    pbi = H.add_existing_prices({0: {H._norm_url(new): 8000}}, {0: [new]}, t, vals, prices=table)
    wb, added, _d, removed = H.plan_aux_writeback({0: [new]}, t, vals, {}, True, price_by_url=pbi)
    assert added == 0 and removed == []          # 高い方は入らず、安い5本がそのまま
    assert wb == {}


def test_安い候補なら一番高い既存と入れ替わる():
    aux = [f"https://snkrdunk.com/apparels/1/used/{i}" for i in range(5)]
    vals = _vals_with_aux(aux)
    t = [{"row": 2, "itemID": "111"}]
    new = "https://jp.mercari.com/item/mCHEAP"
    table = {H._norm_url(u): 5000 + i * 100 for i, u in enumerate(aux)}
    pbi = H.add_existing_prices({0: {H._norm_url(new): 4000}}, {0: [new]}, t, vals, prices=table)
    _wb, added, _d, removed = H.plan_aux_writeback({0: [new]}, t, vals, {}, True, price_by_url=pbi)
    assert added == 1 and [u for _i, u in removed] == [aux[4]]


def test_B列9999の見送り行は補URLの対象外():
    ncol = max(H.B, H.CERT, H.CATEGORY, H.KEY, H.D, H.C) + 1
    row = [""] * ncol
    row[H.B], row[H.CERT], row[H.CATEGORY], row[H.KEY] = "9999", "149064758", "TCG", "one_piece_tcg:OP01-025"
    assert H.select_backfill_targets([[""] * ncol, row], max_backups=6) == []
