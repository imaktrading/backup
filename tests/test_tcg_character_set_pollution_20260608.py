"""Regression: 2026-06-08 TCG C:Character/Card Name の set名汚染を生成側で根絶.

問題 (CSV監査くんが検出):
  Pokemon の character/card_name は PSA Subject を denylist で削って作るため、未登録の新 set 名が
  末尾に残る → C:Character='Togekiss V Legendary Heartbeat' / 'Corviknight Vmax Vmax Climax'。
  eBay Character フィルタ不ヒット。denylist 方式は新 set 毎に追記=後手後手 ([[refine_generation_not_audit_firefighting]])。

修正 (先手): 確定済 set 名 (catalog の set_name_ebay) を character/card_name 末尾から決定論的に剥がす
  _strip_known_set_suffix → denylist 漏れを根絶。
"""
import importlib.util
import sys
from pathlib import Path

_TCG = Path(__file__).resolve().parent.parent / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def _load():
    spec = importlib.util.spec_from_file_location("psa_to_csv", str(_TCG / "psa_to_csv.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = _load()


def test_strip_set_name_from_character():
    f = P._strip_known_set_suffix
    assert f("Togekiss V Legendary Heartbeat", "Legendary Heartbeat") == "Togekiss V"
    assert f("Corviknight Vmax Vmax Climax", "VMAX Climax") == "Corviknight Vmax"


def test_strip_is_case_insensitive():
    assert P._strip_known_set_suffix("Pikachu Crown Zenith", "crown zenith") == "Pikachu"


def test_unrelated_set_leaves_name_unchanged():
    # set 名が末尾に無ければ触らない (誤削除しない)
    assert P._strip_known_set_suffix("Mega Clefable Ex", "Ultra Prism") == "Mega Clefable Ex"
    assert P._strip_known_set_suffix("Pikachu", "Crown Zenith") == "Pikachu"


def test_never_returns_empty():
    # set名 == name の異常時も空を返さず元を維持 (fail-safe)
    assert P._strip_known_set_suffix("Crown Zenith", "Crown Zenith") == "Crown Zenith"


def test_empty_inputs():
    assert P._strip_known_set_suffix("", "X") == ""
    assert P._strip_known_set_suffix("Pikachu", "") == "Pikachu"
