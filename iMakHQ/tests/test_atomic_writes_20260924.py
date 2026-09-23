"""書いている最中に PC が落ちても、壊れた/空のファイルを残さない (一時ファイル → 置き換え, 2026-09-24)。"""
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
FILES = {
    "iMakHQ/tools/psa_hoju_fill.py": "def _save_cache",
    "iMakHQ/tools/ut_hoju_fill.py": "def save_cache",
    "iMakHQ/tools/mercari_psa_resource.py": "def remember_not_buyable",
    "iMakHQ/tools/csv_auditor.py": "def _write_csv",
    "iMakeBayAPI/csv_postprocess/excluder.py": "# 上書き保存",
}


def test_writes_go_through_tmp_and_replace():
    for rel, anchor in FILES.items():
        s = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        body = s[s.index(anchor):s.index(anchor) + 1200]
        assert ".tmp" in body and "os.replace(" in body, rel


def test_funnel_csv_is_atomic():
    s = open(os.path.join(ROOT, "iMakHQ/tools/listing_funnel.py"), encoding="utf-8").read()
    assert re.search(r'open\(path \+ "\.tmp", "w"', s) and 'os.replace(path + ".tmp", path)' in s
