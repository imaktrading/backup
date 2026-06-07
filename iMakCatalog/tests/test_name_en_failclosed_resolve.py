"""arch2: resolve_name_en の fail-closed 取り込みロジック回帰テスト.

「番号計算で別種に化ける」(チコリータ→Durant) を構造的に防ぐ:
- canonical な name_jp 直引き(translate_by_rule 独立 match)のみ採用
- 既存 verified と食い違えば disputed (採らない)
- 非独立(trainer/不能) は空欄(fail-closed)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import pokemon_name_translation as T  # noqa: E402

# 最小 poke_dict (name_jp -> 公式英名)
POKE = {"チコリータ": "Chikorita", "ピカチュウ": "Pikachu", "リオル": "Riolu"}


def test_independent_rule_accepted():
    en, status, _ = T.resolve_name_en("チコリータ", POKE)
    assert en == "Chikorita" and status == "verified_auto"


def test_trainer_or_unknown_is_blank_failclosed():
    # trainer/不能 = 非独立 → 空欄 (番号計算の生結果を保存しない)
    en, status, _ = T.resolve_name_en("ビート", POKE)  # POKE に無い=非独立
    assert en is None and status == "blank"


def test_disputed_when_rule_disagrees_with_verified():
    # 既存 verified が Pikachu なのに rule が別を出す状況を模擬
    # (ここでは name_jp に対し POKE が canonical を返すので、
    #  verified を意図的に誤値にして「不一致時に採らない」を検証)
    en, status, _ = T.resolve_name_en(
        "ピカチュウ", POKE, verified_en_by_jp={"ピカチュウ": "Waitress"})
    # rule=Pikachu(独立) != verified=Waitress → disputed, 値は採らない(None)
    assert en is None and status == "disputed"


def test_reuse_verified_when_rule_cannot():
    # rule 不能(POKE未収載) but 既存 verified あり → 源参照で再利用
    en, status, _ = T.resolve_name_en(
        "ナゾの新種", POKE, verified_en_by_jp={"ナゾの新種": "MysteryMon"})
    assert en == "MysteryMon" and status == "reuse_verified"


def test_agreement_promotes_verified_auto():
    en, status, _ = T.resolve_name_en(
        "ピカチュウ", POKE, verified_en_by_jp={"ピカチュウ": "Pikachu"})
    assert en == "Pikachu" and status == "verified_auto"
