#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログの引き方 — **ここが唯一の口**。

★2026-09-20 ユーザー「カタログの引き方に関して、ノウハウを蓄積しておかないとね」。
  それまで引き方は `market_ledger.py` の中にしか無く、他の道具は自前で引いていた。
  同じ失敗を各所で繰り返すので、**引き方はここ1本**にする。

■ なぜ要るか (1丁目1番地)

  「カタログに無い」と言う前に、**引き方を尽くしたか**を必ず確かめる。
  2026-09-20 の実測: 「カタログ要補充 17件」と出していたが、
  **16件はカタログに在った**。①データの不足ではなく ②引き方の不足だった。

    17件 → 7件  カード番号そのもので引く
     7件 → 2件  英語のカード名で決める
     2件 → 1件  eBay ライブ配信の日付を番号と読まない
  残る1件も カタログの不足ではなく、セラーが書いた番号の間違いだった。

■ 引く順番 (上から順に試す。当たったら止める)

  1. **product_id 完全一致** — 大文字小文字だけは問わない。
     カタログは `SV3a` `M2a` `SV11W` と小文字混じりで書く。大文字に潰すと当たらない。
  2. **弾コード + 番号** — 弾が枝分かれしている物 (SV11 → SV11W / SV11B) は
     **タイトルの和名**で決める。
  3. **英語のセット名 → 弾コード** — 市場のタイトルは弾コードを書かず
     "VSTAR Universe" のような英語のセット名だけのことが多い。
     カタログの `ebay_filter_map` が「S12a: Vstar Universe」の形で持っている。
  4. **カード番号そのもの** (specs の card_number_text) — 弾コードが分からなくても
     決まることが多い。複数に当たったら 和名 → **英語のカード名** → 弾コード →
     英語のセット名 の順で決める。
     ★市場のタイトルは英語なので **英語のカード名が一番効く**
     (Articuno → フリーザー / Radiant Greninja → かがやくゲッコウガ)。
     カタログは name_en を 22,435/22,492件 持っている。
  5. **決められなければ当てない** — 推測で当てると別のカードの値段を掴む。
     実例: 020/019 は マリィのモルペコ と ゲンガーVMAX が同じ番号で、
     ゲンガーの $2,475 を拾うと「8倍 値上げできる」に見えてしまう。

■ 番号を読む時の落とし穴

  - **"PSA10" の 10 を番号と読まない** (最初の実装は全部 -010 になった)
  - **年 (1900〜2100) を番号と読まない**
  - **eBay ライブ配信の日付を番号と読まない**
    ("ebay Live 07/25-021 [PSA10] Mega Gengar MA 230/193" の 07/25)

■ 画像を取る時の落とし穴

  - **先頭を無条件に使わない**。ワンピース / ドラゴンボールは
    [0] 英語版 / [1] 日本語版 の並びが多い (ワンピースは先頭が英語版 4,760件のうち
    4,591件が2枚目以降に日本語版を持つ)。**英語版でない最初の1枚**を選ぶ。
  - カタログが **PSA の鑑定画像しか持っていない**物がある (CLK-007)。
    これは ①カタログ側の不足。画面では「鑑定画像」と分かるように出す。

■ 使い方

    import catalog_lookup as CL
    conn = sqlite3.connect(CL.DB)
    row = CL.lookup(CL.candidates(key, title), conn, title)   # → (pid, name, name_jp, category, images) or None
    url = CL.first_image(row[4])
