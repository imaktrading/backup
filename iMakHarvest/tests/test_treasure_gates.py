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


def test_card_cost_ok_matches_hq_table():
    from scrapers.treasure_keywords import card_cost_ok
    t = "PSA10 ピカチュウ 020/M-P"
    for limit, top in [(400, 600), (3000, 4500), (10000, 15000), (50000, 57000)]:
        lim = {"020/M-P": limit}
        assert card_cost_ok(t, top, lim)
        assert not card_cost_ok(t, top + 1, lim)


def test_card_cost_ok_unknown_number_passes():
    from scrapers.treasure_keywords import card_cost_ok
    assert card_cost_ok("PSA10 ピカチュウ", 60000, {"020/M-P": 400})
    assert card_cost_ok("PSA10 ピカチュウ 020/M-P", None, {"020/M-P": 400})
