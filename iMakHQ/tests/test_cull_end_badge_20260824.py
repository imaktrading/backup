# -*- coding: utf-8 -*-
"""🗑 取下げ ボタンの残数表示 (2026-08-24 ユーザー要望)。

> 在庫メンテの取下げ (200件/回・自動) ボタンだけど、対象が出たらラベルを青にして、
> ヒントテキストで残数を表示するようにして

## 数え方の制約
**eBay を1回も叩かない。** 材料は funnel CSV (ローカル) と 済み台帳だけ。
同じ日に eBay の1日上限で取下げが5時間止まっており、表示のために枠を使うのは本末転倒。
(`iMakHQ/tools/ebay_api_usage.py` / 監視くん依頼 2026-08-24)

数え方は本処理 (`main()` の既定経路) と同じ `select()` を通す。
別の数え方をすると「押したら出る件数」とラベルがずれる。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_end as C  # noqa: E402


def _funnel(tmp_path, rows):
    p = tmp_path / "funnel_20260824.csv"
    cols = ["item_id", "title", "price", "age_days", "flags", "site"]
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in cols))
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(tmp_path)


def _row(iid, age=60, price=150, flags="CULL", site="US"):
    return {"item_id": iid, "title": f"t{iid}", "price": price,
            "age_days": age, "flags": flags, "site": site}


def test_counts_what_the_button_will_actually_do(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row(f"8200{i}") for i in range(5)])
    got = C.count_workload(funnel_dir=d)
    assert got["remaining"] == 5 and got["next"] == 5
    assert got["error"] == ""


def test_next_is_capped_but_remaining_is_not(tmp_path, monkeypatch):
    """1回 CAP 件まで。残りは全部見せる (あと何回か分かるように)。"""
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row(f"82{i:05}") for i in range(C.CAP + 38)])
    got = C.count_workload(funnel_dir=d)
    assert got["next"] == C.CAP
    assert got["remaining"] == C.CAP + 38


def test_already_dropped_are_excluded(tmp_path, monkeypatch):
    """済み台帳の分は残数に数えない (押しても出てこないので)。"""
    monkeypatch.setattr(C, "load_done", lambda: {"8200", "8201"})
    d = _funnel(tmp_path, [_row("8200"), _row("8201"), _row("8202")])
    got = C.count_workload(funnel_dir=d)
    assert got["remaining"] == 1 and got["done"] == 2


def test_only_unknown_age_is_not_counted(tmp_path, monkeypatch):
    """本処理と同じふるいを通す。ラベルと実際がずれない。

    ★2026-08-31: MIN_AGE を 14→1 (既知の若さでは待たない)、MIN_PRICE を撤廃
    (在庫0×需要ゼロは価格を問わず対象)。age==0 (=年齢不明の sentinel) だけ
    fail-closed で引き続き除外する。
    """
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("a", age=0), _row("b", price=10), _row("c")])
    assert C.count_workload(funnel_dir=d)["remaining"] == 2


def test_non_cull_rows_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("a", flags="RESTOCK"), _row("b", flags="CULL")])
    assert C.count_workload(funnel_dir=d)["remaining"] == 1


def test_missing_funnel_says_why(tmp_path):
    got = C.count_workload(funnel_dir=str(tmp_path))
    assert got["remaining"] == 0
    assert "funnel" in got["error"], got["error"]


def test_counting_never_touches_ebay():
    """★表示のために API 枠を使わない (同日に上限で取下げが5時間止まったため)。"""
    import inspect
    src = inspect.getsource(C.count_workload)
    for banned in ("_fetch_active_live", "GetMyeBaySelling", "ActiveList", "fx."):
        assert banned not in src, banned


# ── 画面側の配線 ──────────────────────────────────────────────────
def _panel_src():
    p = os.path.join(os.path.dirname(_TOOLS), "control_panel.py")
    return open(p, encoding="utf-8").read()


def test_button_is_registered_for_badge():
    src = _panel_src()
    assert '"badge": "cull_end"' in src, "残数を出すボタンとして登録されていない"


def test_panel_counts_and_paints():
    src = _panel_src()
    assert "d['cull']=CE.count_workload()" in src, "同じ subprocess で数えていない"
    assert '"cull_end": ce_txt' in src, "ヒントに出していない"
    # ★2026-09-03 (後): 青 = **押さないと減らない残件がある**。
    #   ユーザーは青いものしか押さないので、黒にすると永遠に押されない。
    assert '"cull_end": bool(ce.get("remaining"))' in src, "残件があれば青、になっていない"


@pytest.mark.parametrize("ce,blue", [
    ({"remaining": 138, "next": 138, "cap": 200, "done": 0}, True),
    ({"remaining": 0, "next": 0, "cap": 200, "done": 1278}, False),
    ({"error": "funnel_*.csv がありません"}, False),
])
def test_blue_only_when_something_will_happen(ce, blue):
    """0件なら黒のまま (色 = 今押す価値があるか、という既存の約束)。"""
    assert bool(ce.get("remaining")) is blue


# ── US 限定 (2026-08-24 ユーザー指摘) ──────────────────────────────
# > CULL取下げって、USのみで作らなかった？ … だって、ebaymagだから、US以外を触っても意味ない
#
# UK / AU / CA は eBaymag が US の親出品から作るミラー。親を落とせば付いてくるので、
# ミラーを直接落としても意味がない (親が生きていれば mag がまた作る)。
# 履歴を追ったところ US 限定になっていたのは隣の RESTOCK (063b626) だけで、
# CULL には入っていなかった。実測 1,408件のうち 643件がミラーだった。


def test_mirrors_are_not_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("us1"), _row("uk1", site="UK"),
                           _row("au1", site="AU"), _row("ca1", site="CA")])
    got = C.count_workload(funnel_dir=d)
    assert got["remaining"] == 1, "ミラーを落とそうとしている"


def test_unknown_site_is_not_touched(tmp_path, monkeypatch):
    """site が空 = ミラーか判らない → 落とさない (fail-closed)。"""
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("x", site="")])
    assert C.count_workload(funnel_dir=d)["remaining"] == 0


@pytest.mark.parametrize("site,want", [
    ("US", True), ("us", True), (" US ", True),
    ("UK", False), ("AU", False), ("CA", False), ("DE", False), ("", False), (None, False),
])
def test_is_target_site(site, want):
    assert C.is_target_site({"site": site}) is want


def test_cull_total_still_counts_every_site(tmp_path, monkeypatch):
    """CULL 全体 (母数) は絞らない。何件がミラーで除外されたかを言えるように。"""
    monkeypatch.setattr(C, "load_done", lambda: set())
    d = _funnel(tmp_path, [_row("us1"), _row("uk1", site="UK")])
    assert C.count_workload(funnel_dir=d)["cull"] == 2