"""
import json
import os
import re
import sqlite3

DB = r"C:/dev/iMak_data/catalog/products.sqlite"

# ポケモンの形 (175/165 や 270/SM-P)
CARD_NO = re.compile(r"\b(\d{1,3}\s*/\s*(?:\d{1,3}|[A-Z]{1,3}-?[A-Z]?))\b")
# ワンピース / ドラゴンボールの形 (OP03-057 / ST21-015 / P-001 / FB02-119)
CARD_NO_DASH = re.compile(r"\b([A-Z]{1,4}\d{0,2}-\d{2,3})\b")
# タイトルの中の弾コード (SV2a / S12a / M2a / CLK / sv1a …)
SET_CODE = re.compile(r"\b((?:SV|S|M|CLK|SM|XY|BW|DP)[0-9]{0,2}[A-Z]?)\b", re.I)
# eBay のカタログが作ったタイトル ("… Pokemon Japanese Sv7-Stellar Miracle マホミル AR")
EBAY_SET = re.compile(r"JAPANESE\s+([A-Z]{1,3}[0-9]{1,2}[A-Z]?)-", re.I)
EBAY_NUM = re.compile(r"(?<![0-9/])(\d{2,3})(?![0-9/])")
# 「S12a: Vstar Universe」の形
SET_NAME = re.compile(r"^([A-Za-z0-9-]{2,8}):\s*(.+)$")

_SET_BY_NAME = {}


# ---- 番号を読む ----

def card_no(title):
    """タイトルからカード番号を取る (純関数)。取れなければ None。

    ★eBay のタイトルは書き方がばらばらなので、番号だけを鍵にする。弾コードは
      セラーによって付いたり付かなかったりするので、鍵にすると取りこぼす。
    """
    if not title:
        return None
    t = title.upper().replace(" /", "/").replace("/ ", "/")
    t = re.sub(r"EBAY\s*LIVE\s*\d{1,2}/\d{1,2}(-\d+)?", " ", t)   # 配信の日付は番号でない
    m = CARD_NO.search(t)
    if m:
        return m.group(1).replace(" ", "")
    m = CARD_NO_DASH.search(t)
    if m:
        return m.group(1)
    code, num = ebay_catalog_no(title)
    return f"{code.upper()}-{num}" if code else None


def ebay_catalog_no(title):
    """eBay カタログ形式のタイトル → (弾コード, 3桁番号) (純関数)。読めなければ (None, None)。"""
    t = title or ""
    m = EBAY_SET.search(t)
    if not m:
        return None, None
    clean = EBAY_SET.sub(" ", re.sub(r"PSA\s*10", "", t, flags=re.I))   # PSA10 の 10 は番号でない
    for n in EBAY_NUM.finditer(clean):
        v = int(n.group(1))
        if 1900 <= v <= 2100:              # 年は番号でない
            continue
        return m.group(1), "%03d" % v
    return None, None


def candidates(key, title):
    """カード番号 (と市場タイトル) から product_id の候補を作る (純関数)。"""
    if "/" not in key:
        return [key.upper()]                      # OP03-057 / P-043 はそのまま
    num, suffix = key.split("/", 1)
    if not suffix.isdigit():                      # 020/M-P → M-P-020
        return [f"{suffix.upper()}-{num}", key]
    out = []
    for m in SET_CODE.finditer(title or ""):      # 175/165 は弾コードをタイトルから拾う
        code = m.group(1)
        if code.upper() in ("M", "S", "SV"):      # 単独の文字は弾ではない
            continue
        out.append(f"{code}-{num}")
    out.append(key)                               # 番号そのものも残す (最後の手)
    return out


# ---- 引く ----

def set_code_by_name(conn):
    """{英語のセット名(小文字): 弾コード} をカタログから作る (I/O・1回だけ)。"""
    if _SET_BY_NAME:
        return _SET_BY_NAME
    try:
        rows = conn.execute(
            "SELECT DISTINCT ebay_value FROM ebay_filter_map WHERE field LIKE 'set%'"
        ).fetchall()
    except Exception:                                          # noqa: BLE001
        return _SET_BY_NAME
    for (v,) in rows:
        m = SET_NAME.match((v or "").strip())
        if m:
            _SET_BY_NAME.setdefault(m.group(2).strip().lower(), m.group(1))
    return _SET_BY_NAME


def set_code_from_title(title, conn):
    """タイトルの中の英語セット名 → 弾コード。見つからなければ None。長い名前を優先。"""
    t = (title or "").lower()
    best = None
    for name, code in set_code_by_name(conn).items():
        if len(name) >= 4 and name in t:
            if best is None or len(name) > len(best[0]):
                best = (name, code)
    return best[1] if best else None


def by_set_and_no(code, num, title, conn):
    """弾コード+番号 → product_id。枝分かれ (SV11W / SV11B) は和名で決める。"""
    rows = conn.execute(
        "SELECT product_id, name_jp FROM products WHERE product_id LIKE ?",
        ("%s%%-%s" % (code, num),)).fetchall()
    ok = [r for r in rows if re.fullmatch(code + "[A-Za-z]?", r[0].split("-")[0], re.I)]
    if len(ok) == 1:
        return ok[0][0]
    for pid, jp in ok:
        if jp and jp in (title or ""):
            return pid
    return None


def by_number_text(num_text, title, conn):
    """カード番号そのもの (specs の card_number_text) で引く。

    複数に当たったら 和名 → **英語のカード名** → 弾コード → 英語のセット名 で決める。
    決められなければ None (推測で別のカードを掴まない)。
    """
    rows = conn.execute(
        "SELECT product_id, name, name_jp, category, images, set_name, name_en FROM products "
        "WHERE specs LIKE ?", ('%"card_number_text": "' + num_text + '"%',)).fetchall()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0][:5]
    t = (title or "")
    tu = re.sub(r"[^A-Z0-9]", "", t.upper())
    for r in rows:
        if r[2] and r[2] in t:                       # 和名
            return r[:5]
    for r in sorted([r for r in rows if r[6]], key=lambda r: -len(r[6])):
        if re.sub(r"[^A-Z0-9]", "", r[6].upper()) in tu:    # 英語のカード名 (一番効く)
            return r[:5]
    for r in rows:
        code = re.sub(r"[^A-Z0-9]", "", r[0].split("-")[0].upper())
        if code and code in tu:                      # 弾コード
            return r[:5]
    code = set_code_from_title(t, conn)
    if code:
        cu = re.sub(r"[^A-Z0-9]", "", code.upper())
        for r in rows:
            if re.sub(r"[^A-Z0-9]", "", r[0].split("-")[0].upper()) == cu:
                return r[:5]
    return None


def lookup(cands, conn, title=""):
    """候補 → カタログの行 (product_id, name, name_jp, category, images)。引けなければ None。

    上の docstring「引く順番」のとおりに試す。**名前で探し回らない**
    (綴りの大小だけは問わない = 同じ物なので)。
    """
    for pid in cands:
        row = conn.execute(
            "SELECT product_id, name, name_jp, category, images FROM products "
            "WHERE product_id = ? COLLATE NOCASE", (pid,)).fetchone()
        if row:
            return row
    for pid in cands:
        m = re.fullmatch(r"([A-Za-z]{1,3}\d{1,2}[A-Za-z]?)-(\d{2,3})", pid or "")
        if not m:
            continue
        got = by_set_and_no(m.group(1), m.group(2), title, conn)
        if got:
            return _row(got, conn)
    num = ""
    for pid in cands:
        m = re.search(r"-(\d{2,3})$", pid or "")
        if m:
            num = m.group(1)
            break
    if not num:
        m = re.match(r"^(\d{1,3})/", (cands[0] if cands else "") or "")
        num = ("%03d" % int(m.group(1))) if m else ""
    if num:
        code = set_code_from_title(title, conn)
        if code:
            got = by_set_and_no(code, num, title, conn)
            if got:
                return _row(got, conn)
    for pid in (cands or []):
        if "/" in (pid or ""):
            got = by_number_text(pid, title, conn)
            if got:
                return got
    return None


def _row(pid, conn):
    return conn.execute(
        "SELECT product_id, name, name_jp, category, images FROM products WHERE product_id=?",
        (pid,)).fetchone()


# ---- 画像 ----

def is_en_image(url):
    """英語版のカード画像か (純関数)。バンダイの画像は入れ物の名前で分かる。"""
    u = (url or "").upper()
    return "-EN/" in u or "/EN_" in u


def is_cert_image(url):
    """PSA の鑑定画像か (純関数)。カタログが実物写真しか持っていない印 = ①カタログ側の不足。"""
    return "d1htnxwo4o0jhw.cloudfront.net/cert/" in (url or "")


def first_image(images_json):
    """カタログの images → **日本語版の**画像URL (純関数)。無ければ先頭。"""
    try:
        v = json.loads(images_json) if isinstance(images_json, str) else images_json
    except Exception:                                          # noqa: BLE001
        return ""
    if isinstance(v, str):
        return v
    if not isinstance(v, list) or not v:
        return ""
    for u in v:
        if u and not is_en_image(u):
            return str(u)
    return str(v[0])


def spec_of(specs_json, key):
    """specs (JSON) から1つ取り出す (純関数)。"""
    try:
        d = json.loads(specs_json) if isinstance(specs_json, str) else (specs_json or {})
    except Exception:                                          # noqa: BLE001
        return ""
    return str(d.get(key) or "") if isinstance(d, dict) else ""


if __name__ == "__main__":
    import sys
    t = " ".join(sys.argv[1:]) or "PSA10 GEM MINT Articuno 009/032 Pokemon TCG Classic"
    k = card_no(t)
    conn = sqlite3.connect(DB)
    row = lookup(candidates(k, t), conn, t) if k else None
    print("タイトル:", t)
    print("番号    :", k)
    print("カタログ:", row[:4] if row else "引けませんでした")
    if row:
        print("画像    :", first_image(row[4]))
