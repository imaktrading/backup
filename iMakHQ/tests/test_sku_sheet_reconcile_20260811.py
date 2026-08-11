# -*- coding: utf-8 -*-
"""SKU 詳細シート ↔ eBay Variation 突合 dry-run の判定ロジック (2026-08-11)。

回答書: 2026-08-11_inventory_sku_sheet_duplicate_rows_conflict_response.md

処理ルール (12 組も残り 44 組も同じ、例外なし):
  1. UUID 一致 + 表記一致           → keep
  2. UUID 一致 + 表記不一致          → retire_mismatch (廃止候補)
  3. eBay に UUID 無し               → retire_orphan  (廃止候補)
  4. 同 UUID 二重登録 + 両方一致     → 新しい方 keep、古い方 retire_dup_older
  5. dry-run: シートは 1 セルも変更しない
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")

import sku_sheet_reconcile as R  # noqa: E402


# ---------------------------------------------------------------------------
# ヘルパ: SKU 詳細タブの行を作る (列 A-L)
# ---------------------------------------------------------------------------
def make_row(*, listing_id, uuid, size, color, updated_at="2026-08-01"):
    row = [""] * 12
    row[R.SKU_COL_LISTING_ID] = listing_id
    row[R.SKU_COL_UUID] = uuid
    row[R.SKU_COL_SIZE] = size
    row[R.SKU_COL_COLOR] = color
    row[R.SKU_COL_CHK_DATE] = updated_at
    return row


# ---------------------------------------------------------------------------
# 1. UUID 一致 + 表記一致 = keep
# ---------------------------------------------------------------------------
def test_uuid_match_and_size_color_match_keeps_row():
    rows = [make_row(listing_id="358275199203", uuid="165c348f",
                     size="L-R", color="LBL")]
    truth = {"358275199203": {"165c348f": ("L-R", "LBL")}}
    result = R.reconcile_rows(rows, truth)
    assert result["summary"]["keep"] == 1
    assert result["decisions"][0]["decision"] == "keep"


def test_uuid_match_case_insensitive_and_whitespace_tolerant():
    """UUID / size / color は正規化 (前後空白除去 + lower) して突合。"""
    rows = [make_row(listing_id="358275199203", uuid=" 165C348F ",
                     size=" L-R ", color=" lbl ")]
    truth = {"358275199203": {"165c348f": ("L-R", "LBL")}}
    result = R.reconcile_rows(rows, truth)
    assert result["decisions"][0]["decision"] == "keep"


# ---------------------------------------------------------------------------
# 2. UUID 一致 + 表記不一致 = retire_mismatch (実例: montbell L vs L-R)
# ---------------------------------------------------------------------------
def test_montbell_l_vs_lr_flagged_as_mismatch():
    """回答書 12 組の中核: eBay=`JP L-R` を sheet が `L` と記録 → 古い行。"""
    rows = [
        make_row(listing_id="358275199203", uuid="165c348f",  # eBay 真実 = L-R
                 size="L", color="LBL"),                       # sheet 古い記録
    ]
    truth = {"358275199203": {"165c348f": ("L-R", "LBL")}}
    result = R.reconcile_rows(rows, truth)
    assert result["decisions"][0]["decision"] == "retire_mismatch"
    assert "表記不一致" in result["decisions"][0]["reason"]


def test_color_mismatch_also_flags_retire_mismatch():
    rows = [make_row(listing_id="1", uuid="aaa11111",
                     size="M", color="LBL")]
    truth = {"1": {"aaa11111": ("M", "RED")}}
    result = R.reconcile_rows(rows, truth)
    assert result["decisions"][0]["decision"] == "retire_mismatch"


# ---------------------------------------------------------------------------
# 3. eBay に UUID 無し = retire_orphan
# ---------------------------------------------------------------------------
def test_uuid_missing_from_ebay_flagged_as_orphan():
    rows = [make_row(listing_id="1", uuid="deadbeef", size="M", color="RED")]
    truth = {"1": {"aaa11111": ("M", "RED")}}
    result = R.reconcile_rows(rows, truth)
    assert result["decisions"][0]["decision"] == "retire_orphan"
    assert "存在しない" in result["decisions"][0]["reason"]


def test_listing_id_not_fetched_treats_all_as_orphan():
    """GetItem できなかった listing (truth に entry 無し) は全 UUID を orphan 扱い。"""
    rows = [make_row(listing_id="1", uuid="aaa11111", size="M", color="RED")]
    truth = {}
    result = R.reconcile_rows(rows, truth)
    assert result["decisions"][0]["decision"] == "retire_orphan"


# ---------------------------------------------------------------------------
# 4. 同 UUID 二重登録 + 両方一致 = 古い方が retire_dup_older
# ---------------------------------------------------------------------------
def test_dup_older_row_retired_when_both_match():
    rows = [
        make_row(listing_id="1", uuid="aaa11111", size="M", color="RED",
                 updated_at="2026-07-01"),
        make_row(listing_id="1", uuid="aaa11111", size="M", color="RED",
                 updated_at="2026-08-10"),
    ]
    truth = {"1": {"aaa11111": ("M", "RED")}}
    result = R.reconcile_rows(rows, truth)
    by_date = {d["updated_at"]: d["decision"] for d in result["decisions"]}
    assert by_date["2026-08-10"] == "keep"
    assert by_date["2026-07-01"] == "retire_dup_older"
    assert result["summary"]["keep"] == 1
    assert result["summary"]["retire_dup_older"] == 1


def test_dup_older_only_triggers_when_both_actually_match():
    """一方が mismatch なら retire_dup_older 判定は起こさず、mismatch 判定を維持。"""
    rows = [
        make_row(listing_id="1", uuid="aaa11111", size="M", color="RED"),   # match
        make_row(listing_id="1", uuid="aaa11111", size="XL", color="RED"),  # mismatch
    ]
    truth = {"1": {"aaa11111": ("M", "RED")}}
    result = R.reconcile_rows(rows, truth)
    decisions = sorted([d["decision"] for d in result["decisions"]])
    assert decisions == ["keep", "retire_mismatch"]
    assert result["summary"]["retire_dup_older"] == 0


# ---------------------------------------------------------------------------
# 5. dry-run: シートを触るコードが無いこと (invariant)
# ---------------------------------------------------------------------------
def test_module_never_calls_sheet_update_or_delete():
    """静的検査: 削除/書換 API を呼んでいないことを担保。"""
    src_path = os.path.join(r"C:\dev\iMak\iMakHQ\tools", "sku_sheet_reconcile.py")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    for banned in ("delete_row", "delete_rows", "clear(",
                   "update_cell", "batch_clear", "batch_update",
                   ".update("):
        assert banned not in src, (
            f"dry-run tool が書換系 API を呼んでいる: {banned} を消すこと"
        )


# ---------------------------------------------------------------------------
# 6. GetItem XML パース (実 XML 形状の回帰)
# ---------------------------------------------------------------------------
_SAMPLE_GETITEM = """
<GetItemResponse>
  <Item>
    <Variations>
      <Variation>
        <SKU>165c348f-xxxx-yyyy</SKU>
        <StartPrice currencyID="USD">45.00</StartPrice>
        <VariationSpecifics>
          <NameValueList><Name>Sizes</Name><Value>JP L-R</Value></NameValueList>
          <NameValueList><Name>Color</Name><Value>LBL</Value></NameValueList>
        </VariationSpecifics>
      </Variation>
      <Variation>
        <SKU>2c52d2ca</SKU>
        <VariationSpecifics>
          <NameValueList><Name>Sizes</Name><Value>JP M-R</Value></NameValueList>
          <NameValueList><Name>Color</Name><Value>BLK</Value></NameValueList>
        </VariationSpecifics>
      </Variation>
    </Variations>
  </Item>
