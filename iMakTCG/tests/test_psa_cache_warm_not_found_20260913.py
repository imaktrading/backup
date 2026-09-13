# -*- coding: utf-8 -*-
"""夜間の PSA データ先貯めが「ページの無い cert」で毎晩止まっていた (2026-09-13)。

get_psa_data は Cloudflare でも「PSA にページが無い」でも None を返す。先貯めは None を全部
Cloudflare とみなして打ち切っていたので、ページの無い cert (936643273) が候補の3件目にあるだけで
**40件のはずが毎晩2件で終わる**。8/19 に作られてから一度も動いていなかったタスクを有効化した
直後の試走 (3件) で発覚した。
"""
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import psa_cache_warm as W  # noqa: E402

NOT_FOUND_PAGE = ("PSA Japan ホーム はじめに 料金とサービス カード検索 "
                  "リクエストされたページが見つかりませんでした。 申し訳ございませんが、お探しのページが見つかりませんでした。")
CF_PAGE = "<title>Just a moment...</title> Cloudflare Ray ID: 8c1 challenge-platform"


def test_not_found_page_is_not_cloudflare():
    assert W.failure_kind(NOT_FOUND_PAGE) == "not_found"
    assert W.failure_kind(CF_PAGE) == "cloudflare"
    assert W.failure_kind("") == "unknown"
    assert W.failure_kind(None) == "unknown"


def test_not_found_cert_is_skipped_for_thirty_days():
    led = {"936643273": "2026-09-13T20:40:00"}
    assert W.recently_not_found("936643273", led, today=datetime(2026, 9, 20))
    assert not W.recently_not_found("936643273", led, today=datetime(2026, 10, 14))
    assert not W.recently_not_found("111", led, today=datetime(2026, 9, 20))


def test_pending_skips_recorded_not_found():
    led = {"936643273": datetime.now().isoformat(timespec="seconds")}
    todo = W.pending_certs(["1", "936643273", "2"], lambda c: W.recently_not_found(c, led))
    assert todo == ["1", "2"]


def test_loop_continues_on_not_found_and_stops_otherwise():
    src = (HERE / "psa_cache_warm.py").read_text(encoding="utf-8")
    i = src.index("kind = failure_kind(driver.page_source)")
    block = src[i:i + 900]
    assert 'if kind == "not_found":' in block and "continue" in block
    assert "break" in block, "Cloudflare / 分からない時に止めていない"
