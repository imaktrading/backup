"""Regression: 2026-06-03 post_psa_review で NONE(該当なし)判定 cert を入稿 CSV から除外.

【背景】
post_psa_review HTML で cert を「該当なし(NONE)」判定しても、_apply_user_judgments が
OK/CHOSEN 以外を skip するだけで CSV から除外せず、識別不能カードが入稿 CSV に残っていた
(= 出品の正確性原則違反)。cert 133532392 Pikachu(S-P-001) を NONE 判定したのに CSV 残存。

【対策】
_remove_certs_from_csv: NONE/NG 判定 cert の論理行を CSV から物理除外 (fail-closed)。
Description が HTML で複数物理行に跨るため "Add", 行境界で論理行を判定。残す行は byte 不変。
"""
from __future__ import annotations
import csv
import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_PPR = _REPO / "iMakHQ" / "tools" / "post_psa_review.py"
_spec = importlib.util.spec_from_file_location("post_psa_review_test", str(_PPR))
ppr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppr)

_CERT_COL = "CDA:Certification Number - (ID: 27503)"
_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
           "*Title", _CERT_COL, "*Description"]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(_HEADER)
        for r in rows:
            w.writerow(r)


def _read_certs(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [row[_CERT_COL].strip() for row in csv.DictReader(f)]


def test_removes_only_none_cert_row(tmp_path):
    p = tmp_path / "upload.csv"
    _write_csv(p, [
        ["Add", "Card A", "111111111", "<html>line1\nline2 multiline</html>"],
        ["Add", "Card B Pikachu", "133532392", "<html>desc B</html>"],
        ["Add", "Card C", "333333333", "single line"],
    ])
    removed = ppr._remove_certs_from_csv(str(p), {"133532392"})
    assert removed == 1
    certs = _read_certs(p)
    assert "133532392" not in certs
    assert certs == ["111111111", "333333333"]


def test_multiline_description_row_preserved(tmp_path):
    """除外対象でない複数行 Description 行は壊れず保持される."""
    p = tmp_path / "upload.csv"
    _write_csv(p, [
        ["Add", "Card A", "111111111", "<html>l1\nl2\nl3</html>"],
        ["Add", "Card B", "222222222", "<html>x</html>"],
    ])
    ppr._remove_certs_from_csv(str(p), {"222222222"})
    with open(p, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0][_CERT_COL].strip() == "111111111"
    assert rows[0]["*Description"] == "<html>l1\nl2\nl3</html>"


def test_noop_when_no_matching_cert(tmp_path):
    p = tmp_path / "upload.csv"
    _write_csv(p, [["Add", "Card A", "111111111", "x"]])
    before = p.read_text(encoding="utf-8")
    removed = ppr._remove_certs_from_csv(str(p), {"999999999"})
    assert removed == 0
    assert p.read_text(encoding="utf-8") == before  # byte 不変


def test_empty_inputs_safe(tmp_path):
    p = tmp_path / "upload.csv"
    _write_csv(p, [["Add", "A", "111111111", "x"]])
    assert ppr._remove_certs_from_csv(str(p), set()) == 0
    assert ppr._remove_certs_from_csv(None, {"111111111"}) == 0
