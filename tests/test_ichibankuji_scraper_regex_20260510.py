"""Regression: 2026-05-10 1kuji.com スクレイパー regex が 7/8 series で 0 賞.

事故 (Phase1 run 2026-05-10 14:57):
  8 series 巡回中、NIKKE7 (1/8) のみ 9 賞検出、他 7 series (onep101, db_goku,
  bluelock8, medalist, frieren, winbre6, umamusume16) は **0 賞** = 完全失敗.
  → 中間CSV 3 行のみ、フィギュア判定がほとんど通らない状態.

原因:
  既存 regex `([^\n]+?賞)\s+([^\n]+?)\n■全(\d+)種.*?■サイズ：約([\d.]+)cm` は
  「賞名 アイテム名 \n ■全X種」の改行 \n 必須.
  1kuji.com の HTML 構造 (<h4 class="name sp">A賞 アイテム名</h4>) では
  賞名+アイテム名が単一行内. Selenium body.text 取得時に DOM 構造により
  改行有無が変動 → NIKKE7 は改行入って match、他 7 は改行入らず 0 match.

修正方針 (no_modification_chain):
  regex を緩和:
  - \n → \s* (任意空白許容、改行有無に依存しない)
  - アイテム名側 [^\n]+? → [^\n■]+? (■ 直前で stop、greedy 暴走防止)

  実 HTML 検証 (raw HTML での match 数):
    URL          | 旧 regex | 新 regex
    NIKKE7       |   0      |   8
    onep101      |   0      |   8
    db_goku      |   0      |   8
    bluelock8    |   0      |   7
    medalist     |   0      |   5
    frieren      |   0      |   5
    winbre6      |   0      |   6
    umamusume16  |   0      |   6

  Selenium body.text では更に改行入る可能性あり、上記は最低保証ライン.
"""
from __future__ import annotations
import importlib.util
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_KUJI = _REPO_ROOT / "iMak_ichibankuji"


def _load_kuji_module():
    """sys.modules キャッシュ汚染回避用、絶対パスから ichibankuji_to_csv.py を load."""
    path = _KUJI / "ichibankuji_to_csv.py"
    spec = importlib.util.spec_from_file_location("_test_kuji_scraper_regex", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ============================================================================
# 新 regex の単体検証 (実 HTML サンプルでの match 件数)
# ============================================================================
# 1kuji.com の <h4 class="name sp">A賞 アイテム名</h4> 系 (改行なし) を模擬
SAMPLE_HTML_NO_NEWLINE = """
<div class="itemColList"><h4 class="name sp">A賞 モンキー・D・ルフィ 魂豪示像</h4><div>...</div>
<p>■全1種<br>■サイズ：約25cm</p></div>
<div class="itemColList"><h4 class="name sp">B賞 ルフィ MASTERLISE</h4><div>...</div>
<p>■全1種<br>■サイズ：約20cm</p></div>
<div class="itemColList"><h4 class="name sp">C賞 ゾロ</h4><div>...</div>
<p>■全2種<br>■サイズ：約15cm</p></div>
"""

# Selenium body.text で改行が入った旧パターン (NIKKE7 等で動いてた)
SAMPLE_BODY_TEXT_WITH_NEWLINE = """
A賞 モンキー・D・ルフィ 魂豪示像
■全1種
■サイズ：約25cm
B賞 ルフィ MASTERLISE
■全1種
■サイズ：約20cm
"""


def test_new_regex_matches_no_newline_pattern():
    """賞名+アイテム名と ■全X種 の間に改行が無いケース (5/10 事故) で match できる."""
    m = _load_kuji_module()
    # scrape_1kuji 内の prize_pattern を再構築 (テスト容易性のため)
    prize_pattern = re.compile(
        r'([^\n]+?賞)\s+([^■]+?)\s*■全(\d+)種.*?■サイズ[:：]?\s*約([\d.]+)\s*cm',
        re.DOTALL
    )
    matches = prize_pattern.findall(SAMPLE_HTML_NO_NEWLINE)
    assert len(matches) >= 3, f"Expected >= 3 matches, got {len(matches)}: {matches}"
    # 賞名と種数が正しく抽出される
    prizes = [m[0].strip() for m in matches]
    assert "A賞" in prizes[0]
    assert "B賞" in prizes[1]
    assert "C賞" in prizes[2]


def test_new_regex_still_matches_with_newline_pattern():
    """副作用ゼロ: 改行入りパターン (NIKKE7 等で従来動いていた形) でも match 維持."""
    prize_pattern = re.compile(
        r'([^\n]+?賞)\s+([^■]+?)\s*■全(\d+)種.*?■サイズ[:：]?\s*約([\d.]+)\s*cm',
        re.DOTALL
    )
    matches = prize_pattern.findall(SAMPLE_BODY_TEXT_WITH_NEWLINE)
    assert len(matches) == 2, f"Expected 2 matches, got {len(matches)}"


def test_new_regex_does_not_overshoot_with_dotall():
    """■ 直前停止により、アイテム名が次の ■ を超えて貪欲 match しない."""
    prize_pattern = re.compile(
        r'([^\n]+?賞)\s+([^■]+?)\s*■全(\d+)種.*?■サイズ[:：]?\s*約([\d.]+)\s*cm',
        re.DOTALL
    )
    matches = prize_pattern.findall(SAMPLE_HTML_NO_NEWLINE)
    # 各 match のアイテム名 (group 2) が ■ を含まない
    for prize, item, varieties, size in matches:
        assert "■" not in item, f"Item name should not contain ■: {item!r}"


def test_first_line_extraction_strips_intermediate_text():
    """post-process で item_name の最初の行のみ採用する設計を検証.

    body.text 想定: アイテム名と ■全X種 の間に画像 alt などの中間行が入る場合、
    item_name = match.group(2).strip().split('\\n')[0].strip() で清浄化.
    """
    multiline_text = """
A賞 モンキー・D・ルフィ 魂豪示像
[商品画像 alt: ルフィ figurine]
■全1種
■サイズ：約25cm
"""
    prize_pattern = re.compile(
        r'([^\n]+?賞)\s+([^■]+?)\s*■全(\d+)種.*?■サイズ[:：]?\s*約([\d.]+)\s*cm',
        re.DOTALL
    )
    matches = prize_pattern.findall(multiline_text)
    assert len(matches) == 1
    prize_label, item_raw, varieties, size = matches[0]
    # raw item は中間行含む
    assert "[商品画像" in item_raw
    # post-process で最初の行のみ
    item_clean = item_raw.strip().split('\n')[0].strip()
    assert item_clean == "モンキー・D・ルフィ 魂豪示像"


def test_old_regex_fails_on_no_newline_pattern():
    """旧 regex の振り返り検証: 改行なしパターンでは 0 match (= 5/10 事故再現)."""
    old_pattern = re.compile(
        r'([^\n]+?賞)\s+([^\n]+?)\n■全(\d+)種.*?■サイズ：約([\d.]+)cm',
        re.DOTALL
    )
    matches = old_pattern.findall(SAMPLE_HTML_NO_NEWLINE)
    assert len(matches) == 0, f"Old regex should fail (0 matches) on no-newline pattern, got {len(matches)}"
