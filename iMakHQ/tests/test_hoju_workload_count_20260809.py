"""ボタンのラベル件数が「押したら何件できるか」と一致することの回帰テスト (2026-08-09)。

事故: パネルが「目視待ち 32件」と出したが、押すと 3件しか出なかった。
真因は control_panel が **足切りを一切通していない母数** (キャッシュに候補URLが
1本でもある件数) を「目視待ち」と表示していたこと。件数は段取りを決めるために
見るものなので、10倍ずれる数字はラベルとして意味がない (ユーザー指摘)。

対策: 足切りを confirm_survivors に1本化し、本番 confirm と件数計算が
**同じ関数を通る**ようにした。ここではその一本化が崩れないことを固定する。
"""
import os
import sys
import collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakeBayAPI"))

import psa_hoju_fill as H  # noqa: E402


def _ctx(skip=(), ng=None, used=None, guard_ok=True):
    return {"skip_iids": set(skip), "ng_by_iid": dict(ng or {}),
            "used_by_others": dict(used or {}), "revived": 0,
            "newsupply": set(), "guard_ok": guard_ok}


def _vals(item_id, main_url="", aux=()):
    """HIGH シート相当の2次元配列 (ヘッダ + 1行)。"""
    width = max(H.AUX0 + H.AUXN, H.KEY + 1)
    head = [""] * width
    row = [""] * width
    row[H.A] = main_url
    row[H.B] = item_id
    for i, u in enumerate(aux):
        row[H.AUX0 + i] = u
    return [head, row]


def _target(item_id, row=2, cert="123", key="one_piece:OP01-024"):
    return {"itemID": item_id, "row": row, "cert": cert, "key": key,
            "title": "PSA10 test", "n_backups": 0}


def _entry(urls, date):
    """psa_research_cache の1件分 (mercari 候補 N本 + snkrdunk 無し)。"""
    return {"date": date, "snkrdunk": {},
            "mercari": {"best": None, "cands": [(1000, u, "name") for u in urls],
                        "all_cands": [(1000, u, "name") for u in urls]}}


TODAY = "2026-08-09"
REF = "https://i.ebayimg.com/x.jpg"


def _run(t, vals, cache, ctx, *, ref=REF, art=None):
    stats = collections.Counter()
    art = art or (lambda r, c, tt: (c, []))
    cands, got_ref, why, dropped = H.confirm_survivors(
        t, vals, cache, ctx, TODAY, ref_of=lambda _t: ref, art_of=art, stats=stats)
    return cands, why, stats


def test_skip_ledger_is_counted_not_shown():
    t = _target("111")
    cands, why, stats = _run(t, _vals("111"), {"111": _entry(["u1"], TODAY)},
                             _ctx(skip=["111"]))
    assert (cands, why) == ([], "skip_ledger")
    assert stats["skip_ledger"] == 1


def test_stale_cache_is_not_countable():
    t = _target("111")
    cands, why, _ = _run(t, _vals("111"), {"111": _entry(["u1"], "2026-07-01")}, _ctx())
    assert (cands, why) == ([], "no_cache")


def test_candidate_already_used_by_self_wipes_the_item():
    """主URL/既存補URLと同じ供給しか無い = 目視が成立しない (画面に出ない)。"""
    t = _target("111")
    vals = _vals("111", main_url="https://jp.mercari.com/item/m1")
    cands, why, stats = _run(t, vals, {"111": _entry(["https://jp.mercari.com/item/m1"], TODAY)},
                             _ctx())
    assert (cands, why) == ([], "all_known")
    assert stats["cand_known"] == 1


def test_art_verdict_can_wipe_the_item():
    t = _target("111")
    cands, why, stats = _run(t, _vals("111"), {"111": _entry(["https://jp.mercari.com/item/m9"], TODAY)},
                             _ctx(), art=lambda r, c, tt: ([], list(c)))
    assert (cands, why) == ([], "all_art")
    assert stats["cand_art"] == 1


def test_survivor_is_returned_with_ref():
    t = _target("111")
    stats = collections.Counter()
    cands, ref, why, _ = H.confirm_survivors(
        t, _vals("111"), {"111": _entry(["https://jp.mercari.com/item/m9"], TODAY)},
        _ctx(), TODAY, ref_of=lambda _t: REF, art_of=lambda r, c, tt: (c, []), stats=stats)
    assert why == "" and ref == REF and len(cands) == 1


def test_missing_ref_image_is_not_countable():
    """現物が見えない = 人に確定させない (fail-closed)。件数にも入れない。"""
    t = _target("111")
    cands, why, _ = _run(t, _vals("111"), {"111": _entry(["https://jp.mercari.com/item/m9"], TODAY)},
                         _ctx(), ref="")
    assert (cands, why) == ([], "no_ref")


def test_every_target_lands_in_exactly_one_bucket():
    """件数の検算: 対象 = 出せる件数 + 各 STOP_REASONS の合計。

    ここが崩れると「32件と出て3件」の再発 (どこかで黙って落ちている)。
    """
    cases = [
        (_target("1"), _vals("1"), {"1": _entry(["https://jp.mercari.com/item/a"], TODAY)}),
        (_target("2"), _vals("2"), {"2": _entry(["https://jp.mercari.com/item/b"], "2026-01-01")}),
        (_target("3"), _vals("3"), {"3": _entry([], TODAY)}),
        (_target("4"), _vals("4", main_url="https://jp.mercari.com/item/d"),
         {"4": _entry(["https://jp.mercari.com/item/d"], TODAY)}),
    ]
    stats = collections.Counter()
    shown = 0
    for t, vals, cache in cases:
        cands, _ref, _why, _d = H.confirm_survivors(
            t, vals, cache, _ctx(), TODAY, ref_of=lambda _t: REF,
            art_of=lambda r, c, tt: (c, []), stats=stats)
        if cands:
            shown += 1
    assert shown + sum(stats[k] for k in H.STOP_REASONS) == len(cases)


def test_stop_reasons_cover_all_early_returns():
    """confirm_survivors が返しうる理由が STOP_REASONS に全部載っていること。

    載っていない理由があると、ラベルの内訳から黙って消える (silent drop)。
    """
    import inspect
    src = inspect.getsource(H.confirm_survivors)
    returned = {ln.split('"')[-2] for ln in src.splitlines()
                if 'return [], ' in ln and '"' in ln}
    returned |= {'all_art'}      # ref を返す枝 (return [], ref, "all_art", ...)
    assert returned <= set(H.STOP_REASONS), returned - set(H.STOP_REASONS)
