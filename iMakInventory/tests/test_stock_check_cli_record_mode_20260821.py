"""stock_check_cli 「待たない / 記録を返す / 黙らない」の回帰 test (2026-08-21).

事故: この CLI は一度も成功したことが無かった。既定が「実ブラウザで今すぐ見に行く」で、
巡回 lock を既定 10 分 無言で待つ設計だったため。巡回は 1 回 2〜3 時間走るので 10 分では
絶対に空かず、毎回「600 秒沈黙 → 全件 判定不能」になっていた (= 設計どおりの結果)。

回答書 `2026-08-20_stock_check_cli_hang_response.md` の決定 3 点を固定する:
  1. 既定は待たない (0 分)。lock 保持中は即座に理由 (巡回の開始時刻つき) を出して終わる
  2. 既定の動作は「巡回が既に書いた記録 + それを取得した時刻」を返す。--live の時だけ実取得
  3. 出力をバッファしない / --json は途中で殺されても空にならない
  + --live の chrome 起動に上限 (uc.Chrome() は自前 timeout を持たない = 踏むと無限待ち)

不変条件は旧 test と同じ: **判定不能を sold に混ぜない**。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import stock_check_cli as cli  # noqa: E402

MERCARI_URL = "https://jp.mercari.com/item/m10050701525"
SNKR_URL = "https://snkrdunk.com/apparels/100561/used/47548295"
BACKUP_URL = "https://jp.mercari.com/item/m99999999999"


def _write_log(dirpath: Path, name: str, rows: list, mtime: float):
    """decision_log の巡回記録 (listings_<label>_<ts>.jsonl) を 1 本作る."""
    p = dirpath / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def logs(tmp_path, monkeypatch):
    """新しい記録 (在庫あり) と古い記録 (売切) を持つ decision_log を作る."""
    d = tmp_path / "decision_log"
    d.mkdir()
    now = time.time()
    _write_log(d, "listings_SHEET_20260820_000000.jsonl", [
        {"ts": "2026-08-20T00:00:00", "url": MERCARI_URL, "is_sold": True, "error": None,
         "sub_results": []},
    ], now - 7200)
    _write_log(d, "listings_SHEET_20260821_120000.jsonl", [
        {"ts": "2026-08-21T12:00:00", "url": MERCARI_URL, "is_sold": False, "error": None,
         "sub_results": [{"url": BACKUP_URL, "is_sold": True, "error": None}]},
        {"ts": "2026-08-21T12:00:00", "url": SNKR_URL, "is_sold": None,
         "error": "scraper returned None (fail-closed)", "sub_results": []},
    ], now - 60)
    monkeypatch.setattr(cli, "DECISION_LOG_DIR", d)
    return d


# ---------------------------------------------------------------- 1. 待たない
def test_default_never_waits():
    """既定の待ち上限は 0 分。10 分の無言待ちに戻さないこと (これが不具合の本体だった)."""
    assert cli.LOCK_WAIT_MINUTES == 0


def test_lock_held_returns_immediately_without_sleeping():
    """lock 保持中でも sleep せず即 False (待っても 2〜3 時間空かないので待つ意味が無い)."""
    with patch.object(cli, "_lock_state", return_value=(True, None)), \
         patch.object(cli.time, "sleep", side_effect=AssertionError("待ってはいけない")):
        assert cli._wait_for_cycle_lock(0) is False


def test_lock_reason_names_the_cycle_start_time():
    """無言にしない: 巡回中である事・開始時刻・所要目安を必ず文面に出す."""
    from datetime import datetime
    started = datetime(2026, 8, 21, 16, 23, 11)
    with patch.object(cli, "_lock_state", return_value=(True, started)):
        msg = cli._lock_reason(0)

    assert "巡回" in msg and "16:23" in msg and cli.CYCLE_TYPICAL in msg


def test_live_during_cycle_is_all_unknown_never_sold():
    """★ 巡回中の --live は全件 unknown。偽 sold を 1 件も作らない."""
    with patch.object(cli, "_wait_for_cycle_lock", return_value=False), \
         patch.object(cli, "_lock_state", return_value=(True, None)):
        out = cli.check_urls([MERCARI_URL, SNKR_URL], wait_minutes=0)

    assert [r["status"] for r in out] == ["unknown", "unknown"]
    assert all("巡回" in r["reason"] for r in out)


# ------------------------------------------------------- 2. 記録を返す (既定)
def test_record_returns_latest_value_and_when_it_was_taken(logs):
    """新しい記録が勝つ + 取得時刻を返す (古い売切に引きずられない)."""
    out = cli.read_recorded([MERCARI_URL])

    assert out[0]["status"] == "in_stock"          # 新しい記録 (12:00) が勝つ
    assert out[0]["checked_at"] == "2026-08-21T12:00:00"
    assert out[0]["source"] == "record"
    assert out[0]["age_minutes"] is not None       # 「いつの値か」が呼出側に伝わる


def test_record_never_opens_a_browser(logs):
    """記録モードは巡回中でも答えられること (driver も lock 待ちも使わない)."""
    with patch.object(cli, "_wait_for_cycle_lock", side_effect=AssertionError("lock を見るな")), \
         patch.object(cli, "_create_mercari_driver", side_effect=AssertionError("chrome を開くな")):
        out = cli.read_recorded([MERCARI_URL])

    assert out[0]["status"] == "in_stock"


def test_record_matches_backup_url_in_sub_results(logs):
    """補 URL (sub_results) も記録として引ける."""
    out = cli.read_recorded([BACKUP_URL])

    assert out[0]["status"] == "sold"
    assert out[0]["checked_at"] == "2026-08-21T12:00:00"


def test_record_ignores_query_string(logs):
    """同じ商品ページなら query 違いでも引ける (HQ 側の URL は afid 等が付くことがある)."""
    out = cli.read_recorded([MERCARI_URL + "?afid=123"])

    assert out[0]["status"] == "in_stock"


def test_record_missing_is_unknown_not_in_stock(logs):
    """記録が無い URL を「在庫あり」に倒さない (推測で出品させない = fail-closed)."""
    out = cli.read_recorded(["https://jp.mercari.com/item/m00000000000"])

    assert out[0]["status"] == "unknown"
    assert out[0]["reason"]


def test_record_keeps_unknown_as_unknown(logs):
    """巡回が判定不能だったものは unknown のまま返す (理由つき)."""
    out = cli.read_recorded([SNKR_URL])

    assert out[0]["status"] == "unknown"
    assert "fail-closed" in out[0]["reason"]


def test_record_keeps_input_order_and_duplicates(logs):
    """入力行と 1:1 (呼出側が行番号で突き合わせられる)."""
    out = cli.read_recorded([SNKR_URL, MERCARI_URL, SNKR_URL])

    assert [r["url"] for r in out] == [SNKR_URL, MERCARI_URL, SNKR_URL]
    assert [r["status"] for r in out] == ["unknown", "in_stock", "unknown"]


def test_record_ignores_test_logs(tmp_path, monkeypatch):
    """test の生成物 (listings_TEST_*) を実記録として読まない."""
    d = tmp_path / "decision_log"
    d.mkdir()
    _write_log(d, "listings_TEST_20260821_180000.jsonl", [
        {"ts": "2026-08-21T18:00:00", "url": MERCARI_URL, "is_sold": False, "error": None},
    ], time.time())
    monkeypatch.setattr(cli, "DECISION_LOG_DIR", d)

    assert cli.read_recorded([MERCARI_URL])[0]["status"] == "unknown"


def test_main_defaults_to_record_mode(logs, tmp_path):
    """既定 (--live なし) は記録モード。lock も chrome も触らない."""
    out_json = tmp_path / "out.json"
    argv = ["stock_check_cli", "--url", MERCARI_URL, "--json", str(out_json)]
    with patch.object(sys, "argv", argv), \
         patch.object(cli, "check_urls", side_effect=AssertionError("live を呼ぶな")):
        rc = cli.main()

    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data[0]["status"] == "in_stock" and data[0]["source"] == "record"


def test_main_live_flag_uses_browser_path(logs, tmp_path):
    """--live を明示した時だけ実取得に行く."""
    argv = ["stock_check_cli", "--url", MERCARI_URL, "--live"]
    with patch.object(sys, "argv", argv), \
         patch.object(cli, "check_urls", return_value=[
             {"url": MERCARI_URL, "status": "sold", "source": "live",
              "checked_at": "2026-08-21T18:00:00", "age_minutes": 0}]) as live:
        rc = cli.main()

    assert rc == 0 and live.called


# --------------------------------------------- 3. 黙らない / JSON を空にしない
def test_output_is_flushed_line_by_line():
    """走行中も 1 行ずつ出す (ブロックバッファリングで 0 バイト沈黙しない)."""
    with patch("builtins.print") as pr:
        cli._out("x")

    assert pr.call_args.kwargs.get("flush") is True


def test_json_is_written_per_result_and_stays_valid(tmp_path):
    """途中で殺されても、そこまでの結果が完全な JSON で残る (空にならない)."""
    out_json = tmp_path / "out.json"
    seen = {"n": 0}

    def fake_check(url, sleep_sec, mercari_driver, amazon_driver, *a, **kw):
        seen["n"] += 1
        if seen["n"] == 3:
            raise KeyboardInterrupt      # ここで殺された相当
        return {"is_sold": True, "error": None}

    argv = ["stock_check_cli", "--live", "--json", str(out_json),
            "--url", SNKR_URL, "--url", SNKR_URL + "/2", "--url", SNKR_URL + "/3"]
    with patch.object(sys, "argv", argv), \
         patch.object(cli, "_wait_for_cycle_lock", return_value=True), \
         patch("monitor_listings._check_single_url", side_effect=fake_check), \
         patch.object(cli, "_create_mercari_driver", return_value=(None, None)), \
         pytest.raises(KeyboardInterrupt):
        cli.main()

    data = json.loads(out_json.read_text(encoding="utf-8"))   # 壊れた JSON でないこと
    assert len(data) == 2 and all(r["status"] == "sold" for r in data)


# --------------------------------------- 4. --live の chrome 起動に上限を付ける
def test_driver_start_has_an_upper_bound():
    """uc.Chrome() が返ってこない時に無限待ちしない (踏むと CLI ごと固まる)."""
    def hang(*a, **kw):
        time.sleep(30)

    t0 = time.time()
    with patch("monitor_listings.create_mercari_driver", side_effect=hang):
        drv, err = cli._create_mercari_driver(timeout_sec=1)
    elapsed = time.time() - t0

    assert drv is None and err and "起動" in err
    assert elapsed < 15      # 上限で切れている (30 秒待っていない)


def test_driver_start_error_is_reported_not_swallowed():
    """起動失敗を握り潰さない (呼出側が理由を出せる)."""
    with patch("monitor_listings.create_mercari_driver",
               side_effect=RuntimeError("cannot connect to chrome")):
        drv, err = cli._create_mercari_driver(timeout_sec=5)

    assert drv is None and "cannot connect to chrome" in err
