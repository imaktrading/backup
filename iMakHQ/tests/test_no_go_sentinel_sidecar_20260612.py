"""excluder 価格NO-GO cert sidecar の回帰テスト (2026-06-12).

背景: post_no_go_sentinel は従来 `.csv.bak` 差分で価格NO-GO certを求めていたが、
`.csv.bak` は後段 dedupe が同名で上書きするため、差分が「dedupe除外cert」に化けて
価格NO-GO cert を取りこぼし・誤certに sentinel 書込していた。
→ excluder が除外時に cert を sidecar (`<csv>.nogo_certs.json`) 保存し、
   post_no_go_sentinel はそれを読む方式に変更。本テストはその担保。
"""
import csv
import json
import os
import sys
from pathlib import Path

import pytest

_EXCL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI", "csv_postprocess"))
if _EXCL_DIR not in sys.path:
    sys.path.insert(0, _EXCL_DIR)

try:
    import excluder  # noqa: E402
except Exception as e:  # pragma: no cover
    pytest.skip(f"excluder import 不能: {type(e).__name__}: {e}", allow_module_level=True)

_SENTINEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if _SENTINEL_DIR not in sys.path:
    sys.path.insert(0, _SENTINEL_DIR)
import post_no_go_sentinel as sentinel  # noqa: E402

CERT_COL = "CDA:Certification Number - (ID: 27503)"


def _write_csv(p, rows):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerows(rows)


def _make_csv(tmp_path):
    csv_p = tmp_path / "t.csv"
    header = ["*Action", "*Title", CERT_COL]
    _write_csv(csv_p, [
        header,
        ["x", "Card A keep", "111111"],     # row1 keep
        ["x", "Card B nogo", "222222"],     # row2 NO-GO (価格)
        ["x", "Card C keep", "333333"],     # row3 keep
        ["x", "Card D nogo", "444444"],     # row4 NO-GO (価格)
    ])
    return csv_p


def _nogo_stdout():
    return (
        "🏁 GATE判定サマリー\n"
        "  [2] Card B... → ❌ NO-GO 出品100件 $500 乖離68% > 許容15%\n"
        "  [4] Card D... → ❌ NO-GO 出品100件 $300 乖離63% > 許容40%\n"
        "============================================================\n"
    )


def test_excluder_collects_nogo_certs_and_writes_sidecar(tmp_path):
    csv_p = _make_csv(tmp_path)
    result = excluder.exclude_from_check_csv_stdout(str(csv_p), _nogo_stdout())
    # 除外された 価格NO-GO cert = row2,4 の cert (dedupe除外でなく価格除外の cert)
    assert sorted(result["removed_certs"]) == ["222222", "444444"]
    sidecar = Path(str(csv_p) + ".nogo_certs.json")
    assert sidecar.exists()
    assert sorted(json.load(open(sidecar, encoding="utf-8"))) == ["222222", "444444"]
    # 残存CSV = keep 2 行
    with open(csv_p, encoding="utf-8") as f:
        kept = sorted(r[CERT_COL] for r in csv.DictReader(f))
    assert kept == ["111111", "333333"]


def test_sentinel_reads_sidecar_not_bak_diff(tmp_path):
    """post_no_go_sentinel は sidecar の価格NO-GO cert を返す (dedupe が .bak を上書きしても不変)."""
    csv_p = _make_csv(tmp_path)
    excluder.exclude_from_check_csv_stdout(str(csv_p), _nogo_stdout())
    # dedupe が .csv.bak を別内容で上書きした状況を模擬 (= 旧バグの再現条件)
    bak = Path(str(csv_p) + ".bak")
    _write_csv(bak, [
        ["*Action", "*Title", CERT_COL],
        ["x", "Card A keep", "111111"],
        ["x", "Card C keep", "333333"],
        ["x", "Card E dedupe-removed", "999999"],  # dedupe 除外 cert (価格NO-GOでない)
    ])
    certs = sentinel._get_no_go_certs(str(csv_p))
    # sidecar 由来 = 価格NO-GO のみ。dedupe除外(999999)は含まない、価格NO-GO(222222/444444)は漏れない
    assert certs == ["222222", "444444"]
    assert "999999" not in certs


def test_sidecar_empty_when_no_nogo(tmp_path):
    csv_p = tmp_path / "t.csv"
    _write_csv(csv_p, [["*Action", "*Title", CERT_COL], ["x", "Card A", "111111"]])
    result = excluder.exclude_from_check_csv_stdout(str(csv_p), "no gate section here")
    assert result["removed_certs"] == []
    sidecar = Path(str(csv_p) + ".nogo_certs.json")
    assert sidecar.exists()
    assert json.load(open(sidecar, encoding="utf-8")) == []
    assert sentinel._get_no_go_certs(str(csv_p)) == []
