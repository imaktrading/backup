#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RESTOCK視覚確証: 確定済を再表示しない + 上書きで既存を消さない (2026-06-22)。

ユーザー要望: RESTOCK視覚確証で同じ11件(うち再出品済6)が毎回出て同じ確証作業の繰り返しが面倒。
+ 発覚した上書きバグ: _run_restock_confirm が RESTOCK確定タブを毎回 replace で書くため、新規5件だけ
確証すると既存12件(実行済)が消える。
対策: ① 既にRESTOCK確定済の itemID は視覚確証に出さない ② 書込は既存+新規のマージ。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
# psa_resource_gate は重い import 群を持つので、純関数だけ取り出してテスト
import importlib.util
_P = os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py")
_spec = importlib.util.spec_from_file_location("psa_resource_gate", _P)
# 依存の重い import を避けるため、関数定義だけ読む手段が無いので通常 import を試みる
try:
    g = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(g)
    _LOADED = True
except Exception:
    _LOADED = False

import pytest

pytestmark = pytest.mark.skipif(not _LOADED, reason="psa_resource_gate import 不可環境")

HEADER = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定",
          "確認済仕入URL", "ebay_url", "確証日"]


def test_confirmed_iids_extracts_existing():
    existing = [HEADER,
                ["111", "OP09-062", "t", "", "", "", "", "", "", "2026-06-20"],
                ["222", "OP07-051", "t", "", "", "", "", "", "", "2026-06-20"]]
    assert g._restock_confirmed_iids(existing) == {"111", "222"}


def test_confirmed_iids_empty():
    assert g._restock_confirmed_iids([]) == set()
    assert g._restock_confirmed_iids([HEADER]) == set()


def test_merge_keeps_existing_and_adds_new():
    """既存12件相当を維持しつつ新規を追加(上書きで消えない)。"""
    existing = [HEADER + ["RESTOCK状態", "状態確認日"],
                ["111", "A", "t", "", "", "", "", "", "", "2026-06-20", "実行済(qty復活)", "2026-06-20"]]
    new = [["999", "B", "t2", "", "", "", "", "", "", "2026-06-22"]]
    out = g._merge_restock_out(existing, new, HEADER)
    iids = [r[0] for r in out[1:]]
    assert "111" in iids, "既存(実行済)が消えていない"
    assert "999" in iids, "新規が追加されている"
    assert out[0] == existing[0], "既存ヘッダ(状態列含む)を維持"


def test_merge_new_overrides_duplicate():
    """同 itemID は新規優先(重複しない)。"""
    existing = [HEADER, ["111", "A", "old", "", "", "", "", "", "", "2026-06-20"]]
    new = [["111", "A", "new", "", "", "", "", "", "", "2026-06-22"]]
    out = g._merge_restock_out(existing, new, HEADER)
    rows = [r for r in out[1:] if r[0] == "111"]
    assert len(rows) == 1, "itemID重複しない"
    assert rows[0][2] == "new", "新規が優先"


def test_merge_empty_existing_uses_default_header():
    out = g._merge_restock_out([], [["111", "A", "t", "", "", "", "", "", "", "2026-06-22"]], HEADER)
    assert out[0] == HEADER
    assert out[1][0] == "111"


# --- レビュー済(違う/見送り)を再表示しない (2026-06-22 追加) ---
SKIP_H = ["itemID", "card_no", "title", "理由", "日付", "ebay_url"]


def test_review_skip_iids():
    rows = [SKIP_H, ["111", "P-041", "t", "違う", "2026-06-22", ""],
            ["222", "ST29-001", "t", "見送り", "2026-06-22", ""]]
    assert g._review_skip_iids(rows) == {"111", "222"}
    assert g._review_skip_iids([]) == set()


def test_build_review_skip_rows_classifies_reason():
    """shown - confirmed = 違う(diff_idxs)/見送り(それ以外)。"""
    cands = [{"itemID": "111", "card_no": "P-041", "title": "t1", "ebay_url": "u1"},
             {"itemID": "222", "card_no": "ST29-001", "title": "t2", "ebay_url": "u2"},
             {"itemID": "333", "card_no": "EB02-015", "title": "t3", "ebay_url": "u3"}]
    shown = {0, 1, 2}
    confirmed = {2}          # 333 は確証 → skip対象外
    diff = {0}               # 111 は違う
    out = g._build_review_skip_rows(cands, shown, confirmed, diff, "2026-06-22")
    by_iid = {r[0]: r for r in out}
    assert set(by_iid) == {"111", "222"}, "確証(333)は記録しない"
    assert by_iid["111"][3] == "違う"
    assert by_iid["222"][3] == "見送り"


def test_build_review_skip_skips_empty_itemid():
    cands = [{"itemID": "", "card_no": "x", "title": "t", "ebay_url": ""}]
    assert g._build_review_skip_rows(cands, {0}, set(), set(), "2026-06-22") == []


def test_review_skip_cooldown_is_next_day():
    """2026-07-29: 期限なしで永久に伏せていた → **翌日には再確証に戻す**。

    RESTOCK は売れた後の再仕入れなので、埋もれると直接 機会損失になる。
    「違う」の主因の一つは *その日* 正変種が売られていないことなので、時間で解決する。
    """
    rows = [SKIP_H, ["111", "P-041", "t", "違う", "2026-07-29", ""]]
    assert g._review_skip_iids(rows, today="2026-07-29") == {"111"}   # 同日 = 伏せる
    assert g._review_skip_iids(rows, today="2026-07-30") == set()     # 翌日 = 復帰
    assert g._review_skip_iids(rows) == {"111"}                       # today 省略 = 従来動作


def test_review_skip_unparseable_date_stays_hidden():
    """日付が読めない行は伏せたまま (判定材料なしの再表示は毎回同じものが出る)。"""
    rows = [SKIP_H, ["111", "P-041", "t", "違う", "", ""],
            ["222", "P-042", "t", "違う", "こわれ", ""]]
    assert g._review_skip_iids(rows, today="2026-07-30") == {"111", "222"}


def test_restock_shares_negative_examples_with_hoju():
    """RESTOCK の「違う」も **補URL側と同じ台帳**に貯め、両方で効かせること (2026-07-30)。

    実測: 1走行で9件の「違う」が記録だけされて次回また同じ候補が出ていた
    (人の9クリックが捨てられていた)。同じ出品×同じURLの判断は共有すべき。
    """
    src = (Path(__file__).parent.parent / "tools" / "psa_resource_gate.py").read_text(encoding="utf-8")
    assert "_hf.NG_CAND_TAB" in src, "違うを候補NG台帳に記録していない"
    assert "filter_candidates_rejected" in src, "記録した違うを表示前に除外していない"
    assert "_merge_ng_rows" in src, "台帳を上書きしている (追記でないと過去の判断が消える)"


def test_merge_skip_rows_keeps_and_dedups():
    existing = [SKIP_H, ["111", "P-041", "t", "違う", "2026-06-20", ""]]
    new = [["222", "ST29-001", "t", "見送り", "2026-06-22", ""],
           ["111", "P-041", "t", "見送り", "2026-06-22", ""]]  # 111 更新
    out = g._merge_skip_rows(existing, new, SKIP_H)
    by_iid = {r[0]: r for r in out[1:]}
    assert set(by_iid) == {"111", "222"}
    assert by_iid["111"][3] == "見送り", "新規優先で更新"
