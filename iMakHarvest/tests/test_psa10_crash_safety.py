"""tests/test_psa10_crash_safety - 長時間走行の作業を捨てないことの検証 (2026-08-17).

事故: ワンピース 49語の走行で、収集487件 → 詳細145件まで進んだところで
chromedriver への通信が read timeout。例外が走行全体を殺し、**JSON 保存が
全ループ終了後の1回だけ**だったため 145件分 (Vision 読取 111回 = 課金済) が全部消えた。

守るべきことは3つ:
  ① 途中セーブがある (--save-every 件ごと)
  ② 1件の失敗で走行全体が死なない
  ③ 打ち切った時に「途中まで」と分かる (黙って正常終了しない)

driver / Vision / スプシは全部差し替えて、ネットワークなしで検証する。
"""
from __future__ import annotations

import json
import types

import pytest

import run_harvest_mercari_psa10 as R

pytestmark = pytest.mark.offline


def _args(**over):
    base = dict(
        price_min=3000, price_max=100000, min_rating=100, no_identity=False,
        cap_per_keyword=10, max_details=0, keywords=["PSA10 OP01"], games=None,
        keyword_interval=0.0, headless=True, manual=False, no_dedupe=True,
        save_every=2, max_consecutive_errors=3, resume_from_json=None,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)


@pytest.fixture
def stub(monkeypatch):
    """driver 生成と URL 収集を差し替える。 件数と 1件処理の挙動は test 側で決める."""
    monkeypatch.setattr(R.MS, "create_anonymous_driver",
                        lambda headless=False: types.SimpleNamespace(quit=lambda: None))

    def _collect_urls(keywords, driver, **kw):
        n = _collect_urls.count
        return {"urls": [f"https://jp.mercari.com/item/m{i}" for i in range(n)],
                "by_keyword": {keywords[0]: n}, "total_raw": n}

    _collect_urls.count = 6
    monkeypatch.setattr(R.MSch, "collect_multi_keyword_urls", _collect_urls)
    return _collect_urls


def _candidate(url):
    return {"url": url, "title": "t", "price_jpy": 1000, "condition": "",
            "description": "", "image_urls": ["https://x/1.jpg"],
            "seller_rating_count": 200, "seller_star": 5.0,
            "identity_verified": True,
            "vision": {"cert": "153420191", "grade": "GEM MT 10", "label": "L",
                       "card_number": "1", "year": "2024", "error": ""}}


# --------------------------------------------------------------------------
# ① 途中セーブ
# --------------------------------------------------------------------------

def test_saves_partway_not_only_at_the_end(monkeypatch, stub, tmp_path):
    """save_every 件ごとに JSON が育つ (= 落ちても直前までが残る)."""
    seen_counts = []

    def one(url, driver, args, claimed, rej, vision_errors):
        # 保存済ファイルの候補数を毎回記録する
        if dump.exists():
            seen_counts.append(len(json.loads(dump.read_text(encoding="utf-8"))["candidates"]))
        return _candidate(url)

    monkeypatch.setattr(R, "_process_one", one)
    dump = tmp_path / "d.json"
    R.collect(_args(save_every=2), dump_path=dump)

    # 走行中に 0 件でない状態が観測できていれば「最後に1回だけ」ではない
    assert any(c > 0 for c in seen_counts), seen_counts
    assert len(json.loads(dump.read_text(encoding="utf-8"))["candidates"]) == 6


def test_saves_url_list_before_detail_phase(monkeypatch, stub, tmp_path):
    """収集直後に保存する → 詳細で全滅しても URL 収集をやり直さない."""
    dump = tmp_path / "d.json"

    def boom(*a, **k):
        raise RuntimeError("driver dead")

    monkeypatch.setattr(R, "_process_one", boom)
    R.collect(_args(), dump_path=dump)
    saved = json.loads(dump.read_text(encoding="utf-8"))
    assert saved["by_keyword"] == {"PSA10 OP01": 6}


