# -*- coding: utf-8 -*-
"""`item:` の古い KEY はカタログの KEY に入れ替える (2026-09-12)。

実害: 目視の画面は `item:m…` の行を「KEY が無い」として出していたのに、KEY を書く道具は
「値が入っているから触らない」で飛ばしていた。**目視しても何も書かれない**。
出品済み 79行のうち 57行がこの状態だった。判定は `ut_catalog_values.needs_catalog_key` 1か所。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_catalog_values as V  # noqa: E402
import ut_key_backfill as B  # noqa: E402
import ut_identify as I  # noqa: E402


def test_predicate():
    assert V.needs_catalog_key("") is True
    assert V.needs_catalog_key("   ") is True
    assert V.needs_catalog_key("item:m39740000141") is True
    assert V.needs_catalog_key("shops:abc123") is True
    assert V.needs_catalog_key("uniqlo_ut:480691:BLUE:2XL") is False
    assert V.needs_catalog_key("PSA10-12345678") is False


def test_screen_and_writer_agree():
    """画面が「出す」と言った行は、書く側も「書く」と言うこと。"""
    for val in ("", "item:m39740000141", "shops:x1", "uniqlo_ut:480691:BLUE:2XL"):
        r = [""] * 40
        r[I.C_KEY] = val
        assert I._needs_key(r) == V.needs_catalog_key(val), val


def _row(key_val):
    r = [""] * 40
    r[B.COL_URL] = "https://jp.mercari.com/item/m39740000141"
    r[B.COL_ITEMID] = "358000000001"
    r[B.COL_CAT] = "Tシャツ"
    r[B.COL_SIZE] = "L"
    r[B.COL_KEY] = key_val
    return r


def test_backfill_replaces_supply_key_but_not_catalog_key():
    ledger = {"https://jp.mercari.com/item/m39740000141":
              {"decision": "go", "product_id": "E480691-000", "color": "BLUE", "size": "L"}}
    rows_supply = [[""] * 40, _row("item:m39740000141")]
    assert len(B.plan(rows_supply, ledger)) == 1, "item: の行が書かれない"
    rows_done = [[""] * 40, _row("uniqlo_ut:480691:BLUE:L")]
    assert B.plan(rows_done, ledger) == [], "カタログの KEY を上書きしている"
