#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_official.py — ガチャの公式商品ページを見に行く (2026-08-20)。

なぜ要るか:
    楽天の情報だけでは Item Specifics が埋まらない。実際、最初に出した5件は
    Character / Franchise / Series に **同じシリーズ名を3つとも入れて**しまい、
    Genre は空、Theme は中身と関係なく `Anime & Manga` 固定だった。
    公式には 商品名・説明・種類数・対象年齢・商品画像 が揃っている。

どこを見るか (実測 2026-08-20):
    - **バンダイ**: `gashapon.jp/products/detail.php?jan_code=<JAN>000` で商品ページに直行できる。
      JAN は中間スプシ H列の末尾に入っている (147/147件)。
      取れるもの: og:title / og:description / 発売時期 / 価格 / 種類数 / 対象年齢 /
      商品画像 (`bandai-a.akamaihd.net/bc/img/model/…` が商品写真。19枚取れた実績)
    - **タカラトミーアーツ・キタンクラブ・クオリア**: I列はメーカーのトップページで、
      商品ページではない。中身も JS 描画で HTTP では取れない。
      → **取れない物は取れないままにする** (推測で埋めない)。楽天の情報だけで作る。
"""
from __future__ import annotations

import re
import urllib.request

_UA = {"User-Agent": "Mozilla/5.0"}
BANDAI_DETAIL = "https://gashapon.jp/products/detail.php?jan_code=%s000"
# 商品写真だけ。ロゴ・アイコン・他商品のレコメンド枠は入れない。
_BANDAI_IMG = re.compile(r'https://bandai-a\.akamaihd\.net/bc/img/model/[^"\']+\.(?:jpg|png)')


def jan_from_text(text: str) -> str:
    """H列の商品説明末尾の `JAN: <番号>` を取る (純関数)。無ければ空。"""
    m = re.search(r"JAN[:：]\s*(\d{8,13})", text or "")
    return m.group(1) if m else ""


def official_url(jan: str, maker_url: str = "") -> str:
    """商品ページのURL。バンダイは JAN から作れる。それ以外は空 (トップページは返さない)。"""
    if jan and "gashapon.jp" in (maker_url or "gashapon.jp"):
        return BANDAI_DETAIL % jan
    return ""


def parse_bandai(html: str) -> dict:
    """バンダイ商品ページ → {name, desc, pieces, age, released, images} (純関数)。

    取れなかった項目は空にする。**推測で埋めない**。
    """
    if not html:
        return {}
    og = dict(re.findall(r'<meta property="og:(\w+)" content="([^"]*)"', html))
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                  re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)))

    def field(label, pat):
        m = re.search(label + r"\s*" + pat, flat)
        return m.group(1).strip() if m else ""

    pieces = ""
    m = re.search(r"種類数\D{0,8}全\s*(\d+)\s*種", flat)
    if m:
        pieces = m.group(1)
    return {
        "name": (og.get("title") or "").strip(),
        "desc": (og.get("description") or "").strip(),
        "pieces": pieces,
        # 「15才以上」だけを取る。後ろに続く注意書きを巻き込まない
        "age": field("対象年齢", r"(\d+\s*[才歳]以上)"),
        "released": field("発売時期", r"(\d{4}年\s*\d{1,2}月(?:\s*第\d週)?)"),
        "images": list(dict.fromkeys(_BANDAI_IMG.findall(html))),
    }


def fetch(url: str, timeout: int = 25) -> str:
    """HTML を取る。取れなければ空 (呼び側は「公式なし」として進む)。"""
    if not (url or "").startswith("http"):
        return ""
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                     timeout=timeout).read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("shift_jis", "replace")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 公式ページを読めず ({type(e).__name__}): {url[:70]}")
        return ""


def lookup(item: dict) -> dict:
    """1商品 → 公式から取れた情報。取れなければ {} (楽天の情報だけで進む)。"""
    jan = jan_from_text(item.get("desc_jp", ""))
    url = official_url(jan, item.get("official_url", ""))
    if not url:
        return {}
    info = parse_bandai(fetch(url))
    if info:
        info["url"] = url
        info["jan"] = jan
    return info
