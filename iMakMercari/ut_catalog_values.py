#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目視で特定した UT の行に、**カタログの値**を写すための変換 (2026-09-11)。

ユーザー「カタログの値」(= 写真から AI に推測させず、カタログの値を写す)。
特定は `iMakHQ/tools/ut_identify.py` (人の目視) で行い、結果は台帳 `ut_identity.json` にある。

写すもの: 色 / 素材 / 原産国 / フィット / 性別 / キャラ・シリーズ / テーマ / 商品番号 / サイズ表 / JP→US サイズ
英語タイトルは出品くん側の仕事 (カタログに英語は無い)。

★守ること
- **日本語を出品に1文字も出さない**。訳が辞書に無い語が来たら、その行は出さない
  (skill apparel-tee-listing「翻訳辞書に無い語が来たら変換せず停止する。黙って日本語を通さない」)
- 原産国が2か国ある商品は Item Specifics を空欄、説明文に両方書く (2026-09-09 決定)
- 判らない値は空 (推測で埋めない)
"""
from __future__ import annotations

import html as _html
import json
import re
import sqlite3
import unicodedata

DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"
LEDGER = r"C:/dev/iMak_data/hq/ut_identity.json"

FIBER_EN = {"綿": "Cotton", "コットン": "Cotton", "ポリエステル": "Polyester",
            "ポリウレタン": "Polyurethane", "レーヨン": "Rayon", "ナイロン": "Nylon",
            "アクリル": "Acrylic", "麻": "Linen", "毛": "Wool", "キュプラ": "Cupro"}
EBAY_MATERIAL = {"Rayon": "Viscose"}      # 説明文は Rayon のまま、Item Specifics だけ eBay の語
COUNTRY_EN = {"VN": "Vietnam", "CN": "China", "MY": "Malaysia", "BD": "Bangladesh",
              "IN": "India", "ID": "Indonesia", "KH": "Cambodia", "TH": "Thailand",
              "MM": "Myanmar", "LK": "Sri Lanka", "PK": "Pakistan", "TR": "Turkey", "JP": "Japan"}
DEPT = {"men": "Men", "unisex": "Unisex Adults", "男女兼用": "Unisex Adults"}   # これ以外は出さない
JP_TO_US = {"S": "XS", "M": "S", "L": "M", "XL": "L", "XXL": "XL", "3XL": "2XL", "4XL": "3XL"}
_SIZE_RE = re.compile(r"(?<![A-Z0-9])(4XL|3XL|2XL|XXL|XL|XS|S|M|L)(?![A-Z])")


class NotListable(ValueError):
    """この行はカタログの値では出せない (理由をそのまま人に見せる)。"""


# ── 純関数 ──────────────────────────────────────────────────────────
def jp_size(text):
    """「XL(LL)」「3XL(4L)」「M」→ カタログのサイズ名 (2XL は XXL)。取れなければ ""。純関数。"""
    m = _SIZE_RE.search((text or "").upper())
    if not m:
        return ""
    return {"2XL": "XXL"}.get(m.group(1), m.group(1))


def main_material(composition):
    """公式の組成 → (Item Specifics の Material, 説明文の1行)。**本体だけ**を見る。純関数。

    例: 「本体:綿100%,リブ部分:綿71%・ポリエステル29%(…)」→ ("Cotton", "100% Cotton")
        「88% ポリエステル, 12% ポリウレタン」→ ("Polyester Blend", "88% Polyester, 12% Polyurethane")
    訳せない語・色ごとに組成が違う商品は NotListable。
    """
    s = unicodedata.normalize("NFKC", _html.unescape(composition or ""))   # ％ ， &reg; を揃える
    # 「当商品は以下どちらかの組成商品をお送りいたします」= 候補が複数。全部同じ時だけ採る
    if "どちらか" in s or "いずれか" in s:
        alts = [a for a in re.split(r"<br\s*/?>", s) if "%" in a]
        got = {main_material(a) for a in alts}
        if len(got) != 1:
            raise NotListable("組成が2通りあり、どちらが届くか決められない")
        return got.pop()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[(（][^)）]*[)）]", "", s)                   # (リサイクル…使用) 等の注記
    if not s.strip() or not re.search(r"\d", s):
        raise NotListable("素材がカタログに無い")
    if "[" in s:
        raise NotListable("色ごとに素材が違う商品 (どの色の組成か決められない)")
    # 部位の区切り (「, リブ部分:」「/ リブ部分:」) で切る。数字の途中 (「88%, 12%」) では切らない
    parts = [p.strip() for p in re.split(r"[,、/／]\s*(?=[^\d%,]*[:：])", s) if p.strip()]
    main = next((p for p in parts if re.match(r"^\s*本体\s*[:：]", p)), parts[0])
    main = re.sub(r"^[^:：\d]*[:：]", "", main).strip()
    pairs = re.findall(r"([^\d%・,/\s]+)\s*(\d+)\s*%", main) or \
        [(f, n) for n, f in re.findall(r"(\d+)\s*%\s*([^\d%・,/\s]+)", main)]
    if not pairs:
        raise NotListable(f"素材を読めない: {main[:30]}")
    out = []
    for fib, pct in pairs:
        fib = fib.strip("・ ")
        en = FIBER_EN.get(fib)
        if not en:
            raise NotListable(f"素材の訳が辞書に無い: {fib} (ut_catalog_values.FIBER_EN に足す)")
        out.append((int(pct), en))
    out.sort(key=lambda x: -x[0])
    line = ", ".join(f"{p}% {en}" for p, en in out)
    # ★Item Specifics は eBay の選択肢の語で (2026-09-11 Taxonomy API 15687 で確認):
    #   Rayon は無く Viscose / 混紡の値は Cotton Blend と Polyester Blend だけ
    prim = out[0][1]
    ebay_prim = EBAY_MATERIAL.get(prim, prim)
    if len(out) == 1 and out[0][0] == 100:
        spec = ebay_prim
    elif prim in ("Cotton", "Polyester"):
        spec = f"{prim} Blend"
    else:
        spec = ebay_prim
    return spec, line


def country_value(v):
    """CSV の C:Country of Origin に入れてよい値か (eBay の国名リストにある物だけ)。純関数。

    ★"Does not apply" は Tシャツ (15687) の選択肢に無い (2026-09-11 Taxonomy API で確認)。
      写真から読んだ値もここを通す = 知らない国名は空欄。
    """
    v = (v or "").strip()
    return v if v in set(COUNTRY_EN.values()) else ""


def origin(codes):
    """国コード配列 → (Item Specifics の値, 説明文の文)。2か国以上は Item Specifics 空。純関数。"""
    names = [COUNTRY_EN.get(c) for c in (codes or [])]
    if not names or any(n is None for n in names):
        return "", ""                                          # 判らない国は書かない
    if len(names) == 1:
        return names[0], names[0]
    return "", " or ".join(names) + " (the manufacturer produces this item in more than one country)"


def chart_row(size_chart_inch, size):
    """サイズ表 (inch) から JP サイズの行 (無ければ None)。純関数。"""
    for r in size_chart_inch or []:
        if (r.get("size") or "").upper() == size:
            return r
    return None


def chart_html(row, size_jp):
    """実寸の1行を説明文用 HTML に (英語だけ)。純関数。"""
    if not row:
        return ""
    lab = {"length": "Body Length", "shoulder": "Shoulder Width", "chest": "Body Width (Chest)",
           "sleeve": "Sleeve Length"}
    items = "".join(f"<li><b>{lab[k]}:</b> {row[k]} in</li>" for k in lab if row.get(k))
    return (f"<p><strong>Actual measurements (Japan size {size_jp}, laid flat, official UNIQLO "
            f"data)</strong></p><ul>{items}</ul>") if items else ""


def build_values(product, color_name, size_text):
    """カタログの1商品 + 選んだ色 + メルカリのサイズ → 出品に写す値 (dict)。純関数。

    戻り keys: specs (Item Specifics の上書き) / size_jp / size_us / material_line /
               origin_line / chart_html / collab_jp / is_gu
    出せない時は NotListable (理由付き)。
    """
    s = product["specs"]
    if product.get("category") == "gu":
        # whitelist_registry "tshirt" の Brand は Uniqlo だけ (strict)。GU を出すなら先にそこを決める
        raise NotListable("GU は Tシャツ新規の対象外 (Brand の決まりが UNIQLO 専用)")
    gender = (s.get("gender") or "").strip()
    dept = DEPT.get(gender.lower()) or DEPT.get(gender)
    if not dept:
        raise NotListable(f"性別 {gender or '?'} はこのカテゴリ (Men's 15687) では出さない")
    col = next((c for c in s.get("color_variants") or [] if c.get("name") == color_name), None)
    if not col or not col.get("ebay_color"):
        raise NotListable(f"色 {color_name} がカタログの色に無い")
    size = jp_size(size_text)
    if not size:
        raise NotListable(f"サイズを読めない: {size_text!r}")
    mat_spec, mat_line = main_material(s.get("composition"))
    coo_spec, coo_line = origin(s.get("countries_of_origin"))
    is_gu = product.get("category") == "gu"
    specs = {"Color": col["ebay_color"], "Material": mat_spec, "Department": dept,
             "Model": str(s.get("l1_id") or ""),
             "Country/Region of Manufacture": coo_spec,
             "Brand": "GU" if is_gu else "Uniqlo",
             "Product Line": "GU" if is_gu else "Uniqlo UT"}
    if s.get("fit"):
        specs["Fit"] = s["fit"]
    if s.get("character_family"):
        specs["Character Family"] = s["character_family"]
    if s.get("character"):
        specs["Character"] = s["character"]
    if s.get("themes"):
        specs["Theme"] = ", ".join(s["themes"])
    return {"specs": specs, "size_jp": size, "size_us": JP_TO_US.get(size, ""),
            "material_line": mat_line, "origin_line": coo_line,
            "chart_html": chart_html(chart_row(s.get("size_chart_inch"), size), size),
            "collab_jp": s.get("collab") or product.get("name") or "", "is_gu": is_gu}


def catalog_facts_text(v):
    """Claude にタイトルを書かせる時に渡す事実 (英語)。純関数。"""
    sp = v["specs"]
    fam = sp.get("Character Family", "")
    return ("Catalog facts (authoritative — use these, do not contradict them):\n"
            f"- Brand line: {'UNIQLO GU' if v['is_gu'] else 'UNIQLO UT'}\n"
            f"- Color: {sp['Color']}\n"
            f"- Size: JP {v['size_jp']}" + (f" (US {v['size_us']})" if v['size_us'] else "") + "\n"
            + (f"- Series / franchise: {fam}\n" if fam else "")
            + (f"- Character: {sp['Character']}\n" if sp.get("Character") else "")
            + f"- Official Japanese product name (for identifying the work only): {v['collab_jp']}\n")


# ── 読み込み (I/O) ──────────────────────────────────────────────────
def load_ledger(path=LEDGER):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_product(product_id, db=DB_PATH):
    con = sqlite3.connect(db)
    try:
        r = con.execute("select category, product_id, name, specs from products "
                        "where product_id=? and category in ('uniqlo_ut','gu')", (product_id,)).fetchone()
    finally:
        con.close()
    if not r:
        return None
    try:
        specs = json.loads(r[3] or "{}")
    except ValueError:
        specs = {}
    return {"category": r[0], "product_id": r[1], "name": r[2] or "", "specs": specs}


def values_for_url(url, size_text, ledger=None):
    """その仕入元URLが目視で特定済みなら、写す値 (dict)。特定されていなければ None。

    特定済みなのに写せない時は NotListable (推測に戻さない = その行は出さない)。
    """
    led = ledger if ledger is not None else load_ledger()
    e = led.get((url or "").strip())
    if not e or e.get("decision") != "go":
        return None
    p = load_product(e.get("product_id") or "")
    if not p:
        raise NotListable(f"特定した商品 {e.get('product_id')} がカタログに無い")
    v = build_values(p, e.get("color") or "", size_text or e.get("size") or "")
    v["product_id"] = p["product_id"]
    return v


def apply_to_specs(specs, v, validate):
    """Claude の Item Specifics に カタログの値を上書き → 検証後の specs。純関数寄り。

    validate: whitelist_registry.validate_and_normalize (test で差し替え可)。
    カタログから写した **単一値の決まった項目** が外れたら NotListable
    (写し方の誤り = 推測値に戻さず出さない)。複数値 (Theme) は合わない値が落ちるだけ。
    """
    out = dict(specs or {})
    out.update(v["specs"])
    normalized, viol = validate(out, "tshirt")
    bad = [(f, o) for f, o, _e, _r in viol if f in v["specs"] and f not in ("Theme", "Material", "Fit")]
    if bad:
        raise NotListable("カタログの値が eBay の決まりに合わない: "
                          + ", ".join(f"{f}={o}" for f, o in bad))
    return normalized
