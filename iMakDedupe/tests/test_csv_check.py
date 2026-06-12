"""csv_check unit tests — sample CSV で動作確認 (offline)."""

import csv
from pathlib import Path

import pytest

from dedupe import csv_check
from dedupe.checker import extract_priority_key2

pytestmark = pytest.mark.offline


def _write_csv(path: Path, rows: list, fieldnames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC
        )
        writer.writeheader()
        writer.writerows(rows)


class TestExtractKeysFromRow:
    def test_title_card_id_no_variant(self):
        row = {
            "*Title": "One Piece #OP01-016 Shanks Leader",
            "C:Card Number": "OP01-016",
        }
        k1, t1, k2 = csv_check.extract_keys_from_csv_row(row, extract_priority_key2)
        assert k1 == "OP01-016"
        assert t1 == "card"
        assert k2 == ""

    def test_title_with_variant_in_features(self):
        row = {
            "*Title": "OP02-120 Uta",
            "C:Card Number": "OP02-120",
            "C:Features": "Alternative Art",
        }
        k1, t1, k2 = csv_check.extract_keys_from_csv_row(row, extract_priority_key2)
        assert k1 == "OP02-120"
        assert k2 == "alt"

    def test_secret_in_speciality(self):
        row = {
            "*Title": "OP08-106 Nami",
            "C:Card Number": "OP08-106",
            "C:Speciality": "Secret Rare",
        }
        k1, t1, k2 = csv_check.extract_keys_from_csv_row(row, extract_priority_key2)
        assert k1 == "OP08-106"
        assert k2 == "sec"

    def test_card_number_only_fallback_when_title_misses(self):
        """title から取れず、 C:Card Number に完全形があれば key1 取得."""
        row = {
            "*Title": "Some random PSA10 card serial 1234",
            "C:Card Number": "OP05-060",
        }
        k1, t1, k2 = csv_check.extract_keys_from_csv_row(row, extract_priority_key2)
        assert k1 == "OP05-060"
        assert t1 == "card"

    def test_fail_closed(self):
        row = {
            "*Title": "Random no-id title",
            "C:Card Number": "060",  # 連番のみ = 未対応形式
        }
        k1, t1, k2 = csv_check.extract_keys_from_csv_row(row, extract_priority_key2)
        assert k1 is None


class TestCheckCsv:
    @pytest.fixture
    def existing_tuples(self):
        return frozenset(
            {
                ("OP01-016", ""),
                ("OP02-120", "sec"),
                ("DW-5600-1JF", ""),
            }
        )

    def test_no_duplicates_dry_run(self, tmp_path, existing_tuples):
        csv_path = tmp_path / "test.csv"
        _write_csv(
            csv_path,
            rows=[
                {"*Title": "OP99-001 Brand-new card", "C:Card Number": "OP99-001"},
                {"*Title": "OP88-002 Another new", "C:Card Number": "OP88-002"},
            ],
            fieldnames=["*Title", "C:Card Number"],
        )
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=True,
        )
        assert result["total"] == 2
        assert result["removed"] == 0
        assert result["kept"] == 2
        assert result["backup_path"] == ""
        # 元 CSV 不変
        with csv_path.open(encoding="utf-8") as f:
            assert len(list(csv.reader(f))) == 3  # header + 2 rows

    def test_duplicate_removed(self, tmp_path, existing_tuples):
        csv_path = tmp_path / "test.csv"
        _write_csv(
            csv_path,
            rows=[
                {"*Title": "OP01-016 Shanks Leader", "C:Card Number": "OP01-016"},
                {"*Title": "OP99-001 Brand-new", "C:Card Number": "OP99-001"},
            ],
            fieldnames=["*Title", "C:Card Number"],
        )
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=False,
        )
        assert result["removed"] == 1
        assert result["kept"] == 1
        assert "OP01-016" in result["removed_titles"][0]
        # bak 保存確認
        backup = Path(result["backup_path"])
        assert backup.exists()
        # 上書き後 CSV は kept 1 件
        with csv_path.open(encoding="utf-8") as f:
            new_rows = list(csv.reader(f))
        assert len(new_rows) == 2  # header + 1 kept row

    def test_variant_difference_keeps_row(self, tmp_path, existing_tuples):
        """KEY1 一致 + KEY2 違い → 別 variant、 残存."""
        csv_path = tmp_path / "test.csv"
        _write_csv(
            csv_path,
            rows=[
                # 既存 (OP02-120, "sec") に対し こちらは KEY2 空 = 別 variant
                {"*Title": "OP02-120 Uta (normal)", "C:Card Number": "OP02-120"},
                # こちらは (OP02-120, "sec") = 完全一致 → 除外
                {
                    "*Title": "OP02-120 Uta Secret Rare",
                    "C:Card Number": "OP02-120",
                },
            ],
            fieldnames=["*Title", "C:Card Number"],
        )
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=True,
        )
        assert result["removed"] == 1
        assert result["kept"] == 1
        # 残ったのは normal 版
        assert "Secret Rare" in result["removed_titles"][0]

    def test_unknown_kept(self, tmp_path, existing_tuples):
        """KEY1 取れない row は除外せず unknown count に."""
        csv_path = tmp_path / "test.csv"
        _write_csv(
            csv_path,
            rows=[
                {"*Title": "Random no-id title", "C:Card Number": ""},
            ],
            fieldnames=["*Title", "C:Card Number"],
        )
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=True,
        )
        assert result["unknown"] == 1
        assert result["removed"] == 0
        assert result["kept"] == 1

    def test_model_duplicate_with_variant(self, tmp_path, existing_tuples):
        """G-shock 型番 + variant 抽出は KEY1 のみで突合 (= card と同じ)."""
        csv_path = tmp_path / "test.csv"
        _write_csv(
            csv_path,
            rows=[
                {"*Title": "Casio DW-5600-1JF G-Shock", "C:Card Number": ""},
            ],
            fieldnames=["*Title", "C:Card Number"],
        )
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=True,
        )
        assert result["removed"] == 1

    def test_empty_csv(self, tmp_path, existing_tuples):
        csv_path = tmp_path / "empty.csv"
        _write_csv(csv_path, rows=[], fieldnames=["*Title", "C:Card Number"])
        result = csv_check.check_csv(
            csv_path=csv_path,
            existing_tuples=existing_tuples,
            priority_extractor2=extract_priority_key2,
            dry_run=True,
        )
        assert result["total"] == 0
        assert result["removed"] == 0
        assert result["kept"] == 0

    def test_missing_file_raises(self, tmp_path, existing_tuples):
        with pytest.raises(FileNotFoundError):
            csv_check.check_csv(
                csv_path=tmp_path / "nope.csv",
                existing_tuples=existing_tuples,
                priority_extractor2=extract_priority_key2,
                dry_run=True,
            )
