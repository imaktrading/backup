# -*- coding: utf-8 -*-
"""目視待ちの入口と出口で、見る意味の無い物を省く (2026-10-10 ユーザー「入口出口で省いて欲しい」)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import aux_pending as AP  # noqa: E402


def srow(iid, a="", aux=(), key=""):
    r = [""] * 40
    r[0], r[1], r[34] = a, iid, key
    for k, u in enumerate(aux):
        r[28 + k] = u
    return r


def test_junk_reasons():
    r = srow("1", "https://m/a", ["https://m/b?x=1"], "pokemon_tcg:M-P-020")
    assert AP.junk_reason("https://m/z", None) == "出品が消えた"
    assert AP.junk_reason("https://m/a", r) == "既に主URL/補URLに入っている"
    assert AP.junk_reason("https://m/b", r) == "既に主URL/補URLに入っている"
    assert AP.junk_reason("https://m/c", r, {"https://m/c"}) == "買えない URL"
    uv = {"https://m/d": {"M-P-020": {"v": "diff"}}}
    assert AP.junk_reason("https://m/d", r, set(), uv) == "このカードと「違う」と答えた URL"
    assert AP.junk_reason("https://m/e", r, set(), uv) == ""


def test_sweep_moves_junk_to_dropped_file(tmp_path):
    p, dp = str(tmp_path / "q.jsonl"), str(tmp_path / "d.jsonl")
    rows = [{"itemID": "1", "url": "https://m/a"}, {"itemID": "1", "url": "https://m/new"},
            {"itemID": "9", "url": "https://m/x"}, {"itemID": "", "url": "https://m/old"}]
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    vals = [["h"], srow("1", "https://m/a")]
    why = AP.sweep(vals, path=p, dropped_path=dp, ctx=({"1": vals[1]}, set(), {}))
    assert why == {"既に主URL/補URLに入っている": 1, "出品が消えた": 1}
    assert [r["url"] for r in AP.load(p)] == ["https://m/new", "https://m/old"]
    assert {r["reason"] for r in AP.load(dp)} == set(why)


def test_sweep_does_nothing_without_sheet(tmp_path):
    p = str(tmp_path / "q.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"itemID": "1", "url": "u"}) + "\n")
    assert AP.sweep([], path=p) == {} and len(AP.load(p)) == 1


def test_queue_skips_junk_at_entry(tmp_path, monkeypatch):
    p = str(tmp_path / "q.jsonl")
    vals = [["h"], srow("1", "https://m/a")]
    monkeypatch.setattr(AP, "load_context", lambda v: ({"1": vals[1]}, {"https://m/nb"}, {}))
    n = AP.queue({2: ["https://m/a", "https://m/nb", "https://m/ok"]}, "test", item_of={2: "1"}, path=p, vals=vals)
    assert n == 1 and [r["url"] for r in AP.load(p)] == ["https://m/ok"]


def test_badge_and_run_merge_pending_the_same_way():
    """ボタンの件数と本番が、目視待ちを同じ関数で混ぜる (2026-10-10 件数と画面のずれ)。"""
    src = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    i, j = src.index("def count_workload("), src.index("def run_daytime_confirm(")
    assert "merge_pending_cands(" in src[i:j] and "load_pending_by_iid(" in src[i:j]
    assert "merge_pending_cands(" in src[j:] and "load_pending_by_iid(" in src[j:]
    # 手前で落ちた出品 (ref が空) でも目視待ちは見比べられれば出す
    assert src[j:].count("if _pend and not ref:") == 1


def test_queue_consumed_only_when_shown():
    src = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    j = src.index("def run_daytime_confirm(")
    assert "enumerate(items[:n_ui])" in src[j:] and "_shown_pending.append" not in src[j:]


def test_plain_pokemon_drops_ball_mirror_titles():
    """通常版の出品に ボールのミラーを出さない (SV8a-092 ブラッキー に モンスターボールミラー が出ていた)。"""
    import mercari_psa_resource as mp
    assert mp.mirror_title_conflicts("plain", "PSA10 ブラッキー モンスターボールミラー 092/187")
    assert mp.mirror_title_conflicts("plain", "PSA10 ブラッキー マスターボールミラー")
    assert not mp.mirror_title_conflicts("plain", "PSA10 ブラッキー 092/187 テラスタルフェス")
    assert not mp.mirror_title_conflicts("", "PSA10 ブラッキー モンスターボールミラー")


def test_plain_kind_only_for_pokemon_without_version_mark(monkeypatch):
    import mercari_psa_resource as mp
    import psa_resource_confirm as prc
    import psa_hoju_fill as P
    monkeypatch.setattr(prc, "psa_label_facts", lambda cert, card_no="": {"variety": "", "brand": "POKEMON SV8a"})
    assert P.mirror_kind_for_target({"cert": "1", "key": "pokemon_tcg:SV8a-092"}, mp) == "plain"
    assert P.mirror_kind_for_target({"cert": "1", "key": "pokemon_tcg:SV8a-092_mb"}, mp) == ""
    assert P.mirror_kind_for_target({"cert": "1", "key": "one_piece_tcg:OP01-001"}, mp) == ""
    monkeypatch.setattr(prc, "psa_label_facts", lambda cert, card_no="": {"variety": "", "brand": ""})
    assert P.mirror_kind_for_target({"cert": "1", "key": "pokemon_tcg:SV8a-092"}, mp) == ""