</GetItemResponse>
"""


def test_parse_variation_truth_from_getitem_shape():
    truth = R.parse_variation_truth_from_getitem(_SAMPLE_GETITEM)
    # 8桁短縮 も full も、norm 後に同じ規則で扱う
    assert "165c348f-xxxx-yyyy" in truth or "2c52d2ca" in truth
    # short SKU
    assert truth["2c52d2ca"] == ("JP M-R", "BLK")


def test_parse_variation_truth_missing_specifics_are_empty_strings():
    xml = "<Variation><SKU>abc12345</SKU></Variation>"
    truth = R.parse_variation_truth_from_getitem(xml)
    assert truth["abc12345"] == ("", "")


# ---------------------------------------------------------------------------
# 7. サマリ数値
# ---------------------------------------------------------------------------
def test_summary_counts_each_bucket():
    rows = [
        make_row(listing_id="1", uuid="aaaaaaaa", size="M", color="R"),   # keep
        make_row(listing_id="1", uuid="bbbbbbbb", size="X", color="R"),   # mismatch
        make_row(listing_id="1", uuid="cccccccc", size="X", color="R"),   # orphan
        make_row(listing_id="1", uuid="dddddddd", size="M", color="R", updated_at="2026-07-01"),
        make_row(listing_id="1", uuid="dddddddd", size="M", color="R", updated_at="2026-08-10"),
    ]
    truth = {"1": {
        "aaaaaaaa": ("M", "R"),
        "bbbbbbbb": ("L", "R"),
        "dddddddd": ("M", "R"),
    }}
    result = R.reconcile_rows(rows, truth)
    s = result["summary"]
    assert s["total"] == 5
    assert s["keep"] == 2
    assert s["retire_mismatch"] == 1
    assert s["retire_orphan"] == 1
    assert s["retire_dup_older"] == 1
    assert s["listings_examined"] == 1


# ---------------------------------------------------------------------------
# 8. 出力レポートに実削除への言及が入っていない (誤解防止)
# ---------------------------------------------------------------------------
def test_render_text_report_states_dry_run_only():
    result = R.reconcile_rows(
        [make_row(listing_id="1", uuid="aaa11111", size="M", color="R")],
        {"1": {"aaa11111": ("M", "R")}},
    )
    text = R.render_text_report(result, {})
    assert "dry-run" in text.lower()
    assert "変更していません" in text or "変更しません" in text
