"""bare KEー → {category}:{product_id} upgrade (Phase3) test.

依頼: iMak_data/dedupe/requests/2026-07-27_key_category_phase3_sync_needed.md
      + _hq_response_phase3_and_cache_warming.md

二重 fail-closed の検証:
- resolver が category 確定 かつ 再導出 pid == 既存 bare の時のみ upgrade
- category 未確定 / pid 不一致 / url-key / 既に prefixed / 空 → 据置
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dedupe import sheet_io

pytestmark = pytest.mark.offline

KEY_COL = 5
TITLE_COL = 3
CERT_COL = 9


def _row(title="", cert="", key=""):
    r = [""] * 9
    r[2] = title      # C (col 3)
    r[8] = cert       # I (col 9)
    r[KEY_COL - 1] = key   # KEー (col 5)
    return r


_HEADER = ["A", "B", "title", "D", "KEY", "F", "G", "H", "cert"]


def _run(rows, resolve_map, dry_run=False):
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + rows

    def _fake(title="", url="", image_url="", cert="", extra_text="", purpose="dedup"):
        # resolve_map: cert or title → {"product_id","category"}
        key = cert or title
        return resolve_map.get(key, {"product_id": "", "category": ""})

    with patch("dedupe.resolver_io.resolve_sheet_row_with_category", side_effect=_fake):
        counts = sheet_io.upgrade_bare_keys_to_category(
            ws, key_col=KEY_COL, title_col=TITLE_COL, cert_col=CERT_COL, dry_run=dry_run,
        )
    writes = {}
    if not dry_run:
        for call in ws.batch_update.call_args_list:
            for upd in call.args[0]:
                writes[upd["range"]] = upd["values"][0][0]
    return counts, writes


def test_bare_upgraded_when_category_and_pid_match():
    """bare `ST02-010` + resolver {ST02-010, gundam_tcg} → gundam_tcg:ST02-010."""
    rows = [_row(title="Heero", cert="111", key="ST02-010")]
    counts, writes = _run(rows, {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}})
    assert counts["upgraded"] == 1
    assert counts["by_category"] == {"gundam_tcg": 1}
    assert writes["E2"] == "gundam_tcg:ST02-010"


def test_variant_suffix_preserved():
    """bare `ST01-006_p1` → one_piece_tcg:ST01-006_p1 (variant 保持・曖昧9行の解決)."""
    rows = [_row(title="Chopper", cert="222", key="ST01-006_p1")]
    counts, writes = _run(rows, {"222": {"product_id": "ST01-006_p1", "category": "one_piece_tcg"}})
    assert counts["upgraded"] == 1
    assert writes["E2"] == "one_piece_tcg:ST01-006_p1"


def test_no_category_skipped():
    """resolver が category 確定できず → 据置 (fail-closed)."""
    rows = [_row(title="?", cert="333", key="ST02-010")]
    counts, writes = _run(rows, {"333": {"product_id": "ST02-010", "category": ""}})
    assert counts["upgraded"] == 0
    assert counts["skipped_no_category"] == 1
    assert writes == {}


def test_pid_mismatch_skipped():
    """再導出 pid が既存 bare と不一致 → 据置 (別カード化防止)."""
    # 既存 bare ST04-013 だが resolver は別 pid を返す (= Yugioh 等に化ける懸念)
    rows = [_row(title="Endymion", cert="444", key="ST04-013")]
    counts, writes = _run(rows, {"444": {"product_id": "SDCB-JP041", "category": "yugioh_tcg"}})
    assert counts["upgraded"] == 0
    assert counts["skipped_pid_mismatch"] == 1
    assert writes == {}


def test_already_prefixed_skipped():
    """既に新形式 → 据置."""
    rows = [_row(title="x", cert="555", key="one_piece_tcg:OP01-016")]
    counts, writes = _run(rows, {"555": {"product_id": "OP01-016", "category": "one_piece_tcg"}})
    assert counts["upgraded"] == 0
    assert counts["skipped_already_prefixed"] == 1
    assert writes == {}


def test_url_key_skipped():
    """url-key は対象外 (prefix しない)."""
    rows = [_row(title="x", cert="", key="item:m12345")]
    counts, writes = _run(rows, {})
    assert counts["upgraded"] == 0
    assert counts["skipped_url_key"] == 1
    assert writes == {}


def test_empty_key_skipped():
    """空 KEー は対象外 (backfill の領分)."""
    rows = [_row(title="x", cert="777", key="")]
    counts, writes = _run(rows, {"777": {"product_id": "OP01-016", "category": "one_piece_tcg"}})
    assert counts["upgraded"] == 0
    assert counts["skipped_empty"] == 1
    assert writes == {}


def test_url_key_resolved_not_prefixed():
    """bare key だが resolver が url-key を返す → category 空 → 据置."""
    rows = [_row(title="mercari", cert="", key="SOMEKEY")]
    counts, writes = _run(rows, {"mercari": {"product_id": "item:m999", "category": ""}})
    assert counts["upgraded"] == 0
    assert counts["skipped_no_category"] == 1
    assert writes == {}


def test_dry_run_no_write():
    rows = [_row(title="Heero", cert="111", key="ST02-010")]
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + rows

    def _fake(**kw):
        return {"product_id": "ST02-010", "category": "gundam_tcg"}

    with patch("dedupe.resolver_io.resolve_sheet_row_with_category", side_effect=_fake):
        counts = sheet_io.upgrade_bare_keys_to_category(
            ws, key_col=KEY_COL, title_col=TITLE_COL, cert_col=CERT_COL, dry_run=True,
        )
    assert counts["upgraded"] == 1
    ws.batch_update.assert_not_called()


def test_idempotent_second_run():
    """upgrade 後 (prefixed) は skipped_already_prefixed で追加 0."""
    rows = [_row(title="Heero", cert="111", key="gundam_tcg:ST02-010")]
    counts, writes = _run(rows, {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}})
    assert counts["upgraded"] == 0
    assert counts["skipped_already_prefixed"] == 1


# ==============================================================================
# 2026-07-29 Advisor GO: resolver 空時の catalog 直接 lookup fallback (§2)
# ==============================================================================


def _run_with_direct(rows, resolve_map, direct_lookup, dry_run=False):
    """resolver + catalog 直接 lookup 両方 patch する版."""
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + rows

    def _fake(title="", url="", image_url="", cert="", extra_text="", purpose="dedup"):
        key = cert or title
        return resolve_map.get(key, {"product_id": "", "category": ""})

    def _fake_direct(product_id):
        return direct_lookup.get(product_id.upper() if product_id else "")

    with patch("dedupe.resolver_io.resolve_sheet_row_with_category", side_effect=_fake), \
         patch("dedupe.catalog_io.get_category_by_product_id_unique", side_effect=_fake_direct):
        counts = sheet_io.upgrade_bare_keys_to_category(
            ws, key_col=KEY_COL, title_col=TITLE_COL, cert_col=CERT_COL, dry_run=dry_run,
        )
    writes = {}
    if not dry_run:
        for call in ws.batch_update.call_args_list:
            for upd in call.args[0]:
                writes[upd["range"]] = upd["values"][0][0]
    return counts, writes


def test_direct_lookup_hit_unique():
    """resolver 空 + catalog unique 1 hit → upgrade via direct lookup (§2 GO 主経路)."""
    rows = [_row(title="?", cert="cert-r008", key="R-008")]
    counts, writes = _run_with_direct(
        rows,
        resolve_map={"cert-r008": {"product_id": "", "category": ""}},  # resolver 空
        direct_lookup={"R-008": "gundam_tcg"},
    )
    assert counts["upgraded"] == 1
    assert counts["upgraded_via_direct_lookup"] == 1
    assert counts["by_category"] == {"gundam_tcg": 1}
    assert counts["skipped_no_category"] == 0
    assert writes["E2"] == "gundam_tcg:R-008"


def test_direct_lookup_ambiguous_skipped():
    """catalog に 2+ hit → unique 関数が None → 据置 (fail-closed §2 条件①)."""
    rows = [_row(title="?", cert="cert-eb", key="EB01-006")]
    counts, writes = _run_with_direct(
        rows,
        resolve_map={"cert-eb": {"product_id": "", "category": ""}},  # resolver 空
        direct_lookup={"EB01-006": None},  # unique 関数は ambiguous 時 None
    )
    assert counts["upgraded"] == 0
    assert counts["upgraded_via_direct_lookup"] == 0
    assert counts["skipped_no_category"] == 1
    assert writes == {}


def test_direct_lookup_not_found_skipped():
    """catalog 未登録 (T17 = NIKKE 等) → unique 関数が None → 据置."""
    rows = [_row(title="?", cert="cert-t17", key="T17")]
    counts, writes = _run_with_direct(
        rows,
        resolve_map={"cert-t17": {"product_id": "", "category": ""}},
        direct_lookup={},  # 未登録 → None
    )
    assert counts["upgraded"] == 0
    assert counts["upgraded_via_direct_lookup"] == 0
    assert counts["skipped_no_category"] == 1
    assert writes == {}


def test_direct_lookup_not_used_when_resolver_succeeds():
    """§2 条件③: 既存 resolver 経路は絶対に置き換えない。resolver hit 時は direct を呼ばない."""
    rows = [_row(title="Heero", cert="cert-ok", key="ST02-010")]
    resolver_map = {"cert-ok": {"product_id": "ST02-010", "category": "gundam_tcg"}}
    # direct lookup が呼ばれないことを確認するため、呼ばれたら別カテゴリを返す trap を仕込む
    direct_lookup = {"ST02-010": "pokemon_tcg"}
    counts, writes = _run_with_direct(rows, resolver_map, direct_lookup)
    assert counts["upgraded"] == 1
    assert counts["upgraded_via_direct_lookup"] == 0  # direct 経由でない
    assert writes["E2"] == "gundam_tcg:ST02-010"  # resolver の gundam_tcg が採用