def test_dump_is_atomic(monkeypatch, stub, tmp_path):
    """途中セーブ中に落ちても前回分を壊さない (tmp → replace)."""
    dump = tmp_path / "d.json"
    R._dump({"candidates": [1]}, dump, quiet=True)
    assert not dump.with_suffix(".json.tmp").exists()
    assert json.loads(dump.read_text(encoding="utf-8"))["candidates"] == [1]


# --------------------------------------------------------------------------
# ② 1件の失敗で全体が死なない
# --------------------------------------------------------------------------

def test_one_bad_item_does_not_kill_the_run(monkeypatch, stub, tmp_path):
    def one(url, driver, args, claimed, rej, vision_errors):
        if url.endswith("m2"):
            raise RuntimeError("read timeout")  # 事故と同じ形
        return _candidate(url)

    monkeypatch.setattr(R, "_process_one", one)
    got = R.collect(_args(), dump_path=tmp_path / "d.json")
    assert len(got["candidates"]) == 5          # 6件中 1件だけ落ちる
    assert got["collect_reject"]["item_error"] == 1
    assert got["truncated"] is False


def test_driver_is_recreated_after_consecutive_failures(monkeypatch, stub, tmp_path):
    """連続失敗はドライバ死の疑い → 作り直して続行する."""
    created = []
    monkeypatch.setattr(
        R.MS, "create_anonymous_driver",
        lambda headless=False: created.append(1) or types.SimpleNamespace(quit=lambda: None))

    calls = {"n": 0}

    def one(url, driver, args, claimed, rej, vision_errors):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("chrome not reachable")
        return _candidate(url)

    monkeypatch.setattr(R, "_process_one", one)
    got = R.collect(_args(max_consecutive_errors=3), dump_path=tmp_path / "d.json")
    assert len(created) == 2                     # 初回 + 作り直し1回
    assert len(got["candidates"]) == 3           # 残り3件は拾えている


def test_truncated_flag_set_when_driver_cannot_be_rebuilt(monkeypatch, stub, tmp_path):
    """作り直しも失敗したら「途中まで」を明示する (黙って正常終了しない)."""
    state = {"n": 0}

    def mk(headless=False):
        state["n"] += 1
        if state["n"] > 1:
            raise RuntimeError("cannot start chrome")
        return types.SimpleNamespace(quit=lambda: None)

    monkeypatch.setattr(R.MS, "create_anonymous_driver", mk)
    monkeypatch.setattr(R, "_process_one",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dead")))
    got = R.collect(_args(max_consecutive_errors=2), dump_path=tmp_path / "d.json")
    assert got["truncated"] is True
    assert json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))["truncated"] is True


# --------------------------------------------------------------------------
# ③ 再開
# --------------------------------------------------------------------------

def test_resume_skips_already_processed_urls(monkeypatch, stub, tmp_path):
    done = ["https://jp.mercari.com/item/m0", "https://jp.mercari.com/item/m1"]
    resume = {"candidates": [_candidate(done[0])],
              "collect_reject": {"sold": 1},
              "processed_urls": done}

    touched = []

    def one(url, driver, args, claimed, rej, vision_errors):
        touched.append(url)
        return _candidate(url)

    monkeypatch.setattr(R, "_process_one", one)
    got = R.collect(_args(), dump_path=tmp_path / "d.json", resume=resume)

    assert not any(u in done for u in touched)   # 処理済は触らない
    assert len(touched) == 4                     # 6件中 残り4件だけ
    assert len(got["candidates"]) == 5           # 既存1 + 新規4
    assert got["collect_reject"]["sold"] == 1    # 前回の集計を引き継ぐ


def test_resume_carries_processed_urls_forward(monkeypatch, stub, tmp_path):
    resume = {"candidates": [], "collect_reject": {},
              "processed_urls": ["https://jp.mercari.com/item/m0"]}
    monkeypatch.setattr(R, "_process_one", lambda url, *a, **k: _candidate(url))
    got = R.collect(_args(), dump_path=tmp_path / "d.json", resume=resume)
    assert "https://jp.mercari.com/item/m0" in got["processed_urls"]
    assert len(got["processed_urls"]) == 6
