"""DON!! PRB02 character-key 配線の回帰テスト (2026-07-25)。

PRB02 の Buggy/Shanks Gold DON は Vision で rarity(treatment) が空でも **character 単独**で
一意解決できる(Catalog POC f6834e1)。従来は don_treatment_subject が None(treatment空)→即skipで
character 経路に到達しなかった。修正: treatment 空でも原subjectで lookup_don を試す。

その subject 選択ロジック `don_lookup_subject`(純関数)をガードする。lookup_don 自体の解決は
Catalog worktree(iMak_catalog)の test 領域なので、ここでは worktree 非依存の純関数のみ検証。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iMakTCG"))

from psa_to_csv import don_lookup_subject


def test_treatment_empty_falls_back_to_original_subject():
    # treatment 空(subj_try=None) → 原subjectで lookup(character解決用)。★これが今回の根治点
    assert don_lookup_subject("DON!! CARD", None) == "DON!! CARD"


def test_treatment_present_uses_concatenated_subject():
    # treatment 有 → 連結版を使う(従来挙動)
    assert don_lookup_subject("DON!! CARD", "DON!! CARD ALTERNATE ART GOLD") == "DON!! CARD ALTERNATE ART GOLD"


def test_empty_subj_try_string_also_falls_back():
    # subj_try が空文字("")でも原subjectにフォールバック(None と同様)
    assert don_lookup_subject("DON!! CARD", "") == "DON!! CARD"
