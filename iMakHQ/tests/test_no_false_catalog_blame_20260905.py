# -*- coding: utf-8 -*-
"""カタログに言いがかりの修正依頼が飛んでいた件 (2026-09-05)。

9/5 18:20 の PSA再仕入れ①で、Google スプレッドシートの読取が上限 (429) に当たって失敗した。

    ⚠ canonical KEY map 取得失敗 (APIError [429] Quota exceeded) — bare番号で続行

その結果 84件すべてが「card番号なし・KEYなし」で目視ゲートに出て、外した分が
catalog の誤りとして 39件の修正依頼になった。**うち29件は card番号が空** =
catalog を引きにすら行っていない行だった (= catalog の誤りと言える根拠が無い)。

原因は3つ:
  1. 目視画面の「外した理由」select が CSS の指定ミスで **一度も表示されていなかった**
     (`.cand:has(...)` は候補ピッカー用。事前ゲートの select は `.card` 直下)
  2. その select の先頭が `catalog` で既定選択 → 触らないと全部カタログのせいになる
  3. card番号が空の行を依頼書に載せていた (2026-09-01 に画面表示だけ言い分けた)
  4. シートを読めなかった走行でも、そのまま依頼書を書いていた (fail-open)
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_mismatch_pdca as P  # noqa: E402

_CONFIRM_SRC = open(os.path.join(_TOOLS, "psa_resource_confirm.py"), encoding="utf-8").read()
_GATE_SRC = open(os.path.join(_TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()


# ---------------------------------------------- 1. 理由欄が画面に出る

def test_reason_select_is_visible_when_unchecked():
    """事前ゲートの理由欄に CSS の出し口がある (`.card.off > .rsn`)。"""
    assert ".card.off > .rsn{display:" in _CONFIRM_SRC


# ---------------------------------------------- 2. 既定で catalog を選ばない

def test_reason_select_has_no_default_blame():
    """先頭は空。触らないとカタログのせいになる状態を作らない。"""
    i = _CONFIRM_SRC.index("rsn = (")
    blk = _CONFIRM_SRC[i:i + 900]
    first = blk.index("<option value=")
    assert blk[first:].startswith("<option value=''>"), blk[first:first + 60]
    # 空 → catalog の順 (catalog が先頭に戻っていない)
    assert blk.index("<option value=''>") < blk.index("<option value='catalog'>")


def test_submit_is_blocked_when_reason_is_unset():
    """理由が空のまま確定させない。"""
    assert "if(!r){ unset++;" in _CONFIRM_SRC
    assert "外した理由が未選択の行が" in _CONFIRM_SRC


# ---------------------------------------------- 3. 番号が空の行は catalog に回さない

def _row(card_no, reason="catalog", status="未対処"):
    return {"status": status, "原因": reason, "card_no": card_no}


def test_rows_without_card_number_never_reach_catalog():
    """番号が空 = catalog を引いていない = 誤りと言えない。9/5 の29件がこれ。"""
    ledger = [_row("OP01-001"), _row(""), _row("   ")]
    b = P.route_buckets(ledger)
    assert len(b.get("catalog") or []) == 1
    assert len(b.get("no_cardno") or []) == 2
    assert "no_cardno" in P.ROUTE_LABEL


def test_other_routes_are_untouched():
    """cert / listing の振り分けは変えていない。"""
    ledger = [_row("", reason="cert"), _row("", reason="listing")]
    b = P.route_buckets(ledger)
    assert len(b.get("cert") or []) == 1
    assert len(b.get("listing") or []) == 1
    assert not b.get("no_cardno")


def test_resolved_rows_are_still_skipped():
    ledger = [_row("", status="解決")]
    assert P.route_buckets(ledger) == {}


# ---------------------------------------------- 4. シートが読めない時は依頼を書かない

def test_gate_does_not_write_catalog_request_when_sheet_read_failed():
    assert "SHEET_READ_OK = True" in _GATE_SRC
    assert "SHEET_READ_OK = False" in _GATE_SRC
    assert "if cat and not SHEET_READ_OK:" in _GATE_SRC
