#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_enrich.py — 公式+楽天の情報から、出品に要る英語の値を作る (2026-08-20)。

★なぜ分けたか: 最初に出した5件は Character / Franchise / Series に **同じシリーズ名を
  3つとも入れて**いた。Genre は空、Theme は中身と関係なく `Anime & Manga` 固定。
  eBay のフィルタにも買い手の検索語にも当たらない。項目ごとに何を入れるかを
  ここに1か所で書く。

★取れない項目は **空で返す**。埋まらない物は Item Specifics も空欄にする
  (推測で埋めない = 出品の正確性原則)。
"""
from __future__ import annotations

import json
import re

MODEL = "claude-opus-5"

_RULES = """- series_en: シリーズ名 (公式商品名の英語表記。公式に英語名があればそれを使う)
- maker_en: メーカー名の英語表記 (Bandai / Takara Tomy A.R.T.S / Kitan Club / Qualia 等)
- character_en: **登場するキャラクター名**。作品のキャラなら公式英語名 (例 Gojo Satoru)。
  キャラ物でなければ **空文字**。シリーズ名を入れてはいけない
- franchise_en: **元になった作品・ブランド名** (例 Jujutsu Kaisen / Sanrio / Lion Confectionery)。
  オリジナル商品なら **空文字**。シリーズ名を入れてはいけない
- theme: eBay の Theme。実態に合う語を1〜2個カンマ区切り
  (Anime & Manga / Food / Animals / Fashion / Nature / Vehicles / Music 等)。
  **アニメ作品でない物に Anime & Manga を付けない**
- genre: eBay の Genre。Animation / Collectible / Novelty から実態に合う物
- title_extra: eBay タイトルに足すと検索に効く英単語を2〜4語 (素材・形状・用途。
  例 Miniature Charm Keychain Food)。シリーズ名の繰り返しは不可"""

FIELDS = ("series_en", "maker_en", "character_en", "franchise_en",
          "theme", "genre", "title_extra")


def build_prompt(items: list) -> str:
    """商品リスト → 問い合わせ文 (純関数・test可)。"""
    blocks = []
    for i, it in enumerate(items):
        off = it.get("official") or {}
        b = [f"--- {i + 1}",
             f"楽天タイトル: {(it.get('title_jp') or '')[:110]}",
             f"メーカー: {it.get('maker_jp') or '(不明)'} / 全{it.get('pieces', '?')}種"]
        if off.get("name"):
            b.append(f"公式商品名: {off['name']}")
        if off.get("desc"):
            b.append(f"公式説明: {off['desc'][:300]}")
        if it.get("desc_jp"):
            b.append(f"ラインナップ: {it['desc_jp'][:300]}")
        blocks.append("\n".join(b))
    return (
        "日本のガチャポン (カプセルトイ) のコンプリートセットを eBay に出品します。\n"
        "各商品について、下の項目を英語で作ってください。\n\n"
        + _RULES + "\n\n"
        "分からない項目は **空文字**にしてください。推測で埋めないでください。\n\n"
        + "\n\n".join(blocks) + "\n\n"
        'JSON配列だけを返してください: '
        '[{"n":1,"series_en":"","maker_en":"","character_en":"","franchise_en":"",'
        '"theme":"","genre":"","title_extra":""}]')


def parse_reply(text: str, items: list) -> dict:
    """応答 → {url: {項目}} (純関数・test可)。読めなければ空。"""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return {}
    try:
        rows = json.loads(m.group(0))
    except Exception:                                           # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        try:
            i = int(r.get("n", 0)) - 1
        except Exception:                                       # noqa: BLE001
            continue
        if 0 <= i < len(items):
            out[items[i].get("url", "")] = {k: str(r.get(k) or "").strip() for k in FIELDS}
    return out


def enrich(items: list, api_key: str) -> dict:
    """公式+楽天 → 英語の値。取れなければ空 dict (呼び側は CSV を作らない)。"""
    if not items:
        return {}
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=api_key)
        r = client.messages.create(
            model=MODEL, max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": build_prompt(items)}])
        txt = next((b.text for b in r.content if b.type == "text"), "")
        return parse_reply(txt, items)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 英語の項目を作れず ({type(e).__name__}: {e})")
        return {}
