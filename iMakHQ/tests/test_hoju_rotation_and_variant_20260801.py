"""補URL補強の3要件の回帰テスト (2026-08-01・ユーザー指示)。

要件 (そのまま):
  1. 候補が違うのは、候補を合わせてもらわないと意味がない
  2. 正しい候補を、ちゃんと定期で探しに行ってもらわないと意味がない
  3. 正しい候補が、市場にないものは、次も探し続けるしかない

実装の対応:
  1 → `_build_visual_candidates` が **変種確証済(cands)を先頭**に並べ、各候補に
       `variant_ok` を付ける。確証UIは ✅変種一致 / ⚠️変種未確認 を候補ごとに出す。
  2 → `targets_needing_search` が **最後に探した日が古い順**に並べる。
       これが無いと select_backfill_targets の「新規出品優先」順のまま `todo[:limit]` で
       切られ、古い出品が永久に探索されない (実測 2026-08-01: 14件が7日前 / 22件が未探索)。
  3 → 候補ゼロでも cache entry は残るので、経過日数で必ず順番が回ってくる。
       「候補が無いから外す」を入れないこと自体をテストで固定する。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

from psa_hoju_fill import targets_needing_search          # noqa: E402
from psa_resource_gate import _build_visual_candidates    # noqa: E402
import psa_resource_confirm as prc                        # noqa: E402

TODAY = "2026-08-01"


def _t(iid, listed=0):
    return {"itemID": iid, "listed_at": listed}


def _entry(date, cands=None, all_cands=None):
    return {"date": date, "snkrdunk": {}, "mercari": {"cands": cands or [],
                                                      "all_cands": all_cands or []}}


# ---- 要件2: 定期で探しに行く (古い順) --------------------------------------

def test_oldest_cache_is_searched_first():
    """新規出品優先の入力順でも、**探索が古い物が先頭**に来ること。"""
    targets = [_t("new1"), _t("new2"), _t("old")]          # 入力は出品日時の降順
    cache = {"new1": _entry("2026-07-31"), "new2": _entry("2026-07-30"),
             "old": _entry("2026-07-25")}
    got = [t["itemID"] for t in targets_needing_search(targets, cache, TODAY)]
    assert got == ["old", "new2", "new1"]


def test_never_searched_comes_before_everything():
    targets = [_t("stale"), _t("never")]
    cache = {"stale": _entry("2026-07-25")}                # never は cache 無し
    got = [t["itemID"] for t in targets_needing_search(targets, cache, TODAY)]
    assert got[0] == "never"


def test_same_age_keeps_new_listing_first():
    """同じ経過日数なら入力順(=新規出品が先)が保たれること(安定ソート)。"""
    targets = [_t("newer"), _t("older")]
    cache = {"newer": _entry("2026-07-30"), "older": _entry("2026-07-30")}
    got = [t["itemID"] for t in targets_needing_search(targets, cache, TODAY)]
    assert got == ["newer", "older"]


def test_all_targets_rotate_within_limit_cycles():
    """★本丸: limit で切っても **全対象がいつか必ず探索される**こと。

    古い順に並ばないと、対象数 > limit の間 古い出品は永久に探索されない。
    ここでは 5対象 / limit=2 で3周し、全部が一度は探索されることを確認する。
    """
    import datetime
    ids = [f"i{n}" for n in range(5)]
    cache = {i: _entry("2026-07-20") for i in ids}         # 全部 古い
    day = datetime.date(2026, 8, 1)
    searched = set()
    for _ in range(3):
        today = day.isoformat()
        todo = targets_needing_search([_t(i) for i in ids], cache, today)[:2]
        for t in todo:
            searched.add(t["itemID"])
            cache[t["itemID"]] = _entry(today)             # 探索した = 日付を更新
        day += datetime.timedelta(days=1)
    assert searched == set(ids), f"探されなかった対象がある: {set(ids) - searched}"


# ---- 要件3: 市場に無くても探し続ける ---------------------------------------

def test_no_supply_target_is_never_dropped():
    """候補ゼロで焼かれた対象も、翌日以降ちゃんとキューに戻ってくること。"""
    targets = [_t("nostock")]
    empty = _entry("2026-07-29", cands=[], all_cands=[])   # 探したが候補ゼロ
    assert [t["itemID"] for t in targets_needing_search(targets, {"nostock": empty}, TODAY)] \
        == ["nostock"]


def test_searched_today_is_skipped_but_only_today():
    """当日済は同じ夜に二度叩かない (レジューム耐性) が、翌日は戻る。"""
    targets = [_t("x")]
    assert targets_needing_search(targets, {"x": _entry(TODAY)}, TODAY) == []
    assert len(targets_needing_search(targets, {"x": _entry(TODAY)}, "2026-08-02")) == 1


# ---- 要件1: 候補を合わせる --------------------------------------------------

_OK = (1000, "https://jp.mercari.com/item/m_ok", "正変種 PSA10")
_NG = (900, "https://jp.mercari.com/item/m_ng", "別変種 PSA10")


def test_variant_verified_candidate_comes_first():
    """安い別変種より、**変種が確証できた候補**を先に見せること。"""
    mr = {"cands": [_OK], "all_cands": [_NG, _OK]}
    got = _build_visual_candidates(mr, {})
    assert [c["url"] for c in got] == [_OK[1], _NG[1]]
    assert got[0]["variant_ok"] is True
    assert got[1]["variant_ok"] is False


def test_unverified_candidates_are_marked():
    """cands が空(出品名にセット名が無く確証不能)でも、黙って混ぜず未確認と分かること。"""
    got = _build_visual_candidates({"cands": [], "all_cands": [_NG]}, {})
    assert got and got[0]["variant_ok"] is False


def test_snkrdunk_is_variant_accurate():
    got = _build_visual_candidates({}, {"snkrdunk_urls": [{"url": "https://snkrdunk.com/x"}]})
    assert got and got[0]["variant_ok"] is True


def test_confirm_html_shows_variant_badges():
    html = prc.build_restock_html([{
        "idx": 1, "title": "t", "card_no": "OP06-106", "ebay_url": "https://e/1",
        "ref_image": "https://r/ref.jpg",
        "candidates": [{"channel": "mercari", "url": "https://m/1", "price": 1,
                        "variant_ok": True},
                       {"channel": "mercari", "url": "https://m/2", "price": 2,
                        "variant_ok": False}]}])
    assert "✅変種一致" in html
    assert "⚠️変種未確認" in html


def test_confirm_html_backward_compatible_without_flag():
    """variant_ok を持たない旧呼出ではバッジを出さない(誤った安心を与えない)。"""
    html = prc.build_restock_html([{
        "idx": 1, "title": "t", "card_no": "X", "ebay_url": "https://e/1",
        "ref_image": "https://r/ref.jpg",
        "candidates": [{"channel": "mercari", "url": "https://m/1", "price": 1}]}])
    assert "変種一致" not in html and "変種未確認" not in html
