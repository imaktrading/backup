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
import os
import re
import sqlite3
import unicodedata

DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"
LEDGER = r"C:/dev/iMak_data/hq/ut_identity.json"
TITLE_NAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ut_title_names.yaml")


# ── 作品名の英語表記 (№138) ─────────────────────────────────────────
_WORKS = None


def load_works(path=TITLE_NAMES):
    """ut_title_names.yaml の works (日本語/英語キー → 公式英語表記)。"""
    global _WORKS
    if _WORKS is not None and path == TITLE_NAMES:
        return _WORKS
    import yaml
    with open(path, encoding="utf-8") as f:
        works = (yaml.safe_load(f) or {}).get("works") or {}
    works = {str(k): str(v) for k, v in works.items() if k and v}
    if path == TITLE_NAMES:
        _WORKS = works
    return works


def _nk(s):
    """照合用 (全角半角・大小・空白・記号を無視)。純関数。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s・･=＝×☆―\-:：!！'’【】「」()（）]+", "", s)


def work_name_en(texts, works):
    """商品の文字列群 → 作品の公式英語表記 (表に無ければ "")。**長いキーから先に**当てる。純関数。"""
    t = _nk(" ".join(x for x in texts if x))
    for k in sorted(works, key=lambda k: -len(_nk(k))):
        nk = _nk(k)
        if nk and nk in t:
            return works[k]
    return ""


def title_has(title, name):
    """タイトルにその英語名が入っているか (大小・アクセント・記号を無視)。純関数。"""
    def f(s):
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "", s.lower())
    return bool(name) and f(name) in f(title)

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
    """「XL(LL)」「3XL(4L)」「M」→ カタログのサイズ名 (2XL は XXL)。取れなければ ""。純関数。

    ★2026-09-12: メルカリのサイズ欄が空で、タイトルにしか書かれていない出品がある
      (「…Tシャツ XL」「Mサイズ」)。タイトルからも読むが、**違うサイズが2つ以上**書いてある時は
      決められないので "" (推測しない = その行は出さない)。
    """
    found = {{"2XL": "XXL"}.get(s, s) for s in _SIZE_RE.findall((text or "").upper())}
    return found.pop() if len(found) == 1 else ""


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
    # №138: 作品名は表で公式英語表記に同定する。表に無ければ出さない (綴りのブレを止める)
    work = work_name_en([s.get("collab"), s.get("collab_official_name"), product.get("name"),
                         s.get("character_family")], load_works())
    if not work:
        raise NotListable(f"作品名が対応表に無い: {(s.get('collab') or product.get('name') or '')[:30]} "
                          f"→ iMakMercari/ut_title_names.yaml に公式の英語表記を足す")
    is_gu = product.get("category") == "gu"
    specs = {"Color": col["ebay_color"], "Material": mat_spec, "Department": dept,
             "Model": str(s.get("l1_id") or ""),
             "Country/Region of Manufacture": coo_spec,
             "Brand": "GU" if is_gu else "Uniqlo",
             "Product Line": "GU" if is_gu else "Uniqlo UT"}
    if s.get("fit"):
        specs["Fit"] = s["fit"]
    specs["Character Family"] = work
    if s.get("character"):
        specs["Character"] = s["character"]
    if s.get("themes"):
        specs["Theme"] = ", ".join(s["themes"])
    return {"specs": specs, "size_jp": size, "size_us": JP_TO_US.get(size, ""),
            "product_id": product.get("product_id", ""), "color_name": color_name,
            "material_line": mat_line, "origin_line": coo_line,
            "chart_html": chart_html(chart_row(s.get("size_chart_inch"), size), size),
            "collab_jp": s.get("collab") or product.get("name") or "", "is_gu": is_gu,
            "work_en": work}


# ── 二重出品を止める (PSA と同じ運用。設計: iMakHQ/UT_FLOW.md) ──────
COL_URL, COL_ITEMID = 0, 1
COL_AUX_START, AUX_MAX = 28, 5          # AC..AG = 補URL 1..5


def l1_of(pid):
    """カタログの商品ID → 公式の商品番号6桁 (E486159-000 → 486159)。純関数。"""
    m = re.search(r"(\d{6})", pid or "")
    return m.group(1) if m else ""


KEY_PREFIX = "uniqlo_ut:"
# 仕入元URL から作った古い値。カタログの KEY ではないので、上から書いてよい
_SUPPLY_KEY_PREFIXES = ("item:", "shops:")


def needs_catalog_key(key_value):
    """その AI列の値は **カタログの KEY に入れ替えるべきか** (純関数・test 可)。

    ★2026-09-12: 目視の画面と KEY を書く道具で判定が食い違っていた。
      画面は `item:` / `shops:` の行を「KEY が無い」として出していたのに、書く側は
      「値が入っているから触らない」で飛ばしていた。目視しても何も書かれない = 徒労。
      判定はここ1か所に置く。

    True になるのは 空 と 仕入元URL由来の古い値だけ。`uniqlo_ut:` や人が入れた値は触らない。
    """
    k = (key_value or "").strip()
    if not k:
        return True
    return k.startswith(_SUPPLY_KEY_PREFIXES)


def identity_key(pid, color_name, size_jp, size_us=""):
    """canonical KEY。**1出品 = 1色1サイズ** なので色とサイズまで入れる (純関数)。

    例: `uniqlo_ut:486159:WHITE:L`

    ★2026-09-12 ユーザー「仕入元URLの下何桁かと商品番号の組み合わせにするなり、作り出せばいいやろ」:
      重複くんが **入稿CSVから同じ値を作れる**形にした。CSV には
      `C:Model`=商品番号6桁 / `C:Color`=色 / `C:Size`=USサイズ が既に入っている。
      カタログ側 (商品ID・カタログの色名・JPサイズ) から作っても同じ文字列になる。
    """
    l1 = l1_of(pid) or (pid or "").strip()
    us = (size_us or JP_TO_US.get((size_jp or "").upper(), "")).upper()
    if not (l1 and color_name and us):
        return ""
    return f"uniqlo_ut:{l1}:{color_name.upper()}:{us}"


def key_from_csv_row(model, color, size):
    """入稿CSV の1行 (C:Model / C:Color / C:Size) → KEY。重複くんが使うのと同じ作り (純関数)。"""
    return identity_key(model, color, "", size_us=size)


_EBAY_COLOR_CACHE = {}


def ebay_color_of(pid, color_name, load=None):
    """カタログの色名 → 出品に出す色 (eBay の値)。分からなければ元の名前。

    ★カタログは "LIGHT BLUE"、出品に出すのは "Blue" のことがある。KEY は **出品に出す色**で
      揃える (入稿CSV の C:Color と同じ値でないと、重複くんが同じ KEY を作れない)。
    """
    k = (pid, color_name)
    if k not in _EBAY_COLOR_CACHE:
        p = (load or load_product)(pid)
        cv = next((c for c in ((p or {}).get("specs") or {}).get("color_variants") or []
                   if c.get("name") == color_name), None)
        _EBAY_COLOR_CACHE[k] = (cv or {}).get("ebay_color") or color_name
    return _EBAY_COLOR_CACHE[k]


def identity_key_of(entry, size_jp="", load=None):
    """台帳の1件 (商品番号・カタログの色名・サイズ) → KEY。色は出品に出す値に直す。"""
    e = entry or {}
    pid = e.get("product_id") or ""
    color = ebay_color_of(pid, e.get("color") or "", load=load)
    return identity_key(pid, color, size_jp or jp_size(e.get("size") or ""))


def listed_identities(rows2d, ledger):
    """商品管理シート → {KEY: {"row": 行番号, "item_id":…, "aux": [補URL…]}} (純関数)。

    出品済み (B列に itemID がある) かつ 目視で特定済み (台帳にある) 行だけ。
    """
    out = {}
    for i, r in enumerate(rows2d[1:], start=2):
        if len(r) <= COL_ITEMID or not (r[COL_ITEMID] or "").strip():
            continue
        e = (ledger or {}).get((r[COL_URL] or "").strip())
        if not e or e.get("decision") != "go":
            continue
        key = identity_key_of(e, jp_size(e.get("size") or ""))
        if not key:
            continue
        aux = [u.strip() for u in r[COL_AUX_START:COL_AUX_START + AUX_MAX] if u.strip()] \
            if len(r) > COL_AUX_START else []
        out[key] = {"row": i, "item_id": r[COL_ITEMID].strip(), "aux": aux}
    return out


# 公式仕入の出品 (バリエーション出品) を追う表。出品ID → 公式URL / SKUごとの 色・サイズ・在庫
OFFICIAL_SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
OFFICIAL_MAIN_TAB, OFFICIAL_SKU_TAB = "シート1", "SKU詳細"


def official_identities(main_rows, sku_rows):
    """公式仕入の出品 → {KEY: {"item_id", "size", "color", "official_stock"}} (純関数)。

    ★2026-09-12 ユーザー「公式在庫をどうするかだね」「SKUあるけど」:
      公式仕入の出品は eBay 側に商品番号を持たない (SKU は "UNIQLO official website"、
      バリエーションの SKU は UUID) が、
        シート1: 出品ID → 公式URL (= 商品番号)
        SKU詳細: 出品ID → バリエーションごとの 色・サイズ・仕入元在庫 (監視くんが毎日更新)
      の2つを突き合わせれば、**メルカリ仕入と同じ KEY** を機械で作れる。
      これで「公式仕入で出している物を、メルカリ仕入でもう1本出す」を止められる。
    """
    pid_by_item = {}
    for r in main_rows[1:] if main_rows else []:
        item = (r[2] if len(r) > 2 else "").strip()
        m = re.search(r"/products/(E\d{6})", r[5] if len(r) > 5 else "")
        if item and m:
            pid_by_item[item] = m.group(1)
    out = {}
    for r in sku_rows[1:] if sku_rows else []:
        item = (r[3] if len(r) > 3 else "").strip()
        pid = pid_by_item.get(item)
        if not pid:
            continue
        size_jp = (r[6] if len(r) > 6 else "").strip()
        color = (r[7] if len(r) > 7 else "").strip()
        key = identity_key(pid, color, size_jp)
        if key:
            out[key] = {"item_id": item, "size": size_jp, "color": color,
                        "official_stock": (r[8] if len(r) > 8 else "").strip()}
    return out


def load_official_identities(sheet_id=OFFICIAL_SHEET_ID):
    """公式在庫の表2つを読んで KEY 一覧にする (I/O)。読めなければ {} (止めない)。"""
    try:
        import sys as _sys
        _sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
        import sheet_io
        return official_identities(sheet_io.read_tab(OFFICIAL_MAIN_TAB, sheet_id=sheet_id),
                                   sheet_io.read_tab(OFFICIAL_SKU_TAB, sheet_id=sheet_id))
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ 公式在庫の表を読めませんでした ({type(e).__name__}: {e}) → 公式との重複は見ません")
        return {}


def merge_aux(existing, url, max_n=AUX_MAX):
    """補URL に1本足す (既にあれば そのまま / 5本埋まっていたら足さない)。純関数。"""
    urls = [u for u in (existing or []) if u.strip()]
    if url and url not in urls and len(urls) < max_n:
        urls = urls + [url]
    return urls


def write_aux(row_to_urls):
    """補URL列 (AC-AG) に書く (I/O)。書けなければ 0 を返し、本処理は止めない。"""
    if not row_to_urls:
        return 0
    try:
        import sys as _sys
        _sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
        import sheet_io
        return sheet_io.write_aux_urls(row_to_urls)
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ 補URL を書けませんでした ({type(e).__name__}: {e})")
        return 0


def catalog_facts_text(v):
    """Claude にタイトルを書かせる時に渡す事実 (英語)。純関数。"""
    sp = v["specs"]
    return ("Catalog facts (authoritative — use these, do not contradict them):\n"
            f"- Brand line: {'UNIQLO GU' if v['is_gu'] else 'UNIQLO UT'}\n"
            f"- Color: {sp['Color']}\n"
            f"- Size: JP {v['size_jp']}" + (f" (US {v['size_us']})" if v['size_us'] else "") + "\n"
            + f"- Series / franchise (put this EXACT English name in the title, spelled as given): "
              f"{v['work_en']}\n"
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
        r = con.execute("select category, product_id, name, specs, images from products "
                        "where product_id=? and category in ('uniqlo_ut','gu')", (product_id,)).fetchone()
    finally:
        con.close()
    if not r:
        return None
    try:
        specs = json.loads(r[3] or "{}")
    except ValueError:
        specs = {}
    try:
        images = json.loads(r[4] or "[]") or specs.get("image_urls") or []
    except ValueError:
        images = specs.get("image_urls") or []
    return {"category": r[0], "product_id": r[1], "name": r[2] or "", "specs": specs,
            "images": [u for u in images if isinstance(u, str) and u.strip()]}


def decision_for(url, ledger=None):
    """その仕入元URLの目視の結論 ("go"/"skip"/"out"/"nocat")。まだなら ""。純関数寄り。"""
    led = ledger if ledger is not None else load_ledger()
    return ((led.get((url or "").strip()) or {}).get("decision") or "")


def values_for_url(url, size_text, ledger=None, title=""):
    """その仕入元URLが目視で特定済みなら、写す値 (dict)。特定されていなければ None。

    size_text: シートのサイズ欄。空なら台帳のサイズ、それも空なら **タイトル** から読む。
    特定済みなのに写せない時は NotListable (推測に戻さない = その行は出さない)。
    """
    led = ledger if ledger is not None else load_ledger()
    e = led.get((url or "").strip())
    if not e or e.get("decision") != "go":
        return None
    p = load_product(e.get("product_id") or "")
    if not p:
        raise NotListable(f"特定した商品 {e.get('product_id')} がカタログに無い")
    size = next((s for s in (size_text, e.get("size"), title) if jp_size(s or "")), "")
    v = build_values(p, e.get("color") or "", size)
    v["product_id"] = p["product_id"]
    # ★2026-09-13: 画像は **カタログが主役**。目視で「使わない」と外した画像も一緒に持つ
    v["catalog_images"] = p.get("images") or []
    v["color_codes"] = {c.get("name"): c.get("displayCode") for c in
                        (p["specs"].get("color_variants") or []) if c.get("name")}
    v["l1"] = str(p["specs"].get("l1_id") or "")
    v["img_drop"] = list(e.get("img_drop") or [])
    return v


# ★2026-09-13 ユーザー確定: 「出品者の画像は、使うなら最後の方で使う。メインはカタログ画像を」。
#   並びはルールで固定し、目視では **使わない画像を外すだけ** (毎回 順番を選ばせると目視が重くなる)。
#     1. 目視で選んだ色の、カタログの表 (メイン)
#     2. カタログのサブ画像 (背面・着用)。**他の色の表は入れない** (別の色が届くと思われる)
#     3. 仕入元 (メルカリ) の写真 — タグ・現物
#   eBay の上限に合わせて最大12枚。色見本 (chip) は画像ではないので入れない。
MAX_PICTURES = 12
_RE_GOODS = re.compile(r"goods_(\d{2})_(\d{6})")


def listing_images(catalog_images, color_code="", l1="", other_codes=(), seller_urls=(),
                   drop=(), max_n=MAX_PICTURES):
    """出品に使う画像 URL の並び (純関数)。"""
    dropped = {(u or "").strip() for u in (drop or ()) if u}
    others = {c for c in (other_codes or ()) if c and c != color_code}
    main, sub = [], []
    for u in catalog_images or ():
        u = (u or "").strip()
        if not u or "chip" in u.lower():
            continue
        m = _RE_GOODS.search(u)
        if m and (not l1 or m.group(2) == l1) and color_code:
            if m.group(1) == color_code:
                main.append(u)
                continue
            if m.group(1) in others:
                continue                    # 他の色の表
        sub.append(u)
    out, seen = [], set()
    for u in main + sub + [(x or "").strip() for x in (seller_urls or ())]:
        if u and u not in seen and u not in dropped:
            seen.add(u)
            out.append(u)
    return out[:max_n]


def images_for_listing(v, seller_urls=()):
    """目視で特定した行の値 (values_for_url) → 出品に使う画像の並び。"""
    codes = v.get("color_codes") or {}
    return listing_images(v.get("catalog_images") or [], codes.get(v.get("color_name")) or "",
                          v.get("l1") or "", list(codes.values()), seller_urls,
                          v.get("img_drop") or [])


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
