"""Regression: 2026-05-09 PSA TCG タイトルの phrase 重複事故.

事故 (csv_output/tcg_upload_20260509_154142.csv Row 3):
  cert 141265801  Greninja & Zoroark Gx (Pokemon Tag All Stars #072):
    Title = "PSA 10 Pokemon Tag All Stars #072 Greninja & Zoroark Gx Tag Team Gx All"
                                                                              ^^^
    末尾が "All Stars" → "All" だけ残る不自然な切れ.
  原因: set "Tag All Stars" と card name "...Tag Team Gx All Stars" の bigram "All Stars"
        重複を _dedupe_consecutive_words が単語単位で処理し、後出 "Stars" のみ削除して
        前 trailing "All" が orphan 化。

修正方針 (本体 logic 不変、新 helper 追加):
  iMakTCG/title_generation_agent.py に _dedupe_phrases を追加し、
  _dedupe_consecutive_words の前段で bigram/trigram 単位の重複除去を実施。
  既存 _dedupe_consecutive_words のロジックは維持 (副作用ゼロ)。

設計原則 (CLAUDE.md spell #2 "if 分岐を含まない汎用 helper"):
  - phrase 内に意味語 (len >= 4) を 1 つ以上含む場合のみ dedup
  - phrase 内に '#' 始まりトークン (card#) は除外
  - bigram → trigram 順で長い phrase を優先
  - max 4 イテレーション (多重重複対応、無限ループ防止)
"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def test_dedupe_tag_all_stars_5_9_case():
    """5/9 実事故: 'All Stars' bigram 重複を後出側から除去."""
    from title_generation_agent import _dedupe_phrases
    title = "PSA 10 Pokemon Tag All Stars #072 Greninja & Zoroark Gx Tag Team Gx All Stars"
    out = _dedupe_phrases(title)
    assert out == "PSA 10 Pokemon Tag All Stars #072 Greninja & Zoroark Gx Tag Team Gx"
    assert "All Stars" in out  # 1 回は残る (set context)
    assert out.count("All Stars") == 1


def test_no_dedupe_when_no_repeat():
    """重複 phrase が無ければ無変更 (副作用ゼロ)."""
    from title_generation_agent import _dedupe_phrases
    title = "PSA 10 Pokemon Battle Partners #006 Pikachu Ex"
    assert _dedupe_phrases(title) == title


def test_no_dedupe_short_phrases():
    """phrase 内全トークンが len < 4 の場合は dedup 対象外 (機能語のみ偽陽性回避)."""
    from title_generation_agent import _dedupe_phrases
    # "of the" のような機能語 phrase の重複は dedup しない
    title = "PSA 10 The Foo of the Bar of the Baz"  # of/the は < 4 chars
    # "of the" は両方とも len < 4 なので dedup されない (= title 不変)
    out = _dedupe_phrases(title)
    assert "of the" in out  # 残る


def test_no_dedupe_card_number_context():
    """card# を含む phrase は dedup しない (例: '#001' を跨いだ phrase が誤って消されない)."""
    from title_generation_agent import _dedupe_phrases
    # bigram (#001, Foo) や (Bar, #001) は has_hash で除外される
    title = "PSA 10 Pokemon #001 Pikachu Ex"
    assert _dedupe_phrases(title) == title


def test_dedupe_trigram_preferred_over_bigram():
    """trigram の重複は trigram 単位で除去 (3 トークン丸ごと、bigram 2 回ではなく)."""
    from title_generation_agent import _dedupe_phrases
    # "Battle Card Game" trigram が 2 回出現
    title = "PSA 10 Battle Card Game #001 Pikachu Battle Card Game"
    out = _dedupe_phrases(title)
    assert out.count("Battle Card Game") == 1


def test_full_pipeline_5_9_case():
    """refine_title フルパイプ: Row 3 入力 → 期待出力 (TitleAgent サマリ込)."""
    from title_generation_agent import refine_title
    title = "PSA 10 Pokemon Tag All Stars #072 Greninja & Zoroark Gx Tag Team Gx All Stars"
    out = refine_title(title, character="Greninja & Zoroark Gx", franchise="Pokemon TCG")
    # 末尾の dangling "All" が消えていること (主要回帰目標)
    assert not out.endswith(" All"), f"Trailing orphan 'All' should be gone, got: {out!r}"
    # set context "Tag All Stars" が 1 回は残ること
    assert "Tag All Stars" in out
    # 80 字制限内
    assert len(out) <= 80


def test_existing_consecutive_dedupe_still_works():
    """副作用ゼロ: 既存 _dedupe_consecutive_words 経由の挙動 (Anniversary Coll. Collection) 維持."""
    from title_generation_agent import _dedupe_consecutive_words
    # 既存テスト相当
    out = _dedupe_consecutive_words("Anniversary Coll. Collection Card")
    assert "Anniversary" in out
    assert out.count("Card") == 1
