"""snapshot_io unit tests — file 読書きベース (no network)."""

from pathlib import Path

import pytest

from dedupe import snapshot_io

pytestmark = pytest.mark.offline


def test_find_latest_returns_none_on_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    assert snapshot_io.find_latest_snapshot(missing) is None


def test_find_latest_returns_none_on_empty_dir(tmp_path):
    (tmp_path / "other.txt").write_text("ignore me")
    assert snapshot_io.find_latest_snapshot(tmp_path) is None


def test_find_latest_picks_lexicographically_last(tmp_path):
    # snapshot filename pattern: ebay_active_YYYY-MM-DD_HHMMSS.csv
    # 辞書順 = 時系列順
    for name in [
        "ebay_active_2026-05-24_185906.csv",
        "ebay_active_2026-05-25_145033.csv",
        "ebay_active_2026-05-25_140324.csv",
    ]:
        (tmp_path / name).write_text("Item number,Title\n")
    latest = snapshot_io.find_latest_snapshot(tmp_path)
    assert latest is not None
    assert latest.name == "ebay_active_2026-05-25_145033.csv"


def test_load_snapshot_titles(tmp_path):
    path = tmp_path / "snap.csv"
    path.write_text(
        "Item number,Title,Currency,Current price\n"
        "358372285429,Gundam Card Game Dual Impact #091 Haman Karn,USD,104.98\n"
        "358372294147,Gundam Card Game Newtype Rising #117 Witch,USD,228.98\n"
        "356700921169,Casio G-Shock DW-5600-1JF Wristwatch,USD,75.00\n",
        encoding="utf-8",
    )
    titles = snapshot_io.load_snapshot_titles(path)
    assert titles["358372285429"].startswith("Gundam Card Game Dual Impact")
    assert titles["358372294147"].startswith("Gundam Card Game Newtype")
    assert "DW-5600-1JF" in titles["356700921169"]


def test_load_snapshot_titles_strips_whitespace(tmp_path):
    path = tmp_path / "snap.csv"
    path.write_text(
        "Item number,Title\n"
        "  358372285429  ,  Gundam Card  \n",
        encoding="utf-8",
    )
    titles = snapshot_io.load_snapshot_titles(path)
    assert titles == {"358372285429": "Gundam Card"}


def test_load_snapshot_titles_skips_empty_item_id(tmp_path):
    path = tmp_path / "snap.csv"
    path.write_text(
        "Item number,Title\n"
        ",Empty item id row\n"
        "12345,Real one\n",
        encoding="utf-8",
    )
    titles = snapshot_io.load_snapshot_titles(path)
    assert titles == {"12345": "Real one"}


def test_load_snapshot_titles_raises_on_missing_required_column(tmp_path):
    path = tmp_path / "snap.csv"
    path.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot_io.load_snapshot_titles(path)
