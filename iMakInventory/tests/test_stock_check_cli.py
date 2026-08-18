"""stock_check_cli の test (HQ 入稿前ゲート用 CLI).

守るべき性質は 1 つに尽きる: **判定不能を sold に混ぜない**。
sold と返した URL は HQ 側で入稿CSVから物理的に落とされるので、偽 sold は
「出せたはずの商品を捨てる」= 機会損失に直結する (逆に unknown は警告止まりで安全)。

軸:
  1. is_sold True/False/None → sold / in_stock / unknown の 1:1 写像
  2. unknown には必ず reason が付く (HQ の切り分け用)
  3. 巡回 lock 保持中 → 全件 unknown (sold を 1 件も作らない)
  4. 入力ゼロ → 空リスト (driver を起こさない)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import stock_check_cli  # noqa: E402

MERCARI_URL = "https://jp.mercari.com/item/m10050701525"
SHOPS_URL = "https://jp.mercari.com/shops/product/2JKUSFCwhvXq69wxkrWZuG"
SNKR_URL = "https://snkrdunk.com/apparels/100561/used/47548295"


def _run(urls, sub_by_url):
    """_check_single_url を差し替えて check_urls を回す (lock は空いている前提)."""
    def fake_check(url, sleep_sec, mercari_driver, amazon_driver, *a, **kw):
        return sub_by_url[url]

    with patch.object(stock_check_cli, "_wait_for_cycle_lock", return_value=True), \
         patch("monitor_listings._check_single_url", side_effect=fake_check), \
         patch("monitor_listings.create_mercari_driver", return_value=None):
        return stock_check_cli.check_urls(urls)


def test_three_way_mapping():
    """True→sold / False→in_stock / None→unknown。混線しないこと。"""
    subs = {
        MERCARI_URL: {"is_sold": True, "error": None},
        SHOPS_URL: {"is_sold": False, "error": None},
        SNKR_URL: {"is_sold": None, "error": "scraper returned None (fail-closed)"},
    }
    out = _run([MERCARI_URL, SHOPS_URL, SNKR_URL], subs)

    assert [r["status"] for r in out] == ["sold", "in_stock", "unknown"]
    assert [r["url"] for r in out] == [MERCARI_URL, SHOPS_URL, SNKR_URL]  # 入力順を保持
    assert all(r["checked_at"] for r in out)


def test_unknown_carries_reason():
    """unknown には理由が必ず付く (HQ が切り分けに使う)."""
    subs = {SNKR_URL: {"is_sold": None, "error": "in_stock indeterminate"}}
    out = _run([SNKR_URL], subs)

    assert out[0]["status"] == "unknown"
    assert out[0]["reason"] == "in_stock indeterminate"


def test_unknown_reason_never_empty_even_if_error_missing():
    """error が空でも reason を空にしない (無言の unknown を作らない)."""
    subs = {SNKR_URL: {"is_sold": None, "error": None}}
    out = _run([SNKR_URL], subs)

    assert out[0]["reason"]


def test_sold_and_in_stock_have_no_reason_key():
    """確定した結果に reason を付けない (HQ 側の分岐を単純に保つ)."""
    subs = {MERCARI_URL: {"is_sold": True, "error": None},
            SNKR_URL: {"is_sold": False, "error": None}}
    out = _run([MERCARI_URL, SNKR_URL], subs)

    assert "reason" not in out[0]
    assert "reason" not in out[1]


def test_cycle_running_returns_all_unknown_not_sold():
    """★ 巡回と重なって判定できない時、sold を 1 件も作らないこと.

    巡回は開始時に chrome を一括 kill するので、重なると driver が落ちる。
    そこで「落ちた=売切」に倒すと偽 sold の量産になる (2026-07-25 snkrdunk 事故と同型)。
    """
    with patch.object(stock_check_cli, "_wait_for_cycle_lock", return_value=False):
        out = stock_check_cli.check_urls([MERCARI_URL, SNKR_URL], wait_minutes=0)

    assert [r["status"] for r in out] == ["unknown", "unknown"]
    assert all("巡回" in r["reason"] for r in out)


def test_empty_input_returns_empty():
    """URL ゼロ件で driver を起こさない (無駄な chrome 起動をしない)."""
    with patch.object(stock_check_cli, "_wait_for_cycle_lock") as wait:
        assert stock_check_cli.check_urls([]) == []
        wait.assert_not_called()


def test_read_urls_skips_comments_and_blanks(tmp_path):
    """--urls ファイルの # 行と空行を無視する."""
    f = tmp_path / "urls.txt"
    f.write_text(f"# comment\n{MERCARI_URL}\n\n  {SNKR_URL}  \n", encoding="utf-8")

    class Args:
        urls = str(f)
        url = None

    assert stock_check_cli._read_urls(Args()) == [MERCARI_URL, SNKR_URL]
