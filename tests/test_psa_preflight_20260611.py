"""PSA pre-flight 監査ツールの分類ロジック回帰テスト (2026-06-11).

出品前に「索引不備(catalogに在るが引けない) / 真の未収録 / 要判定」を区別する。
- 0/O 等の set-code 変種で実在 → INDEX-FAILURE (resolver修正で直る)
- name+番号で候補在り → REVIEW (断定しない)
- 何も無し → GAP
本テストは catalog DB に依存しない純ロジック部分 (_zero_o_variants, _subject_tokens, detect_category)。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("psa_preflight", str(_TOOLS / "psa_preflight.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_zero_o_variants_covers_0_and_O():
    P = _load()
    v = P._zero_o_variants("SV0M")
    # SV0M(数字0) から SVOM(英字O) を生成できること (= Marnie 0/O 索引不備の核)
    assert "SVOM" in v
    # ★2026-08-26: 自身も残す。resolver は product_id 直引きではないので「試し済」ではない
    #   (2026-08-26_act_code_proposals_tcg.md 提案3)
    assert "SV0M" in v


def test_zero_o_variants_no_0o_has_no_swap():
    P = _load()
    # 0/O を含まない set_code は 0<->O swap 変種を生まない (case変種のみ)
    v = P._zero_o_variants("ST7")
    assert "ST7" in v       # ★2026-08-26: 自身も残す
    assert all("0" not in x and "O" not in x for x in v)  # 0/O swap 由来は無い


def test_subject_tokens_drops_noise():
    P = _load()
    toks = [t.lower() for t in P._subject_tokens("SHINING MAGIKARP-HOLO PCP 25TH ANNIVERSARY ED.")]
    assert "magikarp" in toks
    assert "holo" not in toks  # noise 除外
    assert "anniversary" not in toks


def test_detect_category():
    P = _load()
    assert P.detect_category("POKEMON JAPANESE M2A-MEGA DREAM EX") == "pokemon_tcg"
    assert P.detect_category("ONE PIECE OP05") == "one_piece_tcg"
    assert P.detect_category("KOBE BRYANT") is None  # スポーツ=TCG外
