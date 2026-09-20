import json
import pytest
import run_harvest_mercari_psa10 as p
from scrapers.psa_grade_gate import is_foreign_edition

CFG = {"enabled": True, "max_jpy": 70000, "min_jpy": 100, "repdigit_len": 6}


def test_cost_rejected():
    assert p.cost_rejected(80000, CFG)
    assert p.cost_rejected(1111111, CFG)
    assert p.cost_rejected(50, CFG)
    assert not p.cost_rejected(70000, CFG)
    assert not p.cost_rejected(None, CFG)


def test_cost_cfg_missing_is_fail_closed(tmp_path):
    with pytest.raises(Exception):
        p.load_cost_sanity(tmp_path / "none.json")
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"enabled": True}))
    with pytest.raises(Exception):
        p.load_cost_sanity(f)


def test_foreign_edition():
    assert is_foreign_edition("PSA10 ピカチュウ 中国語版")
    assert is_foreign_edition("リザードン 英語版 151")
    assert is_foreign_edition("English Pikachu")
    assert not is_foreign_edition("PSA10 ピカチュウ 020/M-P")
    assert not is_foreign_edition("Korra")
