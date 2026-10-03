"""PSA 新規を KAGOYA で動かす (2026-10-03 段階B⑤)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "console"))

import kagoya_offload as K  # noqa: E402
import server as S  # noqa: E402

PSA_AUTO = {"category": "PSA TCG", "label": "🤖自動"}
TEE_AUTO = {"category": "Tシャツ", "label": "🤖自動"}


def test_only_psa_auto_goes_to_kagoya_when_named_with_category():
    """「🤖自動」は商材をまたいで同じ名前。商材付きで書いた PSA だけが KAGOYA に向く。"""
    names = {"PSA TCG 🤖自動"}
    assert S.is_remote(PSA_AUTO, names)
    assert not S.is_remote(TEE_AUTO, names)


def test_plain_label_still_matches():
    assert S.is_remote({"category": "PSA TCG", "label": "🆕 PSA 補URL ① 当日分"}, {"🆕 PSA 補URL ① 当日分"})


def test_tcg_code_files_sent_but_not_the_key():
    assert K.tcg_code_file("psa_to_csv.py")
    assert K.tcg_code_file("PSA10.txt")            # 説明文テンプレ (読めなければ止まる)
    assert K.tcg_code_file("cert_overrides.json")
    assert not K.tcg_code_file("API key.txt")      # 鍵は送らない
    assert not K.tcg_code_file("ebay_upload_20260413_091322_cost.json")


def test_kagoya_picks_from_prefetched_before_selecting():
    """先取りに無い cert は選ぶ前に外す (選んだ後に飛ばすと20件の枠が減る)。順番は保つ。"""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakTCG"))
    sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakeBayAPI"))
    import psa_to_csv as P
    cache = {"1": {"Subject": "A", "Grade": "10"}, "2": {"Subject": "B"}, "4": {"Subject": "D", "Grade": ""}}
    ok, wait = P.split_cached_certs(["1", "2", "3", "4"], cache)
    assert ok == ["1", "4"] and wait == ["2", "3"]
