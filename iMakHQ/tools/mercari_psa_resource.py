#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ RESTOCK PSA の再仕入れ可否を判定 (メルカリ価格の技を借用)。

技の借用元:
  - メルカリ検索→価格抽出: iMakMercari/mercari_scout.scrape_search_results と同手法
    (ただし共有 profile は触らず、別 profile で公開検索のみ = profile lock 事故回避)
  - V8計算: iMakeBayAPI/pricing_engine.compute_listing_price (category=TCG(PSA10))

入力: デスクトップの 03_PSA再仕入れ候補_*.csv (set_no / ebay_price / title)
      ※ 手動CSVが無ければ最新 funnel_*.csv の RESTOCK∩PSA10 行から自動生成 (set_noはtitleから抽出)
出力: 同ディレクトリに ..._メルカリ判定.csv + コンソール要約

判定: 同カードPSA10 の最安(メルカリ on_sale) を仕入れ原価とし、V8推奨eBay価格 <= 現eBay価格 なら
      「再仕入れGO」(畳むはずの死蔵を救出可)。
"""
import csv
import datetime
import glob
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
# PSA 供給検索(メルカリ)専用の Chrome プロファイル。**ログインしない**(BAN→仕入不能を避ける)。
# ジョブごとに別ディレクトリ = 同時実行してもプロファイルロックが競合しない (2026-07-28)。
PSA_SCRAPE_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHQ\psa_mercari_scrape_profile"
FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
CATEGORY = "TCG(PSA10)"
SETNO_RE = re.compile(r"\b([A-Z]{2,3}\d{2}-\d{2,3}|P-\d{2,3}|SB\d{2}-\d{2,3}|#\d{3}/[A-Z0-9]+|#\d{2,3})\b")


def search_keyword(title, set_no):
    sn = set_no.strip() if set_no else ""
    if not sn:
        m = SETNO_RE.search(title)
        sn = m.group(1) if m else ""
    return ("PSA10 " + sn).strip() if sn else ""


# ★他社鑑定会社 (2026-07-30 追加: CGC が漏れていた)
#   ユーザー報告「PSA ではなく CGC の候補が出てくる」。メルカリは出品者が
#   `CGC10 PSA10` のように併記するため、`"PSA10" in n` だけでは通ってしまう。
#   CGC スラブを PSA10 出品の仕入元にすると **別商品を送ること**になり SNAD → Defect。
#   = 2026-07-27 の PSA9 混入 4件END と同型 ([[psa10_only_pipeline_grade_gate]])。
#
#   ★境界付きで判定する: 素の部分一致だと **カード名に埋もれた3文字が誤爆**する。
#     既存の "ARS" は "STARS" に、"AGS" は "TAGS" に部分一致してしまい、
#     正当な PSA10 を弾いていた (潜在 bug。ここで同時に解消)。
#   ★`TAG` / `ACE` は入れない: Pokemon の "TAG TEAM" / "ACE SPEC" と衝突して
#     正当な供給を大量に落とすため。必要なら「数字が続く時だけ」で別途対応する。
#
#   ★★判定は **空白を残した文字列** に対して行う。空白除去後に当てると
#     `CGC pristine …` が `CGCPRISTINE` になり、後方境界 `(?![A-Z])` が P に当たって
#     **すり抜ける** (2026-07-30 実データ `CGC pristine PSA10 ワンピースデイ25 ルフィ P-110`
#     で確認)。PSA9/8/7 の方は `PSA 9` 表記を拾うため空白除去後に当てる = 使う文字列が違う。
_OTHER_GRADER_RE = re.compile(r"(?<![A-Z])(CGC|SGC|AGS|HGA|BGS|ARS|BVG|GMA)(?![A-Z])")


def is_psa10(name):
    n = name.replace(" ", "").upper()
    if any(b in n for b in ("PSA9", "PSA8", "PSA7")):
        return False
    if _OTHER_GRADER_RE.search(name.upper()):   # ★空白を残した形で当てる
        return False
    # 「PSA10相当」= 未鑑定の同等品 (生カード)。本物のPSA10 slabではないので除外
    # (2026-06-09 ユーザー指摘: 相当は除外)。原文の 相当 で判定 (upper非影響)。
    if "相当" in name:
        return False
    return "PSA10" in n


def _card_tokens(card_no):
    """カード番号を英数トークン列に分解 ('OP11-106'→['OP11','106'] / 'P-041'→['P','041'])。"""
    return [t for t in re.split(r"[^A-Za-z0-9]", (card_no or "").upper()) if t]


def _name_matches_card(name, card_no):
    """商品名が対象カード番号を『トークン連続一致』で含むか (id-strict, fail-closed)。

    番号をハイフン区切りでトークン化し、商品名のトークン列に連続部分列として現れるか判定。
    単純な部分文字列照合だと promo の短い番号 'P-041' が遊戯王 'FOTB-JP041'(=JP041) 等に
    誤マッチする (2026-06-09 実機: P-041 検索が遊戯王スラブ¥23,100を拾った)。トークン連続
    一致なら 'P','041' が分離して並ぶ正規表記のみ拾い、'JP041'(1トークン) を弾く。

    SNKRDUNK 側 (parse_search_for_card) と同じ fail-closed 思想。番号が無ければ採用しない。
    """
    parts = _card_tokens(card_no)
    if not parts:
        return False
    tokens = [t for t in re.split(r"[^A-Za-z0-9]", (name or "").upper()) if t]
    m = len(parts)
    for i in range(len(tokens) - m + 1):
        if tokens[i:i + m] == parts:
            return True
    return False


def _ebay_item_id(url):
    """eBay URL から item id を抽出 ('.../itm/358596483319' → '358596483319')。"""
    mt = re.search(r"/itm/(\d+)", url or "")
    return mt.group(1) if mt else ""


def _extract_card_no(title, set_no):
    """set_no か title からカード番号を取り出す (ハイフン保持, 例 'OP11-106' / 'P-041')。"""
    sn = (set_no or "").strip()
    if not sn:
        mt = SETNO_RE.search(title or "")
        sn = mt.group(1) if mt else ""
    return sn


def name_jp_for_card(card_no, _cache={}):
    """カタログ(共有DB)から card_no の日本語カード名を引く (無ければ None)。

    検索語に日本語名を足すと番号だけの曖昧検索より精度が上がる (promo の他カード誤マッチ低減)。
    カテゴリは番号書式から一意でないので主要TCGを順に試す。lookup は ID完全一致のみ (fail-closed)。
    """
    if not card_no:
        return None
    if card_no in _cache:
        return _cache[card_no]
    nj = None
    try:
        if r"C:/dev/iMak" not in sys.path:
            sys.path.insert(0, r"C:/dev/iMak")
        from iMakCatalog import api
        for cat in ("one_piece_tcg", "pokemon_tcg", "dragonball_scg", "gundam_tcg"):
            try:
                rec = api.lookup(cat, card_no)
            except Exception:
                rec = None
            if rec and rec.get("name_jp"):
                nj = rec["name_jp"]
                break
    except Exception:
        nj = None
    _cache[card_no] = nj
    return nj


def split_key(key):
    """canonical KEY → (category, product_id)。純関数。

    ★2026-07-29: KEY は `one_piece_tcg:ST04-005_OP08` の様に **カテゴリ接頭辞つき**だが、
      catalog の `product_id` 列に接頭辞は入っていない。接頭辞を付けたまま引くと **必ず空振り**する。
      実測: live PSA 246件のうち **217件(88%)が接頭辞つき** = ほぼ全部がカタログ未解決になっていた。
      症状は「name_jp / hint が空 → 検索語が番号だけ・変種の絞り込みが無効 → 別変種を掴む」。
      同型のバグを 2026-07-28 に `psa_hoju_fill._card_no_from_key` で直済(探索不能127→91件解消)。
      **同じ接頭辞問題がこちらに残っていた**ので同じ規約に揃える。
    """
    k = (key or "").strip()
    if not k or k.startswith(("item:", "shops:")):   # url-key は catalog 引きの対象外
        return "", ""
    if ":" in k:
        cat, pid = k.split(":", 1)
        return cat.strip(), pid.strip()
    return "", k


def card_meta_for_key(key, _cache={}, _db=r"C:/dev/iMak_data/catalog/products.sqlite"):
    """canonical product_id(固有KEY) → {name_jp, image, set, get_info, variant_type, rarity, hint}。

    Step6 P2/P3: KEY が指す**その1枚の変種**の識別属性を catalog 共有DB から厳密引き。
    変種の text 識別子は set_name 列だけでなく **specs.get_info(入手元セット) / variant_type(alt_art等)
    / rarity** に在る(_p1 と _p2 は set_name=None でも get_info=神速の拳 vs EGGHEAD で区別可)。
    hint = これらを束ねた照合トークン source(メルカリ/SNKRDUNK 両チャネルで variant pin に使う=画像不要)。
    KEY 無 / catalog 未収録 → None (呼出側は bare fallback)。

    ★KEY のカテゴリ接頭辞は split_key で落としてから引く(付けたままだと必ず空振り)。
      接頭辞があればカテゴリでも絞る: 同じ product_id が別作品に実在するため
      (実測 `ST04-005` = ワンピース「クイーン」と ガンダム「ストライクダガー」が同居)。
      カテゴリ一致が無く候補が複数なら **None** (どれか分からないものを掴まない = fail-closed)。
    """
    if not key:
        return None
    if key in _cache:
        return _cache[key]
    import json
    import sqlite3
    out = None
    cat, pid = split_key(key)
    if not pid:
        _cache[key] = None
        return None
    try:
        con = sqlite3.connect(_db)
        rows = con.execute(
            "SELECT name_jp, images, set_name, specs, category FROM products WHERE product_id=?",
            (pid,)).fetchall()
        con.close()
        r = None
        if cat:
            hit = [x for x in rows if (x[4] or "") == cat]
            # カテゴリ一致が無い時は、候補が1件(=曖昧さなし)の時だけ採用する
            r = hit[0] if hit else (rows[0] if len(rows) == 1 else None)
        else:
            # 接頭辞なしKEY: 1件なら採用。複数作品に同じ product_id が在る時は **None**。
            # 先頭を黙って採ると別作品のカード名で仕入れを探す(= 誤仕入れ経路)。
            r = rows[0] if len(rows) == 1 else None
        if r:
            try:
                imgs = json.loads(r[1]) if r[1] else []
            except Exception:
                imgs = []
            imgs = sorted(imgs, key=lambda u: (0 if ("OP-JA" in u or "onepiece-cardgame" in u or "JP" in u) else 1))
            sp = {}
            try:
                sp = json.loads(r[3]) if r[3] else {}
            except Exception:
                sp = {}
            get_info = (sp.get("get_info") or "").strip()         # 入手元set(日本語) → メルカリ用
            set_name_ebay = (sp.get("set_name_ebay") or "").strip()  # set名(英語) → SNKRDUNK用
            variant_type = (sp.get("variant_type") or "").strip()
            rarity = (sp.get("rarity") or "").strip()
            out = {
                "name_jp": r[0], "image": imgs[0] if imgs else "", "set": r[2] or "",
                "get_info": get_info, "set_name_ebay": set_name_ebay,
                "variant_type": variant_type, "rarity": rarity,
                # hint = 変種識別トークン source。set名は **日本語(get_info)とブー英語(set_name_ebay)両方**
                # 入れる: メルカリ=JP名 / SNKRDUNK=EN名 と marketplace で言語が違うため(E2Eで判明)。
                # set列がNoneでも get_info/set_name_ebay が入手元セットを持つ → 両 marketplace と突合可。
                # key(suffix _p1 等)は marketplace に出ず部分一致雑音になるため hint に入れない。
                "hint": [r[2] or "", get_info, set_name_ebay, variant_type, rarity, r[0] or ""],
            }
    except Exception:
        out = None
    _cache[key] = out
    return out


def catalog_variants_for_cardno(card_no, _db=r"C:/dev/iMak_data/catalog/products.sqlite",
                                limit=12, title_hint="", category=""):
    """card番号 → その番号の catalog 変種候補 [{product_id,name_jp,set,image}]。

    KEY未解決の行で「正しい変種をユーザーが選ぶ」ための候補(確認ゲート②)。完全一致を先頭、
    以降 product_id 昇順。'P-041' は P-041 / P-041_D / P-041_ST18 … の様に suffix違いを束ねる
    (P-0419 等の別番号を拾わないよう exact OR '<card_no>_%' に限定)。失敗/空は []。

    ★2026-07-24 フォールバック: Pokemon 等は eBay タイトルの card番号が「038/095」形式
    (コレクター番号)で、catalog の product_id はセットコード形式(SM9-038)のため product_id
    一致では 0件 → 目視ゲートに候補が出ない(RESTOCK再仕入れが回らない)不具合があった。
    product_id で引けず card_no が NNN/NNN 形式なら、specs.card_number_text で再検索する。
    複数セットが同じコレクター番号を持つため、title_hint(eBayタイトル)にキャラ名(name_en)が
    含まれる候補を上位に並べて特定を助ける(fail-closed: 確定はユーザー目視)。

    ★2026-07-29 category: 番号体系は作品を跨いで衝突する(実測 `ST04-005` = ワンピース「クイーン」
      と ガンダム「ストライクダガー」が同居)。カテゴリが分かる呼出(KEY 接頭辞由来)は必ず渡すこと。
      渡さない場合は従来どおり全作品から拾う(= 別作品が混ざりうる)。
    """
    if not card_no:
        return []
    import json
    import re as _re
    import sqlite3
    _cols = "product_id, name_jp, set_name, images, specs, language, name_en"
    _cat_sql, _cat_arg = ("", ())
    if (category or "").strip():
        _cat_sql, _cat_arg = (" AND category=?", ((category or "").strip(),))
    try:
        con = sqlite3.connect(_db)
        rows = con.execute(
            f"SELECT {_cols} FROM products "
            "WHERE (product_id=? COLLATE NOCASE OR product_id LIKE ? COLLATE NOCASE)" + _cat_sql,
            (card_no, card_no + "_%") + _cat_arg).fetchall()
        # フォールバック: product_id 不一致 かつ コレクター番号形式 → card_number_text で再検索
        if not rows and _re.fullmatch(r"\d{1,3}/[A-Za-z0-9]{1,4}", card_no.strip()):
            rows = con.execute(
                f"SELECT {_cols} FROM products "
                "WHERE json_extract(specs,'$.card_number_text')=?" + _cat_sql,
                (card_no.strip(),) + _cat_arg).fetchall()
        con.close()
    except Exception:
        return []
    _hint = (title_hint or "").lower()

    def _name_in_hint(name_en):
        # name_en の識別トークン(4字以上の英単語)が title_hint に含まれれば一致とみなす
        toks = [t for t in _re.findall(r"[A-Za-z]{4,}", (name_en or "")) if t.lower() not in
                ("card", "japanese", "pokemon", "promo")]
        return any(t.lower() in _hint for t in toks) if toks else False

    out = []
    for pid, nj, sn, imgs, specs, lang, nen in rows:
        if "dummy" in (pid or "").lower():     # catalog内部のダミー行は候補から除外(実在変種でない)
            continue
        # 英語版は別カード(=100%違う)。Japanese PSA再仕入れなので en / both(英語表記併合) を除外。
        # ja / None(=onepiece-cardgame等 JP公式サイト由来) のみ残す。
        if (lang or "").strip().lower() in ("en", "both"):
            continue
        try:
            a = json.loads(imgs) if imgs else []
        except Exception:
            a = []
        # bandai-tcg-plus(実画像)を優先し dbs-cardgame.com(死にURL多数=404)を後ろに回す
        a = sorted(a, key=lambda u: (
            0 if ("bandai-tcg-plus" in u or "OP-JA" in u or "onepiece-cardgame" in u or "JP" in u) else
            2 if "dbs-cardgame.com" in u else 1))
        try:
            sp = json.loads(specs) if specs else {}
        except Exception:
            sp = {}
        out.append({"product_id": pid, "name_jp": nj or "", "set": sn or "", "image": a[0] if a else "",
                    # 画像が死んでても変種を text で特定できるよう識別属性も返す(alt_art/rarity/入手元)
                    "variant_type": (sp.get("variant_type") or "").strip(),
                    "rarity": (sp.get("rarity") or "").strip(),
                    "get_info": (sp.get("get_info") or "").strip(),
                    "_hint_match": _name_in_hint(nen)})
    # 並び: ①完全一致 product_id ②title のキャラ名一致(fallbackの複数セット絞り) ③product_id 昇順
    out.sort(key=lambda d: (d["product_id"] != card_no, not d["_hint_match"], d["product_id"]))
    for d in out:
        d.pop("_hint_match", None)
    return out[:limit]


def build_card_query(title, set_no, key=None):
    """1カード分の検索情報を作る → {kw, card_no, name_jp, key, image}。

    Step6 P2: canonical KEY があれば catalog 厳密引きの name_jp + 変種画像を使う(bare曖昧回避)。
    kw = 'PSA10 <name_jp> <card_no>'。card_no は照合用、image は P3 画像pin用。
    key 無 / catalog 未収録 → 従来の bare card_no 経路に fallback (後方互換)。
    """
    card_no = _extract_card_no(title, set_no)
    meta = card_meta_for_key(key) if key else None
    nj = (meta.get("name_jp") if meta else None) or name_jp_for_card(card_no)
    image = meta.get("image") if meta else ""
    hint = meta.get("hint") if meta else []
    cat = split_key(key)[0] if key else ""
    mv = _is_multi_variant(card_no, cat)   # 多変種プロモ判定(画像検索fail-closedの根拠)
    if not card_no:
        return {"kw": "", "card_no": "", "name_jp": nj, "key": key or "", "image": image or "",
                "hint": hint, "multi_variant": mv}
    kw = f"PSA10 {nj} {card_no}" if nj else f"PSA10 {card_no}"
    return {"kw": kw, "card_no": card_no, "name_jp": nj, "key": key or "", "image": image or "",
            "hint": hint, "multi_variant": mv}


def _is_multi_variant(card_no, category="", _cache={}):
    """card_no が catalog で 2 変種以上(=同番号で別配布/別art)か(純関数・DB1回でcache)。

    ★2026-07-24: 多変種プロモ(P-066=3 / P-041=8 等)は、kw で正変種を確証できない時に
    画像検索(番号のみ検証=変種を見ない)へ落ちると別変種を掴む(=「違う」連打の主因)。
    多変種なら画像検索 fallback を使わず fail-closed(候補出さず手動仕入れ)にするための判定。
    """
    cn = (card_no or "").strip()
    if not cn:
        return False
    ck = (cn, (category or "").strip())   # ★カテゴリ込みで cache (別作品の変種数を使い回さない)
    if ck in _cache:
        return _cache[ck]
    try:
        n = len(catalog_variants_for_cardno(cn, category=(category or "").strip()))
    except Exception:
        n = 0
    _cache[ck] = n > 1
    return _cache[ck]


def build_input_from_funnel():
    """手動CSVが無いとき、最新 funnel_*.csv から PSA再仕入れ候補CSVを生成。

    === 既存メンテ PSA再仕入れ の絞り込み(明記) ===
    分母 = funnel の各 listing に対し、次を **すべて満たす** 行:
      ①flags 列に "RESTOCK"   … 在庫切れ かつ 需要シグナルあり(funnel 分類)
      ②title が PSA10         … PSA10 鑑定TCG(One Piece/Pokemon 等。US "CCG Individual Cards" +
                                 DE "TCG Einzelkarten" 相当)
      ③実需フィルタ(本関数で追加, 2026-06-17)= 次の **いずれか1つ以上**:
           sold_qty≥1  or  sales90≥1  or  watch≥1  or  impr≥1
         ・狙い: RESTOCK は「impr_total>0(広告込み累計表示)だけでも入る」緩い基準のため
           297件まで膨らみ処理が遅い。実需(実売/watch/自然表示=organic impr)が立つものだけに絞る。
         ・除外されるのは「impr_total(広告)でしか表示されておらず、実売・watch・organic impr が全ゼロ」
           = 見られても欲しがられていない薄い層(再仕入れ優先度ほぼゼロ)。
         ・重要度: sold_qty/sales90(実売) >> watch > impr。impr_total は広告込みなので条件に使わない。
    funnel 列(title/price/ebay_url) を 03_PSA再仕入れ候補_<日付>.csv に落とす。生成パス返却(無→None)。
    """
    ffiles = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not ffiles:
        return None
    fsrc = max(ffiles, key=os.path.getmtime)
    frows = list(csv.DictReader(open(fsrc, encoding="utf-8")))

    def _has_demand(r):
        def _f(k):
            try:
                return float(r.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0
        # 実需シグナル: 実売 or watch or organic impr が1以上(impr_total=広告込みは使わない)
        return _f("sold_qty") >= 1 or _f("sales90") >= 1 or _f("watch") >= 1 or _f("impr") >= 1

    restock_psa = [r for r in frows
                   if "RESTOCK" in (r.get("flags") or "").split("|") and is_psa10(r.get("title", ""))]
    cands = [r for r in restock_psa if _has_demand(r)]
    print(f"  絞り込み: RESTOCK∩PSA10 {len(restock_psa)}件 → 実需フィルタ(実売/watch/organic impr≥1) "
          f"{len(cands)}件 (impr_total のみの薄い層 {len(restock_psa)-len(cands)}件を除外)", flush=True)
    if not cands:
        return None
    out = os.path.join(DESK, f"03_PSA再仕入れ候補_{datetime.date.today():%Y%m%d}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["set_no", "ebay_price", "title", "ebay_url"])
        w.writeheader()
        for r in cands:
            w.writerow({"set_no": "", "ebay_price": r.get("price", ""),
                        "title": r.get("title", ""), "ebay_url": r.get("ebay_url", "")})
    print(f"手動CSVが無いため funnel から自動生成: {os.path.basename(out)} "
          f"(RESTOCK∩PSA10 = {len(cands)}枚, 元: {os.path.basename(fsrc)})", flush=True)
    return out


def _quiet_chromedriver():
    """chromedriver の黒窓を抑止 (共有ヘルパへ委譲・冪等)。失敗しても走行は止めない。

    2026-07-30: 無人 cron 中に `undetected_chromedriver.exe` のコンソール窓が出っぱなしになり
    ユーザーから指摘。窓を閉じられると子プロセスが道連れで死ぬ経路でもあるため塞ぐ。
    """
    try:
        sys.path.insert(0, r"C:/dev/iMak/iMakeBayAPI")
        from chrome_util import silence_chromedriver_console
        return silence_chromedriver_console()
    except Exception:
        return False


def _chrome_major():
    """インストール済 Chrome のメジャー版を取得 (失敗時 None = uc自動検出に委ねる)。

    uc.Chrome の自動検出が driver 版を取り違える事故 (2026-06-09: driver149 vs Chrome148)
    を防ぐため、レジストリ BLBeacon から実機の Chrome 版を読んで version_main に渡す。
    """
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                v, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                return int(str(v).split(".")[0])
            except OSError:
                continue
    except Exception:
        pass
    return None


# 通常出品のみ採用 (個人=MERCARI / メルカリShops=BEYOND)。不明 itemtype は除外 (fail-closed)。
_ALLOWED_ITEM_TYPES = ("ITEM_TYPE_MERCARI", "ITEM_TYPE_BEYOND")
# オークション item の cell内マーカー。itemtype は auction でも ITEM_TYPE_MERCARI のため
# 判別不可 (2026-06-09 実機: EB02-015 のオークションが itemtype=MERCARI で混入)。
# これらは rendered auction cell のみに出現 (i18n JSON は item-cell ブロック外なので汚染なし、
# 実機4ダンプで cell内出現=実auctionのみ・現在価格/残り時間は全体でも1回確認済)。
_AUCTION_MARKERS = ("オークション", "入札", "現在価格", "残り時間")


def parse_mercari_items(src):
    """検索結果HTMLを item-cell 単位で {type,name,price,href} に分解する純関数。

    各 item-cell ブロック内の itemtype / aria-label('<名前>の画像 <価格>円') / href を
    同一ブロックから取るので name·price·href が必ず対応する
    (旧実装は names/prices/urls を別々の findall で取得→添字ズレで別カードの価格を拾う事故源。
     2026-06-09 ユーザー指摘『2行目が違うカード』の構造的原因)。

    通常出品のみ返す。①itemtype が _ALLOWED_ITEM_TYPES 以外を除外 ②cell内に _AUCTION_MARKERS が
    あればオークションとして除外 (2026-06-09 ユーザー指摘『オークションは確定価格でなく仕入不可』)。
    返り値は DOM順 (=価格昇順)。
    """
    items = []
    for b in re.split(r'data-testid="item-cell"', src)[1:]:
        it = re.search(r'itemtype="([A-Z_]+)"', b)
        if not it or it.group(1) not in _ALLOWED_ITEM_TYPES:
            continue
        if any(mk in b for mk in _AUCTION_MARKERS):   # オークション cell を除外
            continue
        al = re.search(r'aria-label="(.+?)の画像\s*([\d,]+)円"', b)
        if not al:
            continue
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', b)
        items.append({
            "type": it.group(1),
            "name": al.group(1).strip(),
            "price": int(al.group(2).replace(",", "")),
            "href": f"https://jp.mercari.com{hr.group(1)}" if hr else "",
        })
    return items


def _variant_matches(items, card_no, variant_hint=None):
    """価格昇順 items から PSA10 かつ対象カード番号一致の **正変種** 候補を昇順 list で返す(純関数)。

    Step6 P3: variant_hint(canonical変種の get_info=入手元set 等)があれば、番号一致の中で
    hint(セット名/コード)に一致する正変種に絞る。SNKRDUNK と同じ思想・画像不要。
    - hint一致あり → その候補群 (正変種, 価格昇順)
    - hint一致無し + 候補単一 → その1件 (変種曖昧なし。seller がset未記載なだけ)
    - hint一致無し + 候補複数 → [] (誤variant買わない fail-closed)
    - hint無 (KEY未解決) → 番号一致の全候補 (価格昇順)
    """
    matches = [it for it in items  # DOM順 = 価格昇順
               if it["price"] > 0 and is_psa10(it["name"]) and _name_matches_card(it["name"], card_no)]
    if not matches:
        return []
    if not variant_hint:
        return matches
    from snkrdunk_psa_resource import _hint_tokens, _print_signal, _item_print
    # set 確証は **set 部分(hint先頭3=set_name/get_info/set_ebay)のみ**で行う。キャラ名(name_jp)を
    # 含めると同キャラ別変種を誤確証する(2026-06-19 ゼウス/ナミ等)。set-code(OP11等)は番号と被るので除外。
    # kw_variant_confident と同一基準に揃える。
    set_part = list(variant_hint)[:3] if isinstance(variant_hint, (list, tuple)) else variant_hint
    toks = [t for t in _hint_tokens(set_part) if not re.fullmatch(r"[A-Z]{2,}\d{1,3}", t)]
    if not toks:
        return matches                    # set トークン取れず → 従来最安群
    # ①set トークン採点で最高スコア群(=正set)に絞る → ②同setで複数なら print種別で tie-break。
    scored = [(sum(1 for t in toks if t in (it["name"] or "").upper().replace(" ", "").replace("-", "")), it)
              for it in matches]   # matches は価格昇順を保持
    top = max(s for s, _ in scored)
    if top == 0:
        # set を確証できない = 別変種(パラレル/SP/別プロモ)を掴むリスク → 不採用(呼出側で画像検索へ)。
        # 旧: 単一候補は「sellerがset未記載なだけ」と採用していたが、これが番号一致・別変種の誤掴みの
        # 主因だった(2026-06-19 OP02-036パラレル/OP05-091 SP/P-066別プロモ 等)。精度優先で fail-closed。
        return []
    topgroup = [it for s, it in scored if s == top]    # 価格昇順保持
    if len(topgroup) == 1:
        return topgroup                                # set で一意
    target = _print_signal(variant_hint)
    matched = [it for it in topgroup if _item_print(it["name"]) == target]
    return matched if matched else []     # 正 print種別の候補群 / 一意化不可は fail-closed


def kw_variant_confident(name, variant_hint):
    """keyword検索でヒットした候補名が hint の set語で『正変種』と確証できるか(純関数)。

    確証できない=番号だけ一致で別変種/別カードを掴むリスク → 呼出側は画像検索に切替える。
    - hint無(KEY未解決) → False(確証不能)
    - hint のset語が候補名に1つでも在る → True(変種確証)
    - 在らない → False(番号一致だけ=危険 → 画像検索へ)
    """
    if not variant_hint:
        return False
    # set語のみで確証(名前/番号/rarity は同名別setの誤variantを見逃すため使わない)。
    # hint = [set_name, get_info, set_name_ebay, variant_type, rarity, name_jp, key] の前3つ=set。
    set_part = list(variant_hint)[:3] if isinstance(variant_hint, (list, tuple)) else variant_hint
    try:
        from snkrdunk_psa_resource import _hint_tokens
        toks = _hint_tokens(set_part)
    except Exception:
        return False
    # set-code(OP11/EB04 等)はカード番号と重複し誤確証するので除外。set名の語(漢字/カナ/Latin)で確証。
    toks = [t for t in toks if not re.fullmatch(r"[A-Z]{2,}\d{1,3}", t)]
    if not toks:
        return False
    norm = (name or "").upper().replace(" ", "").replace("-", "")
    return any(t in norm for t in toks)


def pick_cheapest_psa10(items, card_no, variant_hint=None):
    """正変種 PSA10 の最安を1件返す (price, href, name) or None。_variant_matches の先頭。"""
    cands = _variant_matches(items, card_no, variant_hint)
    if not cands:
        return None
    it = cands[0]
    return (it["price"], it["href"], it["name"])


def pick_psa10_candidates(items, card_no, variant_hint=None, limit=5):
    """正変種 PSA10 候補を価格昇順で最大 limit 件 [(price, href, name)] 返す。

    補URL(メルカリ＆SNKRDUNK 混合の代替候補)用。最安が売切/状態相違時の次の手。fail-closed 時は []。
    """
    return [(it["price"], it["href"], it["name"])
            for it in _variant_matches(items, card_no, variant_hint)[:limit]]


def _norm_name(s):
    """カード名の比較用正規化 (純関数)。空白・中黒・ハイフン差を吸収する。"""
    t = (s or "").upper()
    for ch in " 　・･-‐‑–—ー~〜「」『』【】()()[]":
        t = t.replace(ch, "")
    return t


def pick_psa10_loose_candidates(items, name_jp, limit=6):
    """★2026-08-01: **番号を確認できない**が名前は一致する PSA10 候補 (純関数)。

    なぜ要るか:
        メルカリの PSA10 出品は **商品名にカード番号を書かない**ことが多い。厳密一致
        (`_name_matches_card`) を必須にすると、在庫が実在しても候補ゼロになり、
        「市場に無い」と誤診してしまう (実測 2026-08-01: 補0本74件のうち 39件が候補なし)。

    ★これは strict が0件のときの **フォールバック専用**。番号未確認なので:
        - 価格判定 (`best`) や RESTOCK ゲートには **絶対に使わない**
        - 視覚確証UI に **番号未確認と明示して**出し、最終判断は人の目視に委ねる
          (ユーザー方針 2026-08-01「最終は目視するわけだから、近しいのを含めていい」)

    名前が取れない (name_jp 空) 場合は [] = 判定材料が無いので出さない (fail-closed)。
    """
    key = _norm_name(name_jp)
    if not key:
        return []
    return [(it["price"], it["href"], it["name"])
            for it in items
            if it.get("price", 0) > 0 and is_psa10(it.get("name") or "")
            and key in _norm_name(it.get("name"))][:limit]


def parse_image_search_results(src):
    """画像検索モーダル(image-grid)の結果を [{price,sold,href}] に分解する純関数。

    モーダル結果は商品名を持たない (サムネ＋価格のみ)。番号照合は別途 item ページを開いて行う。
    各 result anchor は data-location='image_search:similar_looks_modal:item_thumbnail'、
    aria-label='[売り切れ ]<価格>円'、href=/item/m… or /shops/product/… (2026-06-09 実機確認)。
    """
    out = []
    for a in re.split(r'data-location="image_search:similar_looks_modal:item_thumbnail"', src)[1:]:
        seg = a[:600]
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', seg)
        al = re.search(r'aria-label="(売り切れ\s*)?([\d,]+)円"', seg)
        if hr and al:
            out.append({"href": "https://jp.mercari.com" + hr.group(1),
                        "sold": bool(al.group(1)),
                        "price": int(al.group(2).replace(",", ""))})
    return out


def image_search_fallback(drv, ebay_item_id, card_no, max_open=12):
    """キーワードで0件のとき、自社eBay出品のPSAスラブ画像でメルカリ画像検索 → 番号+PSA10検証 → 最安。

    画像検索は『似ている商品』(視覚類似)なので別カード/別ジャンルのスラブも混ざる。結果に名前が
    無いため、販売中候補を価格昇順で開き og:title で番号(token連続一致)+PSA10 を検証、最初に通った
    =最安を返す (2026-06-09 POCで EB02-015 を ¥14,500 で正しく取得・キーワード版と一致を確認)。
    返り値 (price, url, name) or None。
    """
    if not ebay_item_id or not card_no:
        return None
    try:
        from ebay_getitem_images import fetch_listing_images
    except Exception:
        return None
    pics = fetch_listing_images(ebay_item_id)
    if not pics:
        return None
    import requests
    img_path = os.path.join(os.environ.get("TEMP", "."), f"slab_{ebay_item_id}.jpg")
    try:
        ir = requests.get(pics[0], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        with open(img_path, "wb") as f:
            f.write(ir.content)
    except Exception:
        return None
    from selenium.webdriver.common.by import By
    try:
        drv.get("https://jp.mercari.com/search?keyword=%20"); time.sleep(7)
        btn = drv.find_elements(By.CSS_SELECTOR, '[data-testid="image-search-button"]')
        if not btn:
            return None
        btn[0].click(); time.sleep(2)
        fin = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not fin:
            return None
        fin[0].send_keys(img_path); time.sleep(11)
        res = parse_image_search_results(drv.page_source)
    except Exception:
        return None
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
    for r in onsale[:max_open]:
        try:
            drv.get(r["href"]); time.sleep(4)
            ps = drv.page_source
            # オークション除外: 詳細ページの bid-button(=入札) で判別 (通常は checkout-button)。
            # テキスト(入札する/現在価格)は i18n にも入り使えず、ボタンの testid が確実な鑑別子
            # (2026-06-09 実機: auction=bid-button / normal=checkout-button)。
            if 'data-testid="bid-button"' in ps or 'data-testid="checkout-button"' not in ps:
                continue
            mt = re.search(r'<meta property="og:title" content="([^"]+)"', ps)
            title = mt.group(1) if mt else ""
            if is_psa10(title) and _name_matches_card(title, card_no):
                return (r["price"], r["href"], title)
        except Exception:
            continue
    return None


# --- 出品者/送料フィルタ (詳細ページ由来。検索グリッドに無い) -----------------------
# ★2026-07-25: 補URL候補を「送料込み + (個人セラーは評価件数≥N)」に絞る(ユーザー要望)。
# 送料/状態/評価は商品詳細ページにしか無いため各候補を訪問して判定(やや遅い=opt-in)。
_COND_VALUES = r"(新品、未使用|未使用に近い|目立った傷や汚れなし|やや傷や汚れあり|傷や汚れあり|全体的に状態が悪い)"


def _parse_cond_ship(s):
    """詳細 page_source → (商品の状態, 送料負担)。**ラベル直後の値だけ**取る純関数(test可)。

    mercari は送料込み/着払い・状態語が UI/関連商品で常に両方出る(2026-06-25 着払い混入バグ)ため、
    『商品の状態』『配送料の負担』ラベル直後の値を非貪欲マッチで取る。取れねば '' (fail-closed)。
    ichibankuji_restock._parse_cond_ship と同一規約(検証: 実レンダHTMLで('新品、未使用','送料込み'))。
    """
    cm = re.search(r"商品の状態.{0,120}?" + _COND_VALUES, s or "", re.S)
    sm = re.search(r"配送料の負担.{0,120}?(送料込み|着払い)", s or "", re.S)
    return (cm.group(1) if cm else "", sm.group(1) if sm else "")


def _parse_seller_reviews(s):
    """詳細 page_source → 出品者の**評価件数**(int) or None(純関数・test可)。

    ★星の数(5段階評価中4.5)ではなく **件数**。seller aria-label の 'N件のレビュー' を取る
    (実レンダHTMLで 1回のみ出現=一意。検証済 '1282件のレビュー')。取れねば None(fail-closed=除外)。
    """
    m = re.search(r"([\d,]+)件のレビュー", s or "")
    return int(m.group(1).replace(",", "")) if m else None


def _is_shops_url(href):
    """メルカリShops(業者)出品か。個人は /item/m…、Shops は /shops/product/…(純関数)。"""
    return "/shops/product/" in (href or "")


def candidate_passes_filter(cond, ship, reviews, is_shops, min_reviews=100, require_freeship=True):
    """補URL候補が「送料込み + 個人は評価件数≥min_reviews」を満たすか(純関数・test可)。

    - 送料込み必須(着払い=実原価が過小表示→除外)。require_freeship=False で無効化可。
    - **個人(Shopsでない)のみ 評価件数≥min_reviews**。Shops(業者)は評価不問。
    - reviews=None(取れない)は個人なら不合格(fail-closed)。Shops は reviews 不要。
    """
    if require_freeship and ship != "送料込み":
        return False
    if not is_shops:
        if reviews is None or reviews < min_reviews:
            return False
    return True


def _detail_supply_check(drv, href, min_reviews=100, require_freeship=True):
    """詳細ページを訪問し candidate_passes_filter を評価 → (ok, ship, reviews)。失敗は (False,'',None)。"""
    try:
        drv.get(href)
        time.sleep(3)
        src = drv.page_source
    except Exception:
        return (False, "", None)
    _cond, ship = _parse_cond_ship(src)
    reviews = None if _is_shops_url(href) else _parse_seller_reviews(src)
    ok = candidate_passes_filter(_cond, ship, reviews, _is_shops_url(href),
                                 min_reviews=min_reviews, require_freeship=require_freeship)
    return (ok, ship, reviews)


def _filter_candidates_supply(drv, cands, min_reviews=100, keep=5):
    """候補(price,href,name) を詳細訪問で「送料込み+個人評価≥min_reviews」に絞る(価格昇順・最大keep件)。

    各候補の詳細を訪問(遅い)。keep 件通ったら打ち切り。全滅なら []。opt-in(呼出側が有効化時のみ)。
    """
    out = []
    for c in cands:
        href = c[1] if len(c) > 1 else ""
        if not href:
            continue
        ok, _ship, _rev = _detail_supply_check(drv, href, min_reviews=min_reviews)
        if ok:
            out.append(c)
            if len(out) >= keep:
                break
    return out


def fetch_mercari_cheapest(cards, freeship_min_reviews=None):
    """各カードの メルカリ on_sale PSA10 を取得 → {idx: {"best":(price,url,name)|None, "cands":[(price,url,name),...]}}。

    best = 最安(価格判定用)、cands = 正変種 PSA10 を価格昇順で最大5件(補URL=両ch混合の代替候補用)。
    cards: [{"kw":検索語, "card_no":照合番号, "ebay_item_id":フォールバック用}] のリスト。
    キーワード検索で0件なら、ebay_item_id があれば画像検索フォールバックを試す。
    freeship_min_reviews: None=フィルタ無し(既定=RESTOCKゲート等の従来挙動不変)。int を渡すと
      候補を「送料込み + 個人セラー評価件数≥その値」に絞る(詳細ページ訪問=やや遅い。slice2 補URL用)。
    """
    import undetected_chromedriver as uc

    def _new_driver():
        # ★2026-07-28: **専用プロファイル**を持たせる(従来は指定なし=毎回まっさらな一時profile)。
        # 一番くじ側は既に専用profileで cookie を保温しており、PSA 側だけ「初回訪問の匿名 headless」
        # として最も弾かれやすかった。ジョブごとに別ディレクトリなので他ジョブとロックが競合しない。
        # **ログインはしない**(仕入アカBAN→仕入不能を避ける。一番くじと同方針)。
        # profile が他プロセスに掴まれている等で起動できない時は一時profileへ fallback(走行を止めない)。
        _quiet_chromedriver()          # ★黒窓を出さない(無人cron中に出っぱなしになる・2026-07-30)

        def _mk(profile_dir):
            opts = uc.ChromeOptions()
            opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
            opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
            if profile_dir:
                opts.add_argument(f"--user-data-dir={profile_dir}")
            _maj = _chrome_major()
            return uc.Chrome(options=opts, version_main=_maj) if _maj else uc.Chrome(options=opts)

        try:
            os.makedirs(PSA_SCRAPE_PROFILE_DIR, exist_ok=True)
            d = _mk(PSA_SCRAPE_PROFILE_DIR)
        except Exception as e:      # noqa: BLE001
            import tempfile
            print(f"  ⚠ 専用profile で起動できず一時profileへ({type(e).__name__}) — "
                  f"cookie保温は効かないが走行は継続", flush=True)
            d = _mk(tempfile.mkdtemp(prefix="psa_mercari_"))
        d.set_page_load_timeout(50)
        return d

    # ★2026-07-24 確実性優先(ユーザー方針): driver を _RESTART_EVERY 件ごとに作り直す。
    # 長時間セッションで uc.Chrome が不安定化し途中でクラッシュ→以降 全 item timeout(2026-07-24
    # item58 で全滅=79件が空)を防ぐ。BAN回避の 8s sleep は維持し「速度より しっかり探す」。
    _RESTART_EVERY = 10
    out = {}
    drv = _new_driver()
    try:
        for i, c in enumerate(cards):
            if i > 0 and i % _RESTART_EVERY == 0:
                try:
                    drv.quit()
                except Exception:
                    pass
                drv = _new_driver()
                print(f"  ♻ Mercari driver 再起動 ({i}件処理済 / 安定化)", flush=True)
            kw = c.get("kw"); card_no = c.get("card_no"); eid = c.get("ebay_item_id")
            if not kw:
                out[i] = None
                print(f"  [{i+1}/{len(cards)}] (検索語なし) skip", flush=True)
                continue
            url = "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale&order=asc&sort=price"
            try:
                drv.get(url); time.sleep(8)
                # item-cell 単位で抽出 (name·price·href 対応保証 + 通常出品のみ=オークション除外)
                items = parse_mercari_items(drv.page_source)
                cands = pick_psa10_candidates(items, card_no, c.get("hint"))   # 正変種 価格昇順 最大5
                # all_cands = 同番号の **全変種**(variant_hint無)。視覚確証で「どの変種か」を人が選べる
                # ように並べる用(同番号別変種の取り違え→違う再検索ループ防止。2026-06-22)。
                all_cands = pick_psa10_candidates(items, card_no, None, limit=8)
                best = cands[0] if cands else None
                via = "kw"
                # keyword で変種を確証できない(0件 or set語不一致=違うカードを掴むリスク)→ 画像検索。
                # 画像検索は自社PSAスラブ画像で視覚一致 → 番号+PSA10検証なので別カード混入を防ぐ。
                _unconfident = best is None or not kw_variant_confident(best[2], c.get("hint"))
                if _unconfident and eid and c.get("multi_variant"):
                    # ★2026-07-24 fail-closed: 多変種プロモ(P-066/P-041 等)は画像検索(番号のみ検証・
                    # 変種を見ない)で別変種を掴む=「違う」連打の主因。多変種×変種未確証は画像検索せず
                    # 候補を出さない(手動仕入れに倒す)。単一変種のみ画像検索OK(番号一致=正)。
                    best = None
                    cands = []
                    via = "多変種fail-closed(画像検索skip)"
                    print(f"  [{i+1}/{len(cards)}] {card_no}: 多変種で変種確証不可→候補出さず(手動仕入れ)", flush=True)
                elif _unconfident and eid:
                    img = image_search_fallback(drv, eid, card_no)
                    if img:
                        best = img
                        cands = [img]
                        all_cands = [img]
                        via = "画像検索"
                # 補URL用フィルタ(opt-in): 送料込み + 個人セラー評価件数≥N に絞る(詳細訪問=遅い)。
                # best も絞り込み後の最安(送料込み+評価OK)にする=価格判定も実仕入可の値になる。
                if freeship_min_reviews is not None and cands:
                    _before = len(cands)
                    cands = _filter_candidates_supply(drv, cands, min_reviews=freeship_min_reviews)
                    best = cands[0] if cands else None
                    if _before != len(cands):
                        via += f"+送料込み/評価≥{freeship_min_reviews}({_before}→{len(cands)})"
                # ★2026-08-01: 厳密一致(番号必須)が0件のときだけ、**名前一致のみ**の候補を
                #   別枠で拾う。メルカリは番号を書かない出品が多く、そのままだと在庫が
                #   実在しても「候補なし」になるため。番号未確認なので best/価格判定には
                #   一切使わず、視覚確証UIに「番号未確認」と明示して出す。
                loose = []
                if not all_cands:
                    loose = pick_psa10_loose_candidates(items, c.get("name_jp"))
                    if loose:
                        via += f"+番号未確認{len(loose)}件"
                out[i] = {"best": best, "cands": cands, "all_cands": all_cands,
                          "loose_cands": loose}
                tag = f"¥{best[0]} ({via}, 候補{len(cands)})" if best else "PSA10在庫なし"
                print(f"  [{i+1}/{len(cards)}] {card_no or kw}: {tag}", flush=True)
            except Exception as e:
                # ★2026-07-24 fail-closed: 取得失敗(timeout等)は「在庫なし」と区別する。
                # _error 付き = 「不明(取得できなかった)」。呼出側は End候補に倒さず判定保留し、
                # キャッシュにも残さない(次サイクルで再取得)。区別しないと「本当に無いのか
                # 取れなかっただけか分からないのに End候補」= fail-OPEN(仕入可能を取下げ)。
                out[i] = {"best": None, "cands": [], "_error": str(e)[:40] or "error"}
                print(f"  [{i+1}/{len(cards)}] {card_no or kw}: ERR {str(e)[:30]}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass
    return out


def main():
    import pricing_engine

    # キャッシュ: 当日中に既に判定結果があれば再スクレイプしない (連打=数分スクレイプ→BANリスク回避)。
    # 価格再取得したいときは --force を付けて実行。
    done = glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*_メルカリ判定.csv"))
    if done and "--force" not in sys.argv:
        latest = max(done, key=os.path.getmtime)
        if datetime.date.fromtimestamp(os.path.getmtime(latest)) == datetime.date.today():
            print(f"当日の判定結果が既にあります（再スクレイプしません）: {os.path.basename(latest)}")
            print("価格を取り直す場合は --force を付けて実行してください。")
            return  # returncode 0 → 既存の判定CSVが自動で開く

    files = [p for p in glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*.csv"))
             if "_メルカリ判定" not in os.path.basename(p)]
    if files:
        src = max(files, key=os.path.getmtime)
    else:
        src = build_input_from_funnel()
        if not src:
            sys.exit("03_PSA再仕入れ候補_*.csv が無く、funnel_*.csv にも RESTOCK∩PSA10 がありません。"
                     "先に『ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    cards = [{**build_card_query(r.get("title", ""), r.get("set_no", "")),
              "ebay_item_id": _ebay_item_id(r.get("ebay_url", ""))} for r in rows]
    print(f"対象: {src}\nPSA {len(rows)}枚 のメルカリ最安(PSA10)を取得中 (name_jp検索+画像検索フォールバック)...", flush=True)
    found = fetch_mercari_cheapest(cards)

    results = []
    for i, r in enumerate(rows):
        cur = float(r["ebay_price"]) if r.get("ebay_price") else 0
        best = (found.get(i) or {}).get("best")
        rec = judge = murl = None
        cost = best[0] if best else None
        if cost and cur:
            calc = pricing_engine.compute_listing_price(cost_jpy=cost, median_usd=cur, category=CATEGORY)
            rec = calc["price"]
            judge = "再仕入れGO" if rec <= cur else "原価高(再仕入れ不可)"
            murl = best[1]
        elif cur and best is None:
            judge = "メルカリにPSA10在庫なし"
        else:
            judge = "取得失敗"
        results.append({"set_no": r.get("set_no") or search_keyword(r.get("title", ""), "").replace("PSA10 ", ""),
                        "ebay_now_usd": cur, "mercari_jpy": cost, "v8_recommended_usd": rec,
                        "判定": judge, "mercari_url": murl, "ebay_url": r.get("ebay_url"), "title": r.get("title")})

    # スプシ「PSA再仕入れ」タブに集約 (デスクトップCSV廃止 2026-06-07。再仕入れ系をシートに統一)
    if results:
        header = list(results[0].keys())
        rows2d = [header] + [[r.get(k, "") for k in header] for r in results]
        try:
            from sheet_io import write_rows_to_tab, MAINT_URL
            write_rows_to_tab("PSA再仕入れ", rows2d)
            print(f"🃏 「PSA再仕入れ」タブ更新: {len(results)}件 → {MAINT_URL}")
        except Exception as _e:
            print(f"⚠ 「PSA再仕入れ」タブ更新失敗: {type(_e).__name__}: {_e}")

    go = [x for x in results if x["判定"] == "再仕入れGO"]
    nost = [x for x in results if x["判定"] == "メルカリにPSA10在庫なし"]
    high = [x for x in results if x["判定"].startswith("原価高")]
    print(f"\n=== ③ メルカリ再仕入れ判定 ({len(rows)}枚) ===")
    print(f"  再仕入れGO(救出可・黒字): {len(go)}件")
    print(f"  原価高(再仕入れ不可): {len(high)}件")
    print(f"  メルカリPSA10在庫なし: {len(nost)}件")
    print(f"\n再仕入れGO 上位(eBay価格高い順):")
    for x in sorted(go, key=lambda v: -v["ebay_now_usd"])[:12]:
        print(f"  {x['set_no']:<12} メルカリ¥{x['mercari_jpy']} → eBay現${x['ebay_now_usd']:.0f} (V8推奨${x['v8_recommended_usd']:.0f})")
    # 出力はスプシ「PSA再仕入れ」タブ (上で更新済)


if __name__ == "__main__":
    main()
