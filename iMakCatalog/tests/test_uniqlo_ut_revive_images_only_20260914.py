"""廃盤 UT の救済 (revive) の回帰 (2026-09-14).

- 品番リストを渡した救済では、画像だけの行 (images_only) を「在る」に数えない
  (数えると Wayback に商品ページが残っていても起こせない: E453662 FILM RED 黒)
- 倉庫の未収録分を拾う経路 (unknown_pids) は従来どおり全行を「在る」に数える
  (画像だけの 177行を毎月 Wayback に取りに行かないため)
- 原産国は Wayback の保存ページからも移す
"""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "scrapers" / "uniqlo_ut_revive.py").read_text(encoding="utf-8")
GUARD = "!= 'images_only'"


def _body(name: str) -> str:
    return SRC.split(f"def {name}(")[1].split("\ndef ")[0]


class TestReviveImagesOnly(unittest.TestCase):
    def test_pids_file_run_does_not_count_images_only(self):
        self.assertIn(GUARD, _body("run"))

    def test_from_raw_does_not_count_images_only(self):
        self.assertIn(GUARD, _body("run_from_raw"))

    def test_unknown_pids_counts_all_rows(self):
        self.assertNotIn(GUARD, _body("unknown_pids"))

    def test_origin_copied_regardless_of_source(self):
        body = _body("_save_one")
        i = body.find('specs["countries_of_origin"] = coo')
        self.assertGreater(i, 0)
        self.assertNotIn('if src == "official"', body[body.rfind("\n", 0, i - 40):i])


if __name__ == "__main__":
    unittest.main()
