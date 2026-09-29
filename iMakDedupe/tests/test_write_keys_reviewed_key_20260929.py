"""--write-keys-from-csv は目視で決めた KEY (.canonical.json の控え) を写す.

依頼: iMak_data/dedupe/requests/2026-09-29_write_keys_follow_reviewed_key.md

実害 (2026-09-29): cert 174855277 / 169977472 は目視で `one_piece_tcg:EB03-026_p1`
と決めたのに、引き直した `one_piece_tcg:EB03-026` がシートに入り、出品中の
_p1 と見分けられず 2つ目が出品された (820185511332)。

検証:
1. 控えがあれば控えの KEY を書く (引き直した値で上書きしない)
2. 控えが無い cert は従来どおり引き直した値
3. 控えが無い / 壊れている → 全件従来どおり (fail-closed)
"""

from __future__ import annotations

import csv
import json
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
    r[8] = cert
    r[17] = cat
    r[18] = key
    return r


_HEADER = [""] * 19
_HEADER[8] = "cert"
_HEADER[17] = "カテゴリ"
_HEADER[18] = "KEY"


def _run(tmp_path, high_rows, csv_certs, resolve_map, sidecar=None, sidecar_raw=None):
    ws = MagicMock()
    ws.get_all_values.return_value = [_HEADER] + high_rows
    path = tmp_path / "up.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[CERT_CSV, "*Title"], quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for c in csv_certs:
            w.writerow({CERT_CSV: c, "*Title": f"title-{c}"})

    side = Path(str(path) + ".canonical.json")
    if sidecar_raw is not None:
        side.write_text(sidecar_raw, encoding="utf-8")
    elif sidecar is not None:
        side.write_text(
            json.dumps({"source_csv": path.name, "by_cert": sidecar}),
            encoding="utf-8",
        )

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


def test_reviewed_key_wins_over_resolver(tmp_path):
    """控えの _p1 付き KEY を写す (= 引き直した bare で上書きしない)."""
    high = [_high_row(cert="174855277", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["174855277"],
        {"174855277": {"product_id": "EB03-026", "category": "one_piece_tcg"}},
        sidecar={"174855277": "one_piece_tcg:EB03-026_p1"},
    )
    assert writes["S2"] == "one_piece_tcg:EB03-026_p1"
    assert result["from_reviewed"] == 1
    assert result["reviewed_overrode_resolver"] == 1
    assert result["written_key"] == 1


def test_cert_absent_from_sidecar_uses_resolver(tmp_path):
    """控えに無い cert は従来どおり引き直した値."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
        sidecar={"999": "one_piece_tcg:EB03-026_p1"},
    )
    assert writes["S2"] == "gundam_tcg:ST02-010"
    assert result["from_reviewed"] == 0


def test_no_sidecar_unchanged(tmp_path):
    """控えが無ければ従来どおり."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
    )
    assert writes["S2"] == "gundam_tcg:ST02-010"
    assert result["reviewed_keys_loaded"] == 0


def test_broken_sidecar_falls_back(tmp_path):
    """控えが壊れていても止めず、従来経路に戻る (fail-closed)."""
    high = [_high_row(cert="111", cat="TCG", key="")]
    result, writes = _run(
        tmp_path, high, ["111"],
        {"111": {"product_id": "ST02-010", "category": "gundam_tcg"}},
        sidecar_raw="{ not json",
    )
    assert writes["S2"] == "gundam_tcg:ST02-010"
    assert result["reviewed_keys_loaded"] == 0
