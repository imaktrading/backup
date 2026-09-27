"""買えない仕入元: ファイルとスプシのタブの両方を読む (2026-09-27, 残務 №372)。

監視くんが LAPTOP に移り、監視くんが書く not_buyable / restockable がこの PC のファイルに届かなくなった。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402

TAB = [["url", "種類", "理由", "日時", "書いた担当"],
       ["https://m/a", "not_buyable", "売り切れ", "2026-09-27", "監視くん"],
       ["https://m/b", "restockable", "Shops 再入荷", "2026-09-27", "監視くん"],
       ["", "not_buyable", "URL 空は読まない", "", ""]]


def test_tab_rows_by_kind():
    d = mp.tab_rows_by_kind(TAB)
    assert list(d["not_buyable"]) == ["https://m/a"]
    assert list(d["restockable"]) == ["https://m/b"]


def test_merges_file_and_tab(monkeypatch, tmp_path):
    p = tmp_path / "nb.json"
    p.write_text(json.dumps({"https://m/file": {"why": "x"}}), encoding="utf-8")
    monkeypatch.setattr(mp, "NOT_BUYABLE_PATH", str(p))
    monkeypatch.setattr(mp, "_TAB_MEMO", {"rows": mp.tab_rows_by_kind(TAB)})
    d = mp.load_not_buyable(str(p))
    assert set(d) == {"https://m/file", "https://m/a"}


def test_tab_unreadable_falls_back_to_file(monkeypatch, tmp_path):
    p = tmp_path / "nb.json"
    p.write_text(json.dumps({"https://m/file": {"why": "x"}}), encoding="utf-8")
    monkeypatch.setattr(mp, "NOT_BUYABLE_PATH", str(p))
    monkeypatch.setattr(mp, "_TAB_MEMO", {"rows": {}})
    assert set(mp.load_not_buyable(str(p))) == {"https://m/file"}
