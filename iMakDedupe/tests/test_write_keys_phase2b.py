"""--write-keys-from-csv (write_canonical_key_to_high) の Phase2b カテゴリ prefix test.

依頼: iMak_data/dedupe/requests/2026-07-27_key_category_prefix_phase2b_writer.md

検証:
1. catalog-backed → `{category}:{product_id}` で書込 (= 新形式)
2. url-key (category 空) → listing 用途では skip (= product_id のみ採用、従来どおり)
3. fail-closed (product_id 空) → 書かない
4. 既存 product_id KEー は上書きしない (= 冪等維持)
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dedupe import csv_write_keys, sheet_io

pytestmark = pytest.mark.offline

CERT_CSV = "CDA:Certification Number - (ID: 27503)"
KEY_COL = 19
CERT_COL = sheet_io.HIGH_COL_CERT_OR_ENGTITLE   # 9
CAT_COL = sheet_io.HIGH_COL_CATEGORY            # 18


def _high_row(cert="", cat="TCG", key=""):
    r = [""] * 19
    r[8] = cert       # I (col 9)
    r[17] = cat       # R (col 18)
    r[18] = key       # KEー (col 19)
    return r


_HEADER = [""] * 19
_HEADER[8] = "cert"
_HEADER[17] = "カテゴリ"
_HEADER[18] = "KEY"


def _write_csv(path, certs):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[CERT_CSV, "*Title"], quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for c in certs:
            w.writerow({CERT_CSV: c, "*Title": f"title-{c}"})


def _run(tmp_path, high_rows, csv_certs, resolve_map):
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + high_rows
    path = tmp_path / "up.csv"
    _write_csv(path, csv_certs)

    def _fake(row, purpose="dedup"):
        return resolve_map.get((row.get(CERT_CSV) or "").strip(),
                               {"product_id": "", "category": ""})

    with patch("dedupe.resolver_io.resolve_csv_row_with_category", side_effect=_fake):
        result = csv_write_keys.write_canonical_key_to_high(
            ws=ws, csv_path=path, key_col=KEY_COL,
            cert_col=CERT_COL, category_col=CAT_COL,
            tcg_category_value="TCG", dry_run=False,
        )
    writes = {}
    for call in ws.batch_update.call_args_list:
        for upd in call.args[0]:
            writes[upd["range"]] = upd["values"][0][0]
    return result, writes


def test_catalog_backed_written_with_prefix(tmp_path):
    """catalog-backed → {category}:{product_id} で書込."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
    )
    assert result["written_key"] == 1
    assert result["written_with_category"] == 1
    assert result["written_bare_pid"] == 0
    # HIGH row 2, KEー col 19 = S2
    assert writes["S2"] == "gundam_tcg:ST02-010"


def test_url_key_skipped_listing(tmp_path):
    """url-key (category 空) は listing 用途で skip (= product_id のみ)."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "item:m12345", "category": ""}},
    )
    assert result["written_key"] == 0
    assert result["skipped_no_resolution"] == 1
    assert writes == {}


def test_fail_closed_not_written(tmp_path):
    """未解決 (product_id 空) → 書かない."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "", "category": ""}},
    )
    assert result["written_key"] == 0
    assert result["skipped_no_resolution"] == 1
    assert writes == {}


def test_existing_product_id_not_overwritten(tmp_path):
    """既存 product_id KEー は上書きしない (= 冪等)."""
    high = [_high_row(cert="111", cat="TCG", key="one_piece_tcg:OP01-016")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
    )
    assert result["skipped_existing_product_id"] == 1
    assert result["written_key"] == 0
    assert writes == {}


def test_url_key_existing_upgraded_to_prefix(tmp_path):
    """既存 url-key → catalog-backed prefix KEー に upgrade."""
    high = [_high_row(cert="111", cat="TCG", key="item:m999")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
    )
    assert result["upgraded_url_to_product_id"] == 1
    assert writes["S2"] == "gundam_tcg:ST02-010"
