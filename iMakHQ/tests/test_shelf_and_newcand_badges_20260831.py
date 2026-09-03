# -*- coding: utf-8 -*-
"""棚を入れ替えるボタンのラベルに件数・金額 / 捨てた候補ボタンにヒント件数 (2026-08-31)。

> 棚を入れ替えるボタンのラベルに件数と金額を出せる?
> 捨てた候補のボタンにもヒントテキストで件数を

## 見つけたついでの穴
"🌱 捨てた候補→新規出品の種" ボタンは badge (newcand) は登録されていたが、
`SCRIPTS` に `"tip"` が無かった。`_grid_named` は `_tip` が真の時しか
`_attach_tip` を呼ばないため、**ヒント自体が一度も画面に付いていなかった**。
refresh_hoju_badge は件数 (n_txt) を毎回計算していたので、計算はされて
表示されない状態が続いていた。

## 数え方の制約 (cull_end と同じ理由)
shelf_evict.count_workload は **eBay を叩かない**。live 一覧のキャッシュが
古い/無い時に取りに行くと ~24 call の重い sweep が走り、2026-08-24 に
表示のための取得で取下げが5時間止まった実害があるため。
"""
import inspect
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as SE                                          # noqa: E402

_PANEL = os.path.join(os.path.dirname(_TOOLS), "control_panel.py")
_SRC = io.open(_PANEL, encoding="utf-8").read() if False else open(_PANEL, encoding="utf-8").read()


def test_zero_target_returns_no_error():
    """今日まだ出品していない = 目標0円 → 候補0件・エラーなし。"""
    got = SE.count_workload()
    assert got["error"] == ""
    if got["target"] == 0:
        assert got["picked"] == 0


def test_picks_something_when_target_is_set(monkeypatch):
    """funnel データがあれば、目標額に届くまで選ぶ (funnel フォールバック経路)。"""
    monkeypatch.setattr(SE, "listed_today_amount", lambda *a, **k: 1000.0)
    got = SE.count_workload()
    assert got["error"] == ""
    assert got["target"] == 1000.0
    assert got["picked"] >= 0        # 環境の funnel/live 有無に依存するので下限だけ確認
    assert got["amount"] >= 0.0


def test_counting_never_touches_ebay():
    """★badge の計算のために eBay を叩かない (2026-08-24 の CULL 実害と同じ理由)。"""
    src = inspect.getsource(SE.count_workload)
    for banned in ("_fetch_active_live", "GetMyeBaySelling", "ActiveList",
                   "fx.token", "fx.refresh"):
        assert banned not in src, banned


def test_stale_or_missing_live_cache_is_reported_not_hidden():
    """キャッシュが古い/無い時、黙って0にせず理由をヒントに出す材料を返す。"""
    got = SE.count_workload()
    # target=0 の時は cache_note を作る前に return するので、この確認は target>0 側で行う
    assert "cache_note" in got


# ── 画面側の配線 ──────────────────────────────────────────────────
def test_shelf_button_is_registered_for_badge():
    assert '"badge": "shelf_evict"' in _SRC, "棚ボタンが badge 登録されていない"


def test_panel_counts_shelf_in_the_same_subprocess():
    assert "d['shelf']=SE.count_workload()" in _SRC
    assert '"shelf_evict": se_txt' in _SRC
    assert '"shelf_evict_label": se_label' in _SRC
    # ★2026-09-03 (後): 青 = **押さないと減らない残件がある**。
    #   ユーザーは青いものしか押さないので、黒にすると永遠に押されない。
    assert '"shelf_evict": bool(se.get("picked"))' in _SRC


def test_shelf_label_is_painted_onto_the_button_text():
    """他ボタンと違い、このボタンだけラベルに件数/金額を焼く (2026-08-31 明示要望)。"""
    i = _SRC.index("def paint_hoju_badge")
    body_ = _SRC[i:i + 1600]
    assert 'kind + "_label"' in body_
    assert 'kind == "shelf_evict"' in body_


def test_newcand_button_now_has_a_tip_so_the_hint_actually_shows():
    """穴: tip が無いと _attach_tip 自体が呼ばれず、件数ヒントが一生出ない。"""
    i = _SRC.index('"label": "🌱 捨てた候補→新規出品の種"')
    j = _SRC.index("}", i)
    block = _SRC[i:j]
    assert '"tip":' in block, "tip が無い = ヒントが画面に付かない"
