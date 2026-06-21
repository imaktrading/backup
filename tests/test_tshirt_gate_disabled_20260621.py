"""Regression: 2026-06-21 — Tシャツ(UNIQLO UT)の価格NO-GO見送りを廃止.

背景:
  UNIQLO UT 4件が全て 🟠 HOLD(価格ALERT: 当社$49-62 vs 中央値$32-35 = +50〜97%超過)→ 0出品。
  ユーザー指示「価格NO-GO見送りをやめて。全て出品で」。無在庫=cost-plus は損なし、高めは
  既存メンテで追跡する方針(TCG 本丸=価格NO-GO廃止と同方針)。

修正:
  listing_common.PRICE_CHECK_CONFIG["tshirt"] を False に変更。
  → audit_csv_row 内の price ALERT → error 化を skip → HOLD されず CSV に残る(=出品)。
  → ALERT は compute_listing_price で warning として print 継続(可視性は維持)。
  物理ゲート(Item Specifics 必須/長さ/whitelist 等)は従来どおり error で HOLD(誤出品防止は不変)。
"""
from __future__ import annotations
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def test_tshirt_disabled_in_config():
    from listing_common import PRICE_CHECK_CONFIG
    assert PRICE_CHECK_CONFIG.get("tshirt", {}).get("enabled") is False


def test_tshirt_alert_not_gated():
    """tshirt の価格ALERTは error 化されない(=CSVに残る=出品される)。"""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "UNIQLO UT One Piece 25th Luffy Gear Second T-Shirt Black US L NWT Japan New",
        "*Category": "15687",
        "*StartPrice": "61.98",
        "ConditionID": "1000",
    }
    violations = audit_csv_row(row_data, category="tshirt",
                               price_status="ALERT", median_usd=31.50)
    price_errors = [v for v in violations if v[0] == "*StartPrice" and v[2] == "error"
                    and "exceeds market" in v[1]]
    assert price_errors == [], f"tshirt price ALERT should NOT gate, got: {price_errors}"
