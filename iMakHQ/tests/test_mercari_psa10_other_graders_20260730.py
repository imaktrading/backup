# -*- coding: utf-8 -*-
"""mercari_psa_resource.is_psa10 — 他社鑑定 (CGC 等) を仕入元候補にしないこと.

背景 (2026-07-30 ユーザー報告):
    RESTOCK 視覚確証に **CGC の候補が出てくる**。メルカリは出品者が `CGC10 PSA10` と
    併記するため、`"PSA10" in name` だけでは通ってしまい、CGC スラブが PSA10 出品の
    仕入元候補になっていた。買って送れば **別商品** = SNAD → Defect Rate。
    2026-07-27 の PSA9 混入 4件END と同型。

守りたい性質:
  1. 他社鑑定 (CGC/SGC/AGS/HGA/BGS/ARS/BVG/GMA) は PSA10 併記でも弾く
  2. **カード名に埋もれた3文字で誤爆しない** (STARS→ARS / TAGS→AGS の潜在bug)
  3. Pokemon の "TAG TEAM" / "ACE SPEC" を落とさない (正当な供給を殺さない)
  4. 既存仕様 (PSA9/8/7・「相当」除外) を壊さない
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mercari_psa_resource import is_psa10  # noqa: E402


# ★実データ (psa_research_cache.json の mercari.all_cands) から採取した実物。
#   ここが通ると CGC スラブを PSA10 出品の仕入元にしてしまう。
REAL_WORLD_CGC = [
    "CGC10 PRISTINE金PSA10以上　　ナミ　EB03-053",
    "CGC10 PRISTINE金PSA10以上　ナミ　EB03-053",
    # ↓空白除去後に当てると CGCPRISTINE になり境界判定をすり抜けた形 (初版の穴)
    "CGC pristine PSA10 ワンピースデイ25 ルフィ P-110 ②",
]


@pytest.mark.parametrize("title", REAL_WORLD_CGC)
def test_real_world_cgc_rejected(title):
    """実キャッシュから採取した CGC 候補が確実に弾かれること."""
    assert is_psa10(title) is False, f"実データの CGC が通っている: {title}"


@pytest.mark.parametrize("title", [
    "CGC10 PSA10 ポケモンカード リザードン",          # ★報告された形 (併記)
    "PSA10 CGC 10 ワンピース ルフィ",
    "cgc pristine psa10 ルフィ",                     # 小文字
    "PSA10 ポケカ CGC",                              # 末尾
    "PSA10CGC10 まとめ",                             # 空白なし併記
    "ポケカ CGC9.5 PSA10相当なし",
    "SGC10 PSA10 遊戯王",
    "AGS 10 PSA10 ポケモンカード",
    "HGA10 PSA10 ドラゴンボール",
    "BGS9.5 PSA10 ポケカ",
    "ARS10 PSA10 ワンピース",
    "BVG 10 PSA10",
    "GMA10 PSA10",
])
def test_other_graders_rejected(title):
    assert is_psa10(title) is False, f"他社鑑定が通っている: {title}"


@pytest.mark.parametrize("title", [
    "PSA10 ポケモンカード リザードンVMAX",
    "PSA 10 ワンピース ルフィ OP13-118",
    "PSA10 SHINING STARS ピカチュウ",            # ★STARS に ARS が埋もれている
    "PSA10 POKEMON TAGS ホロ",                   # ★TAGS に AGS が埋もれている
    "PSA10 TAG TEAM GX ピカチュウ&ゼクロム",      # ★Pokemon の TAG TEAM
    "PSA10 ACE SPEC マスターボール",              # ★Pokemon の ACE SPEC
    "PSA10 VSTAR ユニバース アルセウス",
])
def test_legit_psa10_still_passes(title):
    assert is_psa10(title) is True, f"正当な PSA10 を弾いている: {title}"


@pytest.mark.parametrize("title,expected", [
    ("PSA9 ポケモンカード", False),
    ("PSA 8 ワンピース", False),
    ("PSA7 遊戯王", False),
    ("PSA10相当 未鑑定 ポケカ", False),   # 「相当」= 生カード
    ("PSA10 ポケカ", True),
])
def test_existing_rules_preserved(title, expected):
    assert is_psa10(title) is expected


def test_no_grade_marker_is_rejected():
    """鑑定表記が無いものは通さない (fail-closed)."""
    assert is_psa10("ポケモンカード リザードン 美品") is False
