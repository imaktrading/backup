#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA10 再仕入れ可否ゲート (2チャネル統合: メルカリ ＆ SNKRDUNK)。

RESTOCK∩PSA10 の各カードについて、メルカリ と SNKRDUNK の両方で「今PSA10が買えるか+最安」を
確認し束ねる。どちらか一方でも在庫あり → 再仕入れ可。両方なし → 再仕入れ不能(End候補)。

設計メモ: oos_demand_harvest_design.md §7/§7c
チャネル:
  - メルカリ: mercari_psa_resource.fetch_mercari_cheapest (キーワード検索, Selenium)
  - SNKRDUNK: snkrdunk_psa_resource.check_by_keyword (HTTP-only, 全シリーズ, Selenium不要)
              productNumber→id を /en/v1/search?type=trading-card で HTTP 解決 → min-prices で PSA10。
              旧 harvest Selenium(CSR描画フレで0件多発)は廃止。HTTP化で安定+全シリーズ+誤End救済。

combine() は純関数 (I/O無し) で test 可能。HTTP shape({available,psa10_price_jpy,card_url})と
harvest shape({psa10_count,psa10_details}) の両対応。出力は「PSA再仕入れ」タブ。
"""
from __future__ import annotations

import os
import re
import sys

# タイトルから card 番号を取る。**作品ごとに書き方が違う**ので順に試す。
#
# ★2026-09-01: 旧実装は `(OP|ST|EB|SB|GD)nn-nnn | P-nnn` = **ワンピースの書き方だけ**で、
#   ポケモンのコレクター番号 (058/095)・promo (261/SV-P)、ドラゴンボール (FB05-119 / E01-09)、
#   ガンダム (GD02-072 / "GD02 #036" 形式) が **1件も取れなかった**。
#   番号が空だと catalog を引きにすら行かない (`catalog_variants_for_cardno("")` は即 [])ため、
#   目視ゲート②が常に「候補なし」になり、しかも画面には「未収録→要追加」と出て
#   **カタログのせいに見えていた**。
#   実測 (funnel_20260825 の PSA10 US 930件): 旧=374件しか取れない → 新=819件 (88%)。
#   2026-07-24 の `2306ec3` は受け取る側 (card_number_text fallback) だけ直しており、
#   **渡す側がずっと直っていなかった** (テストが番号を関数へ直接渡していたので緑のままだった)。
CARD_NUM_PATTERNS = (
    # ① コレクター番号 (ポケモン): 058/095 / 212/187 / 261/SV-P / 182/XY-P
    re.compile(r"\b(\d{1,3}/[A-Za-z0-9\-]{1,5})\b"),
    # ② セットコード: OP07-051 / ST01-012 / PRB02-014 / FB05-119 / E01-09 / GD02-072 / SV8a-093
    re.compile(r"\b([A-Z]{1,4}\d{1,2}[a-z]?-\d{1,3}[A-Za-z]?)\b"),
    # ③ 英字だけの promo: P-110 / RP-025 / FP-024
    re.compile(r"\b([A-Z]{1,3}-\d{2,3})\b"),
)
# ④ セットコードと番号が離れている書き方: "One Piece OP02 Paramount War #036" / "Gundam GD02 #091"
_BARE_NUM_RE = re.compile(r"#(\d{1,3})\b")
_SET_TOKEN_RE = re.compile(r"\b([A-Z]{1,4}\d{1,2}[a-z]?)\b")


def _card_number(title):
    """eBay タイトル → card 番号 (取れなければ None = fail-closed)。

    推測はしない。**タイトルにその形で書かれている時だけ**返す。
    番号だけ (`#036`) はどのセットか決まらないので、**同じタイトル内にセットコードが在る時だけ**
    組み立てる (無ければ None のまま = 従来どおり人が「PSA番号補完」で入れる)。
    """
    t = title or ""
    for rx in CARD_NUM_PATTERNS:
        m = rx.search(t)
        if m:
            return m.group(1).upper()
    m = _BARE_NUM_RE.search(t)
    if m:
        pre = _SET_TOKEN_RE.findall(t[:m.start()])
        if pre:
            return "%s-%03d" % (pre[-1].upper(), int(m.group(1)))
    return None


def _is_setcode_style(num):
    """set-code 形式 (OP07-051) か。コレクター番号 (058/095) と区別する純関数。

    KEY と title の食い違い警告は **同じ書き方どうし**でしか意味がない。
    KEY='SM8B-231' と title='231/150' は同じカードの別表記なので、
    ここを見ないと ポケモン全件で「タイトルが誤りの疑い」と誤警告する。
    """
    n = (num or "").strip()
    return bool(n) and "/" not in n


def _key_card_number(key):
    """canonical KEY (catalog product_id) → SNKRDUNK 検索/突合用 card番号 (変種suffix除去)。

    Pokemon 等 title に番号が出ない場合の供給源。KEY='SV-P-291'→'SV-P-291' /
    'OP11-106_p2'→'OP11-106'。url-key(item:/shops:)・数字を含まない値は None (fail-closed)。
    SNKRDUNK 側は _norm_cardnum で set-code+番号を区切り非依存に突合 (SV系は一致、S系prefix差は
    no-match=Mercariのみ=安全)。
    """
    if not key or str(key).startswith(("item:", "shops:")):
        return None
    k = str(key)
    # ★2026-07-28: KEY の **カテゴリ接頭辞**('pokemon_tcg:SV5a-083')を先に落とす。
    # 旧 bare 形式('SV5a-083')前提で split("_")[0] していたため、新形式では 'pokemon' を拾って
    # 数字なし→None になり **番号が取れない**(= SNKRDUNK 突合が沈黙して供給を見落とす)。
    if ":" in k:
        k = k.split(":", 1)[1]
    base = k.split("_")[0].strip().upper()
    return base if re.search(r"\d", base) else None


def _resource_card_number(title, key, item_id=""):
    """突合用 card番号。**canonical KEY(catalog SSOT) を優先**し、無ければ title 由来。

    ★2026-08-01 優先順を逆転 (旧: title 優先 / 新: KEY 優先)。

    理由 (実測で誤仕入れ手前まで来ていた):
        itemID 358604221709 の eBay タイトルは `#EB01-006 Tony Chopper` だが、
        KEY は `ST01-006_p1`。PSA のラベルは
        `Brand=ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION / CardNumber=006`
        で **KEY が正**。EB01-006 は別セット(EXTRA BOOSTER)の **rarity SR** で、
        ST01-006_p1 は 25周年プレミアムカードコレクションの **rarity C** = 別物。
        title 優先のままだと **SR の供給を探して買ってしまう** (= 別カードを送る / 赤字)。

    KEY は catalog 解決済の SSOT ([[catalog_ssot_principle]])。タイトルは自由文で、
    出品時の生成ミスや表記ゆれが入りうるので、同定の一次ソースにしない。
    食い違いは黙って直さず警告する (タイトル側の誤りを検出する唯一の口になる)。
    """
    ck = _key_card_number(key) or ""
    ct = _card_number(title) or ""
    if ck and ct and _is_setcode_style(ck) and _is_setcode_style(ct) and ck.upper() != ct.upper():
        print(f"  ⚠️ 番号不一致: eBayタイトル='{ct}' / KEY='{ck}' → **KEY を採用** "
              f"(itemID={item_id or '?'} / タイトル側が誤りの疑い = 要 revise 確認)", flush=True)
    return ck or ct or None      # 番号源が無ければ None (fail-closed。従来の戻り値規約を維持)


def _min_price(prices):
    vals = [p for p in prices if isinstance(p, int) and p > 0]
    return min(vals) if vals else None


_VERIFIED_CERTS_FILE = r"C:/dev/iMak_data/dedupe/verified_certs.json"


def load_verified_certs(path=_VERIFIED_CERTS_FILE):
    """出品時 HTML 目視確認の資産 {cert: {choice, product_id}} を読む。失敗は {}。"""
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def key_from_verified_cert(cert, verified):
    """cert → 出品時に確定した canonical KEY (純関数, test可)。

    出品時 HTML viewer で人が確定した変種 (choice=OK=期待通り / CHOSEN=選択) の product_id を返す。
    NONE/未確定/欠落は "" (= fail-closed: 推測で KEY を捏造しない)。
    cert は「その出品」の同定に不変(再仕入れで別個体を買っても、この出品済カードの識別は cert)。
    → itemID join 漏れ(書き戻し漏れ/relist)を、出品時に払った目視コストの資産で埋める。
    """
    rec = verified.get(str(cert or "").strip()) if cert else None
    if rec and rec.get("choice") in ("OK", "CHOSEN"):
        return (rec.get("product_id") or "").strip()
    return ""


def _build_visual_candidates(mr, c, max_mercari=6, max_snkr=6):
    """視覚確証に出す仕入候補リストを作る(純関数)。

    mercari は最安1件でなく **all_cands(同番号の全変種)** を複数並べ、ユーザーが現物と一致する
    変種を1パスで選べるようにする(同番号別変種の取り違え→「違う」再検索ループ防止。2026-06-22)。
    all_cands 無い古cache/フォールバック時は cands→best の順で代替。snkrdunk は出品一覧をそのまま。
    Args:
        mr: fetch_mercari_cheapest の1カード分 {"best","cands","all_cands"} (None可)。
        c:  combine() の戻り(snkrdunk_urls / mercari_url 等)。
    """
    mr = mr or {}
    out, seen = [], set()
    # ★2026-08-01: all_cands は **同番号の全変種**(変種未確証) なので、そのまま並べると
    #   別変種が上に来て人が毎回「違う」を押す羽目になる。cands(= _variant_matches を通った
    #   **正変種**) に載っている URL を先頭へ寄せ、各候補に variant_ok を持たせて UI で
    #   区別できるようにする。cands が空(mercari の出品名にセット名が無くて確証できない場合)は
    #   全部 variant_ok=False = 「変種未確認だから絵柄をよく見て」を人に伝える。
    verified = {t[1] for t in (mr.get("cands") or []) if t and len(t) > 1 and t[1]}
    merc = mr.get("all_cands") or mr.get("cands") or []
    merc = sorted(merc, key=lambda t: 0 if (t and len(t) > 1 and t[1] in verified) else 1)
    for t in merc[:max_mercari]:
        url = t[1] if (t and len(t) > 1) else ""
        if url and url not in seen:
            seen.add(url)
            out.append({"channel": "mercari", "url": url,
                        "price": (t[0] if t and isinstance(t[0], int) else None),
                        "name": (t[2] if len(t) > 2 else ""),
                        "variant_ok": url in verified})
    # ★2026-08-01: 番号未確認 (名前一致のみ) の候補を **最後に** 足す。
    #   厳密一致が0件のときだけ mercari 側が積む枠。「候補なし」で終わらせず、
    #   目視で弾ける形にして人に見せる (ユーザー方針: 最終は目視なので近しいのも出す)。
    #   number_ok=False を持たせ、UI で明確に区別できるようにする。
    for t in (mr.get("loose_cands") or [])[:max_mercari]:
        url = t[1] if (t and len(t) > 1) else ""
        if url and url not in seen:
            seen.add(url)
            out.append({"channel": "mercari", "url": url,
                        "price": (t[0] if t and isinstance(t[0], int) else None),
                        "name": (t[2] if len(t) > 2 else ""),
                        "variant_ok": False, "number_ok": False})
    if not out and c.get("mercari_url"):            # 最終フォールバック(best のみ)
        out.append({"channel": "mercari", "url": c["mercari_url"], "price": c.get("mercari_jpy")})
    for d in (c.get("snkrdunk_urls") or [])[:max_snkr]:
        if d.get("url") and d["url"] not in seen:
            seen.add(d["url"])
            # snkrdunk は card_id で引いているので変種は特定済み (番号一致の全変種を混ぜない)。
            out.append({"channel": "snkrdunk", "url": d["url"], "price": d.get("price"),
                        "image": d.get("image", ""), "variant_ok": True})
    return out


def combine(mercari, snkrdunk, mercari_cands=None, max_aux=5):
    """2チャネル結果を束ねる純関数。

    Args:
        mercari: (price_jpy:int, url:str, name:str) or None  (メルカリ最安)
        snkrdunk: {"available":bool,"psa10_price_jpy":int,"psa10_listings":[{price,url}]} (HTTP shape)
                  or {"psa10_count":int,"psa10_details":[...]} (harvest shape) or None
        mercari_cands: [(price:int,url:str,name:str),...] メルカリ正変種の価格昇順候補 (補URL用)
        max_aux: 補URL に載せる代替候補の最大数 (両ch混合の最安 max_aux 件)
    Returns:
        {resourceable, channels, cheapest_jpy, cheapest_channel, cheapest_url,
         mercari_jpy, mercari_url, snkrdunk_jpy, snkrdunk_count, snkrdunk_urls, aux_urls}
        aux_urls = メルカリ＆SNKRDUNK 混合の最安 max_aux 件を **高い順** ([0]=高 … [-1]=最安)。
    """
    channels = []
    cand = []  # (channel, price, url)

    # ★2026-09-04: ありえない仕入値の候補は **この段階で外す** (ユーザー指示
    #   「この段階で、セラーフィルタ含めて仕入れるに値するものにしておくべき」)。
    #   実例: SNKRDUNK が S12A-126 に ¥1,111,111 を出しており、そのまま最安として
    #   採られると 再仕入れ可 と判定され、cost-plus で $11,707 の行になる。
    #   基準は pricing_engine.cost_sanity (全カテゴリ共通・しきい値は global.yaml)。
    def _sane(price):
        if not isinstance(price, int) or price <= 0:
            return True                    # 価格不明はここでは判定しない (別経路で落ちる)
        try:
            import os as _os
            import sys as _sys
            _api = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.dirname(_os.path.abspath(__file__)))), "iMakeBayAPI")
            if _api not in _sys.path:
                _sys.path.insert(0, _api)
            from pricing_engine import cost_sanity
        except Exception:                                      # noqa: BLE001
            return True                    # 判定器が無い環境では従来どおり (後段の門が拾う)
        return cost_sanity(price) is None

    m_price = mercari[0] if (mercari and isinstance(mercari[0], int) and mercari[0] > 0) else None
    if m_price is not None and not _sane(m_price):
        m_price = None
    if m_price:
        channels.append("mercari")
        cand.append(("mercari", m_price, mercari[1] if len(mercari) > 1 else ""))

    s_count = 0
    s_price = None
    snkrdunk_urls = []          # 補URL一覧 (全PSA10出品、価格付)
    if isinstance(snkrdunk, dict):
        if "available" in snkrdunk:
            # HTTP shape (snkrdunk_psa_resource.check_by_keyword): 在庫+最安+PSA10出品一覧(補URL候補)
            if snkrdunk.get("available"):
                s_price = snkrdunk.get("psa10_price_jpy")
                # 画像は **その出品個別の実スラブ写真**(primaryPhoto)を最優先。出品に写真が無い時だけ
                # カード共通の thumbnailUrl にフォールバック(listing ページの og:image はロゴで不可)。
                _simg = snkrdunk.get("card_image", "")
                # psa10_listings = 価格昇順の全PSA10出品 → 補URL列(最安の代替候補)。
                listings = snkrdunk.get("psa10_listings") or []
                snkrdunk_urls = [{"price": d.get("price"), "url": d.get("url", ""),
                                  "image": d.get("image") or _simg}
                                 for d in listings if d.get("url")]
                if not snkrdunk_urls:                 # 後方互換 (psa10_listings 無→card_url 1件)
                    url = snkrdunk.get("card_url", "")
                    snkrdunk_urls = [{"price": s_price, "url": url, "image": _simg}] if url else []
                s_count = len(snkrdunk_urls) or 1
        else:
            # harvest shape (find_psa10_urls_for_card): 個別補URL一覧 (psa10_count/psa10_details)
            s_count = int(snkrdunk.get("psa10_count") or 0)
            details = snkrdunk.get("psa10_details") or []
            snkrdunk_urls = sorted(
                [{"price": d.get("price"), "url": d.get("url", "")}
                 for d in details if isinstance(d, dict) and d.get("url")],
                key=lambda x: (x["price"] is None, x["price"] or 0),
            )
            if not snkrdunk_urls and snkrdunk.get("psa10_urls"):
                snkrdunk_urls = [{"price": None, "url": u} for u in snkrdunk["psa10_urls"]]
            s_price = _min_price([d.get("price") for d in details if isinstance(d, dict)])
        # ★ありえない値の出品は 補URL からも最安からも外す (2026-09-04)。
        #   URL を1本も持たない形 (harvest shape の件数のみ) は触らない —
        #   価格が無い=判定していないので、件数を勝手に0にしない。
        if snkrdunk_urls:
            _kept = [d for d in snkrdunk_urls if _sane(d.get("price"))]
            if len(_kept) != len(snkrdunk_urls):
                snkrdunk_urls = _kept
                s_count = len(_kept)
                s_price = _min_price([d.get("price") for d in _kept]) or None
        elif s_price is not None and not _sane(s_price):
            s_price = None
        if s_count > 0:
            channels.append("snkrdunk")
            s_url = snkrdunk_urls[0]["url"] if snkrdunk_urls else ""
            cand.append(("snkrdunk", s_price if s_price else 10**12, s_url))

    cheapest = None
    priced_cand = [c for c in cand if isinstance(c[1], int) and 0 < c[1] < 10**12]
    if priced_cand:
        cheapest = min(priced_cand, key=lambda x: x[1])

    # --- 補URL: メルカリ＆SNKRDUNK 混合の最安 max_aux 件を 高い順 ([0]=高 … [-1]=最安) ---
    # 「補」= 最安が売切/状態相違時の代替候補。両ch横断で安い順に拾い、列には高い順で並べる。
    pool = []
    for c in (mercari_cands or []):
        if c and isinstance(c[0], int) and c[0] > 0 and len(c) > 1 and c[1]:
            if not _sane(c[0]):            # ★ありえない値は補URLにも載せない
                continue
            pool.append({"price": c[0], "url": c[1], "channel": "mercari"})
    for u in snkrdunk_urls:
        if u.get("url") and isinstance(u.get("price"), int) and u["price"] > 0:
            pool.append({"price": u["price"], "url": u["url"], "channel": "snkrdunk"})
    pool.sort(key=lambda x: x["price"])           # 安い順
    aux_urls = list(reversed(pool[:max_aux]))      # 最安 max_aux 件 → 高い順

    return {
        "resourceable": len(channels) > 0,
        "channels": channels,
        "cheapest_jpy": cheapest[1] if cheapest else None,
        "cheapest_channel": cheapest[0] if cheapest else (channels[0] if channels else None),
        "cheapest_url": cheapest[2] if cheapest else "",
        "mercari_jpy": m_price,
        "mercari_url": (mercari[1] if (mercari and len(mercari) > 1) else "") if m_price else "",
        "snkrdunk_jpy": s_price,
        "snkrdunk_count": s_count,
        "snkrdunk_urls": snkrdunk_urls,   # SNKRDUNK の PSA10出品一覧 (価格昇順)
        "aux_urls": aux_urls,             # 補URL: 両ch混合の最安 max_aux 件 (高い順)
    }


def dedupe_rows(rows, idfn):
    """同一eBay出品の重複行を除去(順序保持)。idfn(row)=itemID。itemID無は url|title で代替キー。

    funnel/CSV 由来で同じ listing が複数行になることがある(2026-06-17 実機: 81行中10重複)。
    同じ現物を2回探索/2回目視するのは無駄なので入口で1本化する。純関数(test可)。
    """
    seen, out = set(), []
    for r in rows:
        iid = idfn(r)
        k = iid or ((r.get("ebay_url", "") or "") + "|" + (r.get("title", "") or ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _load_restock_psa10():
    """funnel RESTOCK∩PSA10 を mercari_psa_resource 経由で取得 (rows: title/ebay_price/...)."""
    import csv
    import glob
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    # 毎回 funnel から最新生成(実需フィルタ込み)→ 古い 03_CSV があっても無視(=手動削除不要)。
    # funnel が無い時だけ既存の 03_CSV にfallback(手動入力の救済)。
    src = mp.build_input_from_funnel()
    if not src:
        files = [p for p in glob.glob(os.path.join(mp.DESK, "03_PSA再仕入れ候補_*.csv"))
                 if "_メルカリ判定" not in os.path.basename(p)]
        if files:
            src = max(files, key=os.path.getmtime)
            print(f"  (funnel無 → 既存CSV使用: {os.path.basename(src)})", flush=True)
    if not src:
        return [], mp
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    deduped = dedupe_rows(rows, lambda r: mp._ebay_item_id(r.get("ebay_url", "") or ""))
    if len(deduped) != len(rows):
        print(f"  重複除去: {len(rows)}→{len(deduped)}行 (同一eBay出品の重複)")
    # RESTOCK対象外(catalog非対応カテゴリ=正しく出品不能→fail-closed skip)を除外。
    # = 毎回「候補なし→依頼」の無限ループを止める(Weiss Schwarz 等)。
    try:
        from sheet_io import read_tab
        excl = {(rr[0] or "").strip() for rr in (read_tab("RESTOCK対象外")[1:] or []) if rr and (rr[0] or "").strip()}
    except Exception:
        excl = set()
    if excl:
        before = len(deduped)
        deduped = [r for r in deduped if mp._ebay_item_id(r.get("ebay_url", "") or "") not in excl]
        if len(deduped) != before:
            print(f"  対象外除外: {before - len(deduped)}件 (catalog非対応カテゴリ等)")
    return deduped, mp


def _backfill_snkr_card_image(cached, row, mp, sp):
    """SNKRDUNK 当日キャッシュに card_image(実カード画像) が無ければ thumbnail だけ HTTP 補完。

    画像配線(thumbnailUrl)導入より前にできたキャッシュは card_image を持たず、RESTOCK確証で
    全候補がサイト既定ロゴになる。Mercari は再scrapeせず(遅い/BAN)、SNKRDUNK の軽い HTTP 検索
    だけ再実行して card_image を後付けする。available でない/card番号不明/取得失敗は元のまま。
    """
    if not (isinstance(cached, dict) and cached.get("available")):
        return cached
    # 旧キャッシュ判定: card_image 欠落 OR psa10_listings が per-listing 画像(image キー)を持たない
    # (82dffc5 前のキャッシュ)。どちらかなら SNKRDUNK を取り直して出品個別の実スラブ写真を入れる。
    _ls = cached.get("psa10_listings") or []
    _stale = (not cached.get("card_image")) or any("image" not in x for x in _ls)
    if not _stale:
        return cached
    updated = dict(cached)
    # per-listing 写真: **キャッシュ済の card_id をそのまま使って** listings だけ取り直す。
    # 再 resolve しない = 変種ドリフト(別カードに解決し直す)を起こさない(2026-06-19 P-053型で発覚)。
    cid = cached.get("card_id")
    if cid:
        try:
            fresh_ls = sp.psa10_listings_for(cid)
        except Exception:
            fresh_ls = None
        if fresh_ls:
            updated["psa10_listings"] = fresh_ls
    # card_image(thumbnail)欠落時のみ search で補完(これは card番号→variant の再 resolve が必要)。
    if not cached.get("card_image"):
        cn = _resource_card_number(row.get("title", "") or "", row.get("key"),
                                   row.get("itemID") or "")
        if cn:
            vh = None
            k = row.get("key")
            if k:
                m = mp.card_meta_for_key(k)
                vh = m.get("hint") if m else None
            try:
                fresh = sp.check_by_keyword(cn, variant_hint=vh)
                if isinstance(fresh, dict) and fresh.get("card_image"):
                    updated["card_image"] = fresh["card_image"]
            except Exception:
                pass
    return updated


def _run_mismatch_pdca(rejected, confirmed_idx, idx_row, targets, cert_map, mp):
    """確認ゲートの不一致(OFF)を PDCA で回す: read台帳→reconcile→write→原因別ルーティング→トレンド。

    Check止まりにしない(pdca_spiral_up_expectation): 前回比 新規/再発/再燃/解決 を出し、
    catalog誤は Catalog修正依頼書を自動生成、cert誤/出品誤は台帳に振り分けて再掲。失敗は警告のみ。
    """
    import datetime
    today = datetime.date.today().isoformat()
    recs = []
    for rj in rejected:
        i = rj.get("idx")
        r = idx_row.get(i, {})
        # targets は {row index: target} の dict(目視対象のみ。確定済スキップ行は含まれない)
        t = targets.get(i, {}) if isinstance(targets, dict) else (
            targets[i] if isinstance(i, int) and i < len(targets) else {})
        iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        recs.append({"itemID": iid, "cert": cert_map.get(iid, ""), "key": r.get("key", ""),
                     "card_no": t.get("card_no", ""), "title": t.get("title", ""),
                     "reason": rj.get("reason"), "psa_image": t.get("psa_image", ""),
                     "catalog_image": t.get("ref_image", ""), "ebay_url": r.get("ebay_url", "")})
    confirmed_iids = {mp._ebay_item_id(idx_row[i].get("ebay_url", "") or "")
                      for i in confirmed_idx if i in idx_row}
    confirmed_iids.discard("")
    try:
        import psa_mismatch_pdca as pdca
        from sheet_io import read_tab, write_rows_to_tab
        prev = pdca.ledger_from_rows(read_tab("PSA不一致台帳"))
        ledger, st = pdca.reconcile(prev, recs, confirmed_iids, today)
        write_rows_to_tab("PSA不一致台帳", pdca.to_tab_rows(ledger))
        print(f"📒 不一致PDCA: 新規{st['new']} 再発{st['recurring']} 再燃{st['reopened']} "
              f"解決{st['resolved']} / 未対処計{st['open']}")
        if st["by_route"]:
            print("   原因内訳: " + " ".join(
                f"{pdca.ROUTE_LABEL.get(k, k)}={v}" for k, v in st["by_route"].items()))
        buckets = pdca.route_buckets(ledger)
        cat = buckets.get("catalog") or []
        if cat:
            reqdir = r"C:/dev/iMak_data/catalog/requests"
            os.makedirs(reqdir, exist_ok=True)
            p = os.path.join(reqdir, f"{today}_psa_mismatch_catalog.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(pdca.build_catalog_request_md(cat, today))
            print(f"   → Catalog修正依頼書: {p} ({len(cat)}件)")
        for k in ("cert", "listing"):
            n = len(buckets.get(k) or [])
            if n:
                print(f"   → {pdca.ROUTE_LABEL[k]}: 未対処{n}件 (台帳「PSA不一致台帳」参照)")
    except Exception as e:
        print(f"⚠ 不一致PDCA skip ({type(e).__name__}: {e})")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    rows, mp = _load_restock_psa10()
    if not rows:
        sys.exit("RESTOCK∩PSA10 がありません (先にファネル分析)。")
    if limit:
        rows = rows[:limit]
    print(f"対象 PSA10: {len(rows)}枚 (2チャネル: メルカリ＆SNKRDUNK)")

    # --- Step6 P1: canonical KEY を血統に通す (itemID で商品管理シートに join) ---
    # 各行に r["key"] = canonical product_id (固有変種) を付与。bare番号でなく KEY で正確な変種を同定する土台。
    # 取得失敗/未マッチ時は r["key"] 無し → 後段は従来の bare番号 fallback (fail-soft)。
    keyed = 0
    itemid_row = {}
    cert_map = {}
    try:
        from sheet_io import product_index
        keymap, itemid_row, cert_map = product_index()
        for r in rows:
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            k = keymap.get(iid) if iid else None
            if k:
                r["key"] = k
                keyed += 1
        print(f"  canonical KEY 付与: {keyed}/{len(rows)}枚 (商品管理シート itemID join)")
    except Exception as e:
        print(f"  ⚠ canonical KEY map 取得失敗 ({type(e).__name__}: {e}) — bare番号で続行")

    # --- Step6 P1b: itemID join 漏れを「出品時 目視確定」資産で補完 (2026-07-24) ---
    # 出品時に HTML viewer で確定した変種は verified_certs.json (cert→product_id) に資産化されている。
    # だが商品管理シートAI列への KEY 書き戻しは promo等 12変種曖昧カードで漏れる(write-keys が
    # 再解決で絞れず skip)→ RESTOCK が「出品したのに未解決」で再目視を要求する欠陥だった。
    # itemID→cert(シートI列, cert_map)→verified_certs で、出品時に払った目視コストを回収する。
    _vc = load_verified_certs()
    if _vc:
        recovered = 0
        _recovered_wb = {}     # itemID→KEY: シートAI列へ書戻し(次回から itemID join で直接解決)
        for r in rows:
            if r.get("key"):
                continue
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            k2 = key_from_verified_cert(cert_map.get(iid, ""), _vc)
            if k2:
                r["key"] = k2
                recovered += 1
                if iid:
                    _recovered_wb[iid] = k2
        if recovered:
            print(f"  🔑 出品時 目視確定を資産回収: {recovered}件 "
                  f"(verified_certs.json cert→KEY / itemID join漏れを補完=再目視不要)")
            # 資産化: 回収KEYをシートAI列へ書戻し → write-keys の書き戻し漏れを恒久治癒
            # (次回は itemID join で直接解決。verified_certs 再recover に毎回依存しない)。
            try:
                from sheet_io import write_keys
                n = write_keys(itemid_row, _recovered_wb)
                print(f"  🔑 回収KEYをシートAI列へ書戻し: {n}行 (次回から itemID join で解決=書き戻し漏れ治癒)")
            except Exception as e:
                print(f"  ⚠ 回収KEY書戻し skip ({type(e).__name__}: {e}) — 今回はメモリ上のKEYで続行")

    # --- pre-search 目視確認ゲート (2026-06-17) ---
    # 「探す前に、仕入れたい正カードが正しいか」を catalog 正カード画像で目視確認 → 確定分だけ探索。
    # 番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)や KEY未解決(正画像なし)を、探索に時間を
    # 使う前に人手で確定する。--no-confirm で skip(全件探索, 非対話/test用)。
    if "--no-confirm" in sys.argv:
        print("  (--no-confirm) 確認ゲートskip、全件探索")
    else:
        import psa_resource_confirm as prc
        # 目視確定済(過去に目視で確定した itemID→KEY)を読み、再目視をスキップ。
        # = 一度確定したカードは再走で再目視しない(目視は資産・負担は使うほど減る)。--review-all で全件再目視。
        confirmed_prev = {}
        cardno_override = {}     # itemID→base card番号(題名から取れない△variant等。Catalog確定の権威値)
        if "--review-all" not in sys.argv:
            try:
                from sheet_io import read_tab as _rt
                for rr in _rt("PSA目視確定済")[1:]:
                    if len(rr) >= 2 and rr[0] and rr[1]:
                        confirmed_prev[rr[0].strip()] = rr[1].strip()
            except Exception as e:
                print(f"  ⚠ 目視確定済 読込skip ({type(e).__name__}: {e})")
        try:
            from sheet_io import read_tab as _rt2
            for rr in _rt2("PSA番号補完")[1:]:
                if len(rr) >= 2 and rr[0] and rr[1]:
                    cardno_override[rr[0].strip()] = rr[1].strip()
        except Exception as e:
            print(f"  ⚠ 番号補完 読込skip ({type(e).__name__}: {e})")
        total_rows = len(rows)
        auto_idx = set()       # 変種確定済=再目視スキップ
        todo = []              # (i, r) 今回目視する行
        for i, r in enumerate(rows):
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            # KEY解決済(itemID join or 過去目視で確定)= 変種が既に確定 → 再目視しない。
            # 誤りの最終捕捉は RESTOCK視覚確証(現物 vs 仕入候補)で行う(= 二重に目視させない)。
            if r.get("key"):
                auto_idx.add(i)
            elif iid and iid in confirmed_prev:
                r["key"] = confirmed_prev[iid]
                auto_idx.add(i)
            else:
                todo.append((i, r))
        if auto_idx:
            print(f"  ⏭ 変種確定済(KEYあり) {len(auto_idx)}件は再目視スキップ。新規/未解決 {len(todo)}件のみ目視")

        targets_by_idx = {}    # {row index: target}
        if todo:
            print(f"▶ ①現物画像(eBay GetItem)取得中 {len(todo)}件...", flush=True)
        for n, (i, r) in enumerate(todo):
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            # ① 現物: eBay出品画像(必ず有る)→ 無ければ cert→psa_cache フォールバック
            psa_img = prc.ebay_listing_image(iid) or prc.psa_image_for_cert(cert_map.get(iid) if iid else None)
            # ② 候補: その card番号の catalog 変種(ユーザーが正しい変種を選ぶ)。
            # 題名から取れない△variant等は「PSA番号補完」(Catalog確定のbase番号)で補う → ②候補が出る。
            card_no = _resource_card_number(r.get("title", "") or "", r.get("key"), iid) or cardno_override.get(iid, "")
            # title_hint = eBayタイトル。Pokemon等 コレクター番号(NNN/095)fallback時に
            # 同番号の複数セットからキャラ名でユーザー特定を助ける(2026-07-24)。
            # ★2026-07-29: KEY のカテゴリで絞る。番号体系は作品を跨いで衝突するため
            # (実測 ST04-005 = ワンピース「クイーン」/ ガンダム「ストライクダガー」)、
            # 絞らないと **別作品のカードが選択肢に並び、人が選べてしまう**。
            variants = mp.catalog_variants_for_cardno(
                card_no, title_hint=r.get("title", "") or "",
                category=mp.split_key(r.get("key"))[0])
            # 解決済KEY自身は必ず候補に含める(card番号ヒット漏れ/大小文字差でも②が出る・既定選択)
            rk = r.get("key")
            if rk and not any(c["product_id"] == rk for c in variants):
                meta = mp.card_meta_for_key(rk)
                if meta and meta.get("image"):
                    variants = [{"product_id": rk, "name_jp": meta.get("name_jp", ""),
                                 "set": meta.get("set", ""), "image": meta.get("image", ""),
                                 "variant_type": meta.get("variant_type", ""), "rarity": meta.get("rarity", ""),
                                 "get_info": meta.get("get_info", "")}] + variants

            def _label(c):
                # 画像が死んでても変種を特定できるよう alt_art/rarity/set/入手元 をラベルに出す
                extra = " / ".join(x for x in [c.get("variant_type", ""), c.get("rarity", ""),
                                               c.get("set") or c.get("get_info", "")] if x)
                base = f'[{c["product_id"]}] {c.get("name_jp", "")}'
                return base + (f' ｜ {extra}' if extra else "")

            candidates = [{"key": c["product_id"], "image": c["image"], "label": _label(c)}
                          for c in variants]
            targets_by_idx[i] = {
                "idx": i, "title": (r.get("title") or "")[:90], "card_no": card_no,
                "psa_image": psa_img, "candidates": candidates,
                "resolved_key": r.get("key"),          # 既定選択(itemID join 済なら)
                "ebay_url": r.get("ebay_url", ""), "no_image": not psa_img,
            }
            if (n + 1) % 20 == 0:
                print(f"   {n+1}/{len(todo)}", flush=True)

        if targets_by_idx:
            print(f"▶ 目視確認ゲート: {len(targets_by_idx)}件をブラウザ表示。① 現物 と ② 候補(変種選択)の一致を確認...")
            res = prc.confirm_targets(list(targets_by_idx.values()))
            if res is None:
                sys.exit("確認がタイムアウト/未確定。探索せず終了(再実行してください)。")
            confirmed, rejected = res["confirmed"], res["rejected"]
        else:
            confirmed, rejected = [], []
            print("  目視対象なし(全件 確定済)→ 探索のみ")

        idx_row = {i: r for i, r in enumerate(rows)}    # filter前に idx→row 固定
        # 選択された変種KEYを各行に反映 + 商品管理シート書戻し + 目視確定済 追記用に収集
        writeback = {}
        new_confirmed = {}     # itemID→KEY 今回新規に目視確定(次回スキップ用)
        for c in confirmed:
            i, key = c["idx"], (c.get("key") or "")
            r = idx_row.get(i)
            if r is None or not key:
                continue
            old = r.get("key")
            r["key"] = key
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            if iid:
                new_confirmed[iid] = key
                if key != old:                          # 新規解決 or 訂正のみ書戻し
                    writeback[iid] = key
        # PDCA: 不一致(OFF)を台帳に蓄積 → 原因別振り分け → 再発/解決トレンド
        # auto_idx(itemID join / 過去目視で KEY 解決済=今回スキップ)も「確定」として渡す。
        # これを渡さないと、KEY が入って解決済の行が台帳で永久に「未対処」のまま毎日再発行される
        # (= Catalog への同一依頼の無限再発行。2026-06-18 真因)。
        _run_mismatch_pdca(rejected, list(auto_idx) + [c["idx"] for c in confirmed],
                           idx_row, targets_by_idx, cert_map, mp)
        # 確定した変種KEYを商品管理シートAI列に書戻し(目視を資産化=次回から解決済)
        if writeback:
            try:
                from sheet_io import write_keys
                n = write_keys(itemid_row, writeback)
                print(f"🔑 商品管理シートAI列にKEY書戻し: {n}行 (目視確定を資産化=次回 itemID join で解決済)")
            except Exception as e:
                print(f"⚠ KEY書戻し失敗: {type(e).__name__}: {e}")
        # 目視確定済 を追記(次回の再目視スキップ用) — auto分は既存なので新規確定のみ追加
        if new_confirmed:
            try:
                from sheet_io import read_tab as _rt2, write_rows_to_tab as _wt
                rec = {}
                for rr in _rt2("PSA目視確定済")[1:]:
                    if len(rr) >= 2 and rr[0]:
                        rec[rr[0].strip()] = rr[1].strip()
                rec.update(new_confirmed)
                _wt("PSA目視確定済", [["itemID", "KEY"]] + [[k, v] for k, v in rec.items()])
                print(f"  📝 目視確定済 記録: +{len(new_confirmed)}件 (計{len(rec)})")
            except Exception as e:
                print(f"  ⚠ 目視確定済 記録skip ({type(e).__name__}: {e})")
        conf_idx = auto_idx | {c["idx"] for c in confirmed if c.get("key")}
        if not conf_idx:
            sys.exit("確定0件。探索せず終了。台帳「PSA不一致台帳」で原因対処を。")
        rows = [r for i, r in enumerate(rows) if i in conf_idx]
        print(f"  ✅ 確定 {len(conf_idx)}/{total_rows}件 "
              f"(確定済skip {len(auto_idx)} + 今回目視 {len(conf_idx) - len(auto_idx)}) → 選択変種で探索")

    # --- 再仕入れ待ち台帳の End候補 を再チェックに合流 ---
    # 過去に「再仕入れ不能(End候補)」になった行を毎回再探索(供給は動的=後で出れば RESTOCK)。
    # 目視確定済(KEY付与済)なので確認ゲートは通さず、探索だけ合流する。
    try:
        from sheet_io import read_tab, write_rows_to_tab
        import psa_restock_wait as prw
        wled = prw.ledger_from_rows(read_tab("再仕入れ待ち"))
        have = {mp._ebay_item_id(r.get("ebay_url", "") or "") for r in rows}
        # ★2026-09-04 ユーザー指摘「再仕入れ対象の基準がおかしい。出品中で在庫がなくて、でしょ？」
        #   再仕入れは **生きている出品の数量を戻す**機能。ファネル経路は eBay の出品中
        #   レポートが元なので条件を満たすが、**この台帳経路は出品の生死を見ていなかった**。
        #   出品が終了すると funnel からは消えるのに台帳は持ち続けるので、終了済が毎回
        #   よみがえって RESTOCK確定 に入り、cert が引けず「入稿待ち」で残り続けていた
        #   (実測 5件。CULL で落とした分も含むが、原因は取下げ基準ではなく **出品が無い**こと)。
        from ebay_getitem_images import fetch_listing_status as _wls
        _cands = [t for t in prw.recheck_targets(wled)
                  if t["itemID"] and t["itemID"] not in have]
        merged, _ended = 0, []
        for t in _cands:
            st = _wls(t["itemID"])
            if st is not None and st != "Active":
                _ended.append(t)          # 終了済 = 戻せない。分からない時は従来どおり合流
                continue
            rows.append({"title": t["title"], "ebay_url": t["ebay_url"],
                         "key": t["key"], "set_no": ""})
            merged += 1
        if merged:
            print(f"  ♻ 再仕入れ待ち台帳から {merged}件を再チェックに合流(目視済=skip)")
        if _ended:
            import datetime as _dtx
            wled, _n = prw.mark_ended(wled, [t["itemID"] for t in _ended],
                                      _dtx.date.today().isoformat())
            write_rows_to_tab("再仕入れ待ち", prw.to_tab_rows(wled))
            print(f"  🚫 出品が終了していた {len(_ended)}件は再仕入れの対象から外しました "
                  f"(台帳に『終了済』で残す。reviseでは戻せない)")
            for t in _ended[:8]:
                print(f"       {t['itemID']} {(t.get('title') or '')[:52]}")
    except Exception as e:
        print(f"  ⚠ 待ち台帳読込skip ({type(e).__name__}: {e})")

    # --- 研究キャッシュ: 当日の Mercari/SNKRDUNK 結果を再利用(再走の再スクレイプ/BANリスク回避)。--fresh で無視 ---
    import datetime as _dt
    import json as _json
    _today = _dt.date.today().isoformat()
    _cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_research_cache.json")
    _rcache = {}
    if "--fresh" not in sys.argv:
        try:
            with open(_cache_path, encoding="utf-8") as _f:
                _rcache = _json.load(_f)
        except Exception:
            _rcache = {}
    _iids = [mp._ebay_item_id(r.get("ebay_url", "") or "") for r in rows]

    def _cache_hit(iid):
        c = _rcache.get(iid)
        return c if (c and c.get("date") == _today) else None

    # --- SNKRDUNK (HTTP-only。当日キャッシュ分は再利用) ---
    # ★2026-07-26: SNKRDUNK(全件・HTTP高速)を **先に** 取得 → メルカリは「新規再仕入れ可が N件
    #   見つかるまで」保留分をチャンク検索するループに(RESTOCK_TARGET_NEW>0 のとき)。SNKRDUNK済で
    #   resourceable が分かるので、足りない分だけメルカリを掘る = 無駄スクレイプ最小・確証が毎回N件出る。
    print("▶ SNKRDUNK PSA10 取得中 (HTTP, 当日分はキャッシュ再利用)...")
    import snkrdunk_psa_resource as sp
    snkr_res = {}
    for i, r in enumerate(rows):
        c = _cache_hit(_iids[i])
        if c and "snkrdunk" in c:
            snkr_res[i] = _backfill_snkr_card_image(c["snkrdunk"], r, mp, sp)
            continue
        cn = _resource_card_number(r.get("title", "") or "", r.get("key"),
                                   r.get("itemID") or "")
        if not cn:
            snkr_res[i] = None
            print(f"  [{i+1}/{len(rows)}] (card番号抽出不可) skip", flush=True)
            continue
        # Step6 P3: canonical KEY → catalog の set+name を variant_hint に。同番号の複数 print を正選択。
        vhint = None
        k = r.get("key")
        if k:
            meta = mp.card_meta_for_key(k)
            if meta:
                vhint = meta.get("hint")  # set + get_info(入手元set) + variant_type + rarity + name_jp + key
        # 多変種プロモは単一一致でも変種確証必須(番号だけで別変種を掴まない・2026-07-24)
        _mv = mp._is_multi_variant(cn, mp.split_key(k)[0])   # 別作品の変種を数に入れない
        res = sp.check_by_keyword(cn, variant_hint=vhint, multi_variant=_mv)
        snkr_res[i] = res
        if res.get("_error") == "card_not_found":
            print(f"  [{i+1}/{len(rows)}] {cn}: SNKRDUNK未登録", flush=True)
        elif res.get("available"):
            print(f"  [{i+1}/{len(rows)}] {cn}: PSA10 ¥{res.get('psa10_price_jpy')}", flush=True)
        else:
            print(f"  [{i+1}/{len(rows)}] {cn}: PSA10在庫なし", flush=True)

    # --- メルカリ (一括 Selenium。当日キャッシュ分は再利用、未キャッシュのみスクレイプ) ---
    mercari_res = {}
    _to_scrape_all = [i for i in range(len(rows)) if not (_cache_hit(_iids[i]) and "mercari" in _cache_hit(_iids[i]))]
    for i in range(len(rows)):
        c = _cache_hit(_iids[i])
        if c and "mercari" in c:
            mercari_res[i] = c["mercari"]

    # 既に確定/レビュー済の itemID(=視覚確証に出さない) → 「新規」再仕入れ可の判定に使う。
    _processed_iids = set()
    try:
        from sheet_io import read_tab as _rt_proc
        _processed_iids = (_restock_confirmed_iids(_rt_proc("RESTOCK確定"))
                           | _review_skip_iids(_rt_proc(REVIEW_SKIP_TAB)))
    except Exception as _e:
        print(f"  ⚠ 既処理itemID読込skip ({type(_e).__name__}) — 新規カウントは全resourceable基準")

    def _count_new_resourceable():
        """現在の snkr_res + mercari_res で「新規(未確定・未レビュー)の再仕入れ可」件数。
        = 視覚確証HTMLに実際に出る件数と一致(確証は _processed_iids を除外表示するため)。"""
        pairs = []
        for _i, _r in enumerate(rows):
            _mr = mercari_res.get(_i) or {}
            _c = combine(_mr.get("best"), snkr_res.get(_i), mercari_cands=_mr.get("cands"), max_aux=5)
            _iid = mp._ebay_item_id(_r.get("ebay_url", "") or "")
            pairs.append((bool(_c["resourceable"]), _iid))
        return _count_new_resourceable_from(pairs, _processed_iids)

    def _scrape_chunk(idxs):
        if not idxs:
            return
        try:
            cards = [{**mp.build_card_query(rows[i].get("title", ""), rows[i].get("set_no", ""), rows[i].get("key")),
                      "ebay_item_id": _iids[i]} for i in idxs]
            scraped = mp.fetch_mercari_cheapest(cards)
            for j, i in enumerate(idxs):
                mercari_res[i] = scraped.get(j)
        except Exception as e:
            print(f"  ⚠ メルカリ skip ({type(e).__name__}: {e}) — SNKRDUNKのみで判定")

    _batch = int(os.environ.get("RESTOCK_SCRAPE_BATCH", "10"))
    _target = int(os.environ.get("RESTOCK_TARGET_NEW", "0"))       # >0 で「新規N件見つかるまで」ループ
    _max_scrape = int(os.environ.get("RESTOCK_MAX_SCRAPE", "60"))  # BAN安全: 1走行のメルカリ検索上限
    _cache_reuse = len(rows) - len(_to_scrape_all)

    if _target > 0:
        # ★「新規再仕入れ可が _target 件見つかるまで」保留分を _batch 刻みで検索(BAN throttle維持)。
        # _max_scrape で1走行の検索上限を打ち切り。保留が尽きても止める(在庫が実際に無ければ N件出ない=正)。
        # 未検索の残りは End候補にせず判定保留(fail-closed)。
        _chunk = _batch if _batch > 0 else 10
        print(f"▶ メルカリ: 新規再仕入れ可 {_target}件 見つかるまで検索(当日キャッシュ {_cache_reuse}件 / "
              f"保留 {len(_to_scrape_all)}件 / 1走行上限 {_max_scrape}件・{_chunk}件刻み)")
        _ptr = 0
        _have = _count_new_resourceable()
        print(f"  ⟳ 起点(キャッシュ+SNKRDUNK)で新規 {_have}/{_target}", flush=True)
        while _have < _target and _ptr < len(_to_scrape_all) and _ptr < _max_scrape:
            _chunk_idxs = _to_scrape_all[_ptr:_ptr + _chunk]
            _scrape_chunk(_chunk_idxs)
            _ptr += len(_chunk_idxs)
            _have = _count_new_resourceable()
            print(f"  ⟳ 新規再仕入れ可 {_have}/{_target}(検索 {_ptr}/{len(_to_scrape_all)})", flush=True)
        _deferred = set(_to_scrape_all[_ptr:])
        _reason = ("目標到達" if _have >= _target
                   else ("保留尽き=在庫ある分は探し切った" if _ptr >= len(_to_scrape_all)
                         else f"1走行上限{_max_scrape}件で打切り"))
        print(f"  ✓ 新規 {_have}件 ({_reason})"
              + (f" / 次回送り {len(_deferred)}件(判定保留)" if _deferred else ""))
    else:
        # 従来: 固定 _batch 件だけ検索(残りは判定保留)。RESTOCK_SCRAPE_BATCH=0 でメルカリ再走なし。
        _deferred = set(_to_scrape_all[_batch:]) if _batch >= 0 else set()
        _to_scrape = _to_scrape_all[:_batch] if _batch > 0 else ([] if _batch == 0 else _to_scrape_all)
        print(f"▶ メルカリ最安取得: 当日キャッシュ再利用 {_cache_reuse}件 / 今回スクレイプ {len(_to_scrape)}件"
              + (f" / 次回送り {len(_deferred)}件(End候補にしない=判定保留)" if _deferred else ""))
        _scrape_chunk(_to_scrape)

    # 研究キャッシュ更新(当日付き) — 次回の同日再走はスクレイプ不要に。
    # ★2026-07-24 fail-closed: メルカリ取得失敗(_error)は **キャッシュに残さない** →
    # 次サイクルで再取得される(「取れなかっただけ」を「在庫なし」として焼き付けない)。
    def _mercari_errored(m):
        return isinstance(m, dict) and m.get("_error")
    for i in range(len(rows)):
        if _iids[i]:
            _entry = {"snkrdunk": snkr_res.get(i), "date": _today}
            _m = mercari_res.get(i)
            if not _mercari_errored(_m):
                _entry["mercari"] = _m       # 成功/在庫なし(確定)のみキャッシュ
            _rcache[_iids[i]] = _entry
    try:
        with open(_cache_path, "w", encoding="utf-8") as _f:
            _json.dump(_rcache, _f, ensure_ascii=False)
    except Exception as e:
        print(f"  ⚠ 研究キャッシュ保存skip ({type(e).__name__}: {e})")

    # --- 統合 + 出力 ---
    import datetime as _dt
    _judged_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")  # 可否判定(supply確認)の時刻
    MAX_AUX = 5  # 補URL列数 (AC-AG 相当)
    aux_cols = [f"補URL{k+1}" for k in range(MAX_AUX)]
    out_rows = [["set_no", "title", "再仕入れ可否", "判定日時", "チャネル", "最安¥", "最安チャネル",
                 "mercari¥", "mercari_URL", "snkrdunk¥", "snkrdunk件数",
                 *aux_cols, "ebay_url"]]
    go = 0
    aux_writeback = {}   # {商品管理シート行番号: [補URL,...]} (itemID join できた行のみ)
    wait_end = []        # 再仕入れ不能(End候補) → 待ち台帳へ
    wait_resourceable = set()   # 再仕入れ可 itemID → 待ち台帳で「復活可」に
    restock_cands = []   # POC-A: 再仕入れ可 → RESTOCK視覚確証ビューア用
    held_unknown = 0     # ★取得失敗=在庫不明 → End候補にせず判定保留(次サイクル再チェック)
    held_list = []       # 在庫不明を待ち台帳に蓄積(孤児化防止・毎回再取得)
    for i, r in enumerate(rows):
        mr = mercari_res.get(i) or {}
        c = combine(mr.get("best"), snkr_res.get(i),
                    mercari_cands=mr.get("cands"), max_aux=MAX_AUX)
        _iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        # ★2026-07-24 fail-closed: メルカリ「取得失敗(_error)」or「今回バッチ送り(_deferred)」で
        # SNKRDUNK も在庫確定なし → 「本当に無い」か「まだ確認してない」か不明 → End候補にしない
        # (=取下げに倒さない)。判定保留=次サイクルで再チェック。
        _mercari_unknown = (i in _deferred) or bool(
            mercari_res.get(i) and isinstance(mercari_res.get(i), dict)
            and mercari_res.get(i).get("_error"))
        if c["resourceable"]:
            go += 1
            if _iid:
                wait_resourceable.add(_iid)
            _cands = _build_visual_candidates(mr, c)
            try:
                _cur = float(r.get("ebay_price")) if r.get("ebay_price") else None
            except (TypeError, ValueError):
                _cur = None
            restock_cands.append({
                "itemID": _iid, "card_no": _resource_card_number(r.get("title", "") or "", r.get("key")) or "",
                # key も持ち回る: 確証UIの ⚠️多変種判定を **カテゴリで絞る**ため(2026-07-29)。
                # 無いと別作品の同番号を変種として数え、警告が過剰に出る。
                "key": r.get("key", ""),
                "title": (r.get("title") or "")[:90], "ebay_url": r.get("ebay_url", ""),
                "candidates": _cands, "cost": c.get("cheapest_jpy"), "cur": _cur,
                "channel": c.get("cheapest_channel"), "url": c.get("cheapest_url")})
        elif _mercari_unknown:
            held_unknown += 1   # 在庫不明 → End候補に落とさない(fail-closed)。次回再取得。
            if _iid:
                held_list.append({"itemID": _iid, "key": r.get("key", ""),
                                  "card_no": _resource_card_number(r.get("title", "") or "", r.get("key")) or "",
                                  "title": (r.get("title") or "")[:90], "ebay_url": r.get("ebay_url", "")})
        elif _iid:
            wait_end.append({"itemID": _iid, "key": r.get("key", ""),
                             "card_no": _resource_card_number(r.get("title", "") or "", r.get("key")) or "",
                             "title": (r.get("title") or "")[:90], "ebay_url": r.get("ebay_url", "")})
        # 補URL: メルカリ＆SNKRDUNK 混合の最安 MAX_AUX 件を 高い順 (URLのみ、価格は各¥列に既出)。
        # 主URL(H列=mercari_URL)とは重複させない(= H列とK列が同じになるのを防ぐ)。
        aux = [u["url"] for u in c["aux_urls"]
               if u.get("url") and u["url"] != c.get("mercari_url")]
        # 商品管理シートの 補URL列(AC-AG)へ書戻し用に収集 (itemID で行特定)
        iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        rn = itemid_row.get(iid) if iid else None
        if rn and aux:
            aux_writeback[rn] = aux
        aux += [""] * (MAX_AUX - len(aux))
        # ★C列(再仕入れ可否)は3値: 可◎ / まだ探してない(判定保留=在庫不明) / 探して無い(End候補)。
        # 従来は2値で「判定保留」も「不能✕(End候補)」表示=「探して無い」と誤読させてた(2026-07-26 ユーザー指摘)。
        # _mercari_unknown = メルカリ未検索(batch送り)or取得失敗 → 在庫不明(次回再取得)。fail-closed。
        if c["resourceable"]:
            _c_status = "再仕入れ可◎"
        elif _mercari_unknown:
            _c_status = "⏸判定保留(未検索/在庫不明)"
        else:
            _c_status = "不能✕(End候補)"
        out_rows.append([
            r.get("set_no") or mp.search_keyword(r.get("title", ""), "").replace("PSA10 ", ""),
            (r.get("title") or "")[:60],
            _c_status,
            _judged_at,
            "/".join(c["channels"]) or "-",
            c["cheapest_jpy"] or "", c["cheapest_channel"] or "",
            c["mercari_jpy"] or "", c["mercari_url"],
            c["snkrdunk_jpy"] or "", c["snkrdunk_count"],
            *aux, r.get("ebay_url", ""),
        ])
    _end_n = len(rows) - go - held_unknown
    print(f"\n再仕入れ可: {go}/{len(rows)}  不能(End候補): {_end_n}"
          + (f"  ⏸判定保留(メルカリ取得失敗=在庫不明・次回再取得): {held_unknown}" if held_unknown else ""))
    if held_unknown:
        print("  ⚠ 保留分は End候補にしていません(取れなかった=在庫なしに倒さない/fail-closed)。"
              "次サイクルで再取得されます。")
    # 探索後ビューアは廃止(探索前の確認ゲートで変種確認済 + 静的HTMLは画像プロキシ不可のため)。

    # 再仕入れ待ち台帳を更新: End候補は蓄積(消さず毎回再チェック)、供給戻りは「復活可」に。
    try:
        import datetime
        import psa_restock_wait as prw
        from sheet_io import read_tab, write_rows_to_tab
        today = datetime.date.today().isoformat()
        prev = prw.ledger_from_rows(read_tab("再仕入れ待ち"))
        wled, wst = prw.reconcile(prev, wait_end, wait_resourceable, today, held_candidates=held_list)
        write_rows_to_tab("再仕入れ待ち", prw.to_tab_rows(wled))
        print(f"♻ 再仕入れ待ち台帳: 新規{wst['new']} 継続{wst['still_waiting']} "
              f"復活{wst['revived']} 在庫不明{wst.get('unknown', 0)} / 待ち計{wst['total_wait']}")
        if wst["revived"]:
            print(f"   → 復活可{wst['revived']}件(供給戻り)= RESTOCK対象。タブ「再仕入れ待ち」上段参照")
    except Exception as e:
        print(f"⚠ 再仕入れ待ち台帳更新skip ({type(e).__name__}: {e})")

    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("PSA再仕入れ", out_rows)
        print(f"📊 「PSA再仕入れ」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
        # 出品状態列を RESTOCK確定 join で自動付与(手動スナップショット廃止=フロー内更新)。
        try:
            from restock_funnel_status import update_funnel_listing_status
            _t = update_funnel_listing_status()
            print(f"   📍 出品状態列 同期: {_t}")
        except Exception as _e:
            print(f"   ⚠ 出品状態列 同期skip: {type(_e).__name__}: {_e}")
    except Exception as e:
        print(f"⚠ スプシ更新失敗: {type(e).__name__}: {e}")

    # ★2026-08-03 ユーザー指示「目視を経由せずにカードを特定することはやめよう」で **書込を停止**。
    #
    # 何が起きていたか:
    #   ここは `aux_writeback` (= **メルカリ + SNKRDUNK 混合**の候補URL / 上の :838 参照) を
    #   **確証UIを一度も通さずに** 商品管理シートの補URL(AC-AG)へ直接書いていた。
    #   「SNKRDUNK は cert で個体特定できるから安全」という理解は**誤り**で、実際は
    #   `check_by_keyword(card_number)` = **カード番号での検索**。同番号に複数変種があれば
    #   メルカリと同じく別変種を掴む (2026-08-03 実測で判明)。
    #
    # なぜ止めるのが正しいか (実害):
    #   誤った補URLは表示が汚れるだけでは済まない。監視くんがその価格を M列に書き、
    #   `N=(M or F)-K` が拾い、**価格エンジンが出品価格をその安値から決める**。
    #   2026-08-03: 別変種(通常版 ¥12,200)を掴んだ結果、ミラー版(¥57,500)の出品が
    #   **$169.98 で出ていた** (正しくは $640.98 = 3.8倍差)。オファーが来て偶然気づいた。
    #
    # 候補は捨てない: `psa_research_cache.json` に保存済み (上の「研究キャッシュ保存」)。
    #   `psa_hoju_fill.py confirm` の視覚確証UIが同じ cache を読んで人に見せるので、
    #   **目視を通ってから**補URLに入る。ここで書かなくても供給は失われない。
    if aux_writeback:
        _n_url = sum(len(v) for v in aux_writeback.values())
        print(f"🔒 補URL(AC-AG) の自動書戻しは **停止中** "
              f"(候補 {len(aux_writeback)}行 / {_n_url}本 は cache に保持)")
        print("   → 目視を通すこと: 出品くんパネルの「補URL補強(昼確認)」"
              "= `psa_hoju_fill.py confirm`")

    # --- POC-A: RESTOCK視覚確証ビューア(再仕入れ可のみ)→ RESTOCK確定リスト + V8自動利益判定 ---
    # 不可逆(RESTOCK=出品復活→売れたら仕入)の前に「① 現物 vs 仕入候補(買う物)」を視覚一致確認。
    # 確定分を「RESTOCK確定」タブに出力(eBay書込はしない=手動GO。POC-B/iMakReviseで revise)。
    if "--no-confirm" not in sys.argv and restock_cands:
        _run_restock_confirm(restock_cands, mp, cert_map)


def _v8_label(cost_jpy, cur_usd, mp):
    """最安¥(仕入値)から新規と同じ pricing_engine で「利益が出る出品価格(cost-plus)」を算出し、市場と比較。

    コストプラス運用なので出品価格=V8推奨にすれば売れる限り赤字にならない。判定するのは
    『その cost-plus 価格が市場(現価格)で通るか=売れるか』:
      - V8推奨 ≤ 市場 → ✅市場内(利益価格でも売れる)
      - V8推奨 > 市場 → ⚠仕入高(利益出すには市場超の価格が必要=売れにくい / 旨味薄)
    """
    if not cost_jpy or not cur_usd:
        return ""
    try:
        import pricing_engine
        cat = getattr(mp, "CATEGORY", "tcg")
        rec = pricing_engine.compute_listing_price(cost_jpy=cost_jpy, median_usd=cur_usd, category=cat)["price"]
        if rec <= cur_usd:
            return f"✅市場内 (V8出品${rec:.0f} ≤ 市場${cur_usd:.0f} / 原価¥{cost_jpy})"
        return f"⚠仕入高:市場で売れにくい (利益には${rec:.0f}必要 > 市場${cur_usd:.0f} / 原価¥{cost_jpy})"
    except Exception as e:
        return f"V8計算不可({type(e).__name__})"


def _is_high_cost(v8_label):
    """V8ラベルが「仕入高(売れにくい)」か(純関数)。照合で間引く判定。

    _v8_label は「✅市場内 ...」/「⚠仕入高:市場で売れにくい ...」/「」(判定不能)/「V8計算不可」を返す。
    仕入高 = ⚠仕入高 で始まる時のみ True。判定不能・市場内・計算不可は False(=照合に出す)。
    """
    return bool(v8_label) and v8_label.startswith("⚠仕入高")


def _count_new_resourceable_from(pairs, processed_iids):
    """[(resourceable_bool, itemID), ...] → 新規(未処理=確定/レビュー済でない)の再仕入れ可 件数(純関数)。

    「新規N件見つかるまで」ループの停止判定に使う。itemID 空(join不能)の resourceable も
    新規として数える(確証には出るため)。processed_iids = RESTOCK確定 ∪ レビュー済 の itemID。
    """
    seen = set()
    cnt = 0
    for res, iid in pairs:
        if not res:
            continue
        if iid:
            if iid in processed_iids or iid in seen:
                continue
            seen.add(iid)
        cnt += 1
    return cnt


def _restock_confirmed_iids(existing_rows):
    """RESTOCK確定タブ既存行から itemID 集合を返す(純関数)。再表示しない判定に使う。"""
    if not existing_rows or len(existing_rows) < 2:
        return set()
    return {(r[0] or "").strip() for r in existing_rows[1:] if r and (r[0] or "").strip()}


def _merge_restock_out(existing_rows, new_rows, default_header):
    """既存RESTOCK確定行 + 新規確定行 をマージ(純関数)。

    既存を維持しつつ新規を追加(itemID重複は新規優先)。**上書き(replace)で既存の実行済記録を
    消さないため**(2026-06-22: 新規5件だけ確証すると既存12件が消える上書きバグの根治)。
    existing_rows 空なら default_header + new_rows。
    """
    header = existing_rows[0] if existing_rows else default_header
    new_iids = {(r[0] or "").strip() for r in new_rows if r and (r[0] or "").strip()}
    kept = [r for r in (existing_rows[1:] if existing_rows else [])
            if r and (r[0] or "").strip() and (r[0] or "").strip() not in new_iids]
    return [header] + kept + new_rows


REVIEW_SKIP_TAB = "RESTOCK確証スキップ"
REVIEW_SKIP_HEADER = ["itemID", "card_no", "title", "理由", "日付", "ebay_url"]


# ★2026-07-29: 補URL側 (psa_hoju_fill) と同じく **期限なしで永久に伏せていた**。
# RESTOCK は「売れた後の再仕入れ」なので、埋もれると直接 機会損失になる。
# 「違う」の主因の一つは *その日* 正変種が売られていないことなので、翌日には再挑戦する
# (ユーザー判断 2026-07-29「即対応していかないと生きていけない。翌日でいい」)。
REVIEW_SKIP_COOLDOWN_DAYS = 1


def _review_skip_iids(skip_rows, today=None):
    """RESTOCK確証スキップ タブ既存行から itemID 集合(純関数)。視覚確証で再表示しない判定。

    today を渡すと cooldown 判定する (翌日以降は集合から外れる = 再表示)。
    日付が読めない行は伏せたまま (判定材料なしの再表示は毎回同じものが出るため)。
    today 省略時は従来どおり全行対象 (後方互換)。
    """
    if not skip_rows or len(skip_rows) < 2:
        return set()
    out = set()
    for r in skip_rows[1:]:
        if not r or not (r[0] or "").strip():
            continue
        if today is not None and not _review_skip_active(r[4] if len(r) > 4 else "", today):
            continue
        out.add((r[0] or "").strip())
    return out


def _review_skip_active(date_str, today):
    """その行がまだ伏せる期間内か(純関数)。日付が読めない行は True(伏せたまま)。"""
    try:
        import datetime
        age = (datetime.date.fromisoformat((today or "").strip())
               - datetime.date.fromisoformat((date_str or "").strip())).days
    except Exception:
        return True
    return age < 0 or age < REVIEW_SKIP_COOLDOWN_DAYS


def count_workload(today=None):
    """押したら『今すぐ照合に出せる件数』を **探索せずに** 数える (パネルのヒント用・2026-09-01).

    ★scrape も eBay API も1回も使わない。材料は funnel CSV とスプシ3タブだけ
      (表示のために API 枠を使わない = cull_end / shelf_evict と同じ約束)。
    ★絞り込みは `mercari_psa_resource.restock_psa10_candidates` を通す。
      ボタン本体と同じ関数なので、条件が片方だけズレることがない。
    """
    import csv as _csv
    import datetime as _dt
    import glob as _glob
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import mercari_psa_resource as mp
        files = _glob.glob(os.path.join(mp.FUNNEL_DIR, "funnel_*.csv"))
        if not files:
            return {"error": "funnel CSV が無い (先に 📊 ファネル分析)"}
        src = max(files, key=os.path.getmtime)
        frows = list(_csv.DictReader(open(src, encoding="utf-8")))
        _all, cands = mp.restock_psa10_candidates(frows)
        uniq, seen = [], set()
        for r in cands:
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            if iid and iid in seen:
                continue
            if iid:
                seen.add(iid)
            uniq.append(iid)
        age_d = (_dt.date.today() - _dt.date.fromtimestamp(os.path.getmtime(src))).days
        base = {"targets": len(uniq), "funnel": os.path.basename(src), "funnel_age": age_d}
        try:
            from sheet_io import read_tab
            t = today or _dt.date.today().isoformat()
            processed = (_restock_confirmed_iids(read_tab("RESTOCK確定"))
                         | _review_skip_iids(read_tab(REVIEW_SKIP_TAB), t))
            excl = {(rr[0] or "").strip()
                    for rr in (read_tab("RESTOCK対象外")[1:] or []) if rr and (rr[0] or "").strip()}
        except Exception as e:                                 # noqa: BLE001
            # スプシが読めない時は **多めに言わない**。全部を新規と数えると青になり続ける。
            base.update({"actionable": 0, "note": "スプシ未読 (%s) = 件数は押すまで不明"
                                                  % type(e).__name__})
            return base
        base.update({"actionable": sum(1 for i in uniq if i and i not in processed and i not in excl),
                     "processed": sum(1 for i in uniq if i and i in processed),
                     "excluded": sum(1 for i in uniq if i and i in excl)})
        return base
    except Exception as e:                                     # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, e)}


def _build_review_skip_rows(restock_cands, shown_idxs, confirmed_idxs, diff_idxs, today):
    """視覚確証でレビュー済だが未確定(違う/見送り)の行を作る(純関数)。

    shown - confirmed = 違う + 見送り。次回から視覚確証に出さないため記録する。
    理由: diff_idxs にあれば「違う」、なければ「見送り」。
    """
    out = []
    for n in sorted(shown_idxs - confirmed_idxs):
        rc = restock_cands[n] if isinstance(n, int) and 0 <= n < len(restock_cands) else {}
        iid = (rc.get("itemID") or "").strip()
        if not iid:
            continue
        reason = "違う" if n in diff_idxs else "見送り"
        out.append([iid, rc.get("card_no", ""), rc.get("title", ""), reason, today, rc.get("ebay_url", "")])
    return out


def _merge_skip_rows(existing_rows, new_rows, default_header):
    """既存スキップ行 + 新規 をマージ(純関数・itemID重複は新規優先)。"""
    header = existing_rows[0] if existing_rows else default_header
    new_iids = {(r[0] or "").strip() for r in new_rows if r and (r[0] or "").strip()}
    kept = [r for r in (existing_rows[1:] if existing_rows else [])
            if r and (r[0] or "").strip() and (r[0] or "").strip() not in new_iids]
    return [header] + kept + new_rows


def _run_restock_confirm(restock_cands, mp, cert_map):
    """再仕入れ可を視覚確証(現物 vs 仕入候補)→ 確定分を「RESTOCK確定」タブへ。失敗は警告のみ。"""
    import datetime
    import psa_resource_confirm as prc
    from sheet_io import read_tab
    # 現在の仕入れ値(N=col13)+現在価格(M=col12)を itemID で引く → 確証カードに💴表示(補URL slice3 と横展開)。
    # 「今の仕入れ価格 vs 見つけた候補」を見比べて、安い供給か一目で分かる(2026-07-26)。失敗は空マップ。
    _cost_by_iid = {}
    try:
        import sheet_io as _sio
        _pv = _sio._product_ws().get_all_values()
        for _r in _pv[1:]:
            _iid = (_r[1].strip() if len(_r) > 1 else "")
            if _iid:
                _cost_by_iid[_iid] = ((_r[13].strip() if len(_r) > 13 else ""),
                                      (_r[12].strip() if len(_r) > 12 else ""))  # (N仕入れ値, M現在価格)
    except Exception as _e:
        print(f"  ⚠ 仕入れ値マップ取得skip ({type(_e).__name__})")
    # 既にRESTOCK確定済(実行済/入稿待ち)の itemID は視覚確証に再表示しない(同じ確証作業の繰り返し防止。
    # 2026-06-22 ユーザー要望)。canonical は RESTOCK確定タブ。
    _existing = read_tab("RESTOCK確定")
    _done_iids = _restock_confirmed_iids(_existing)
    # レビュー済だが未確定(違う/見送り)も再表示しない(2026-06-22 ユーザー指摘: 同じ3件が毎回出る)。
    # canonical は RESTOCK確証スキップ タブ。再検討したい時はその行を消せば再浮上する。
    # ★2026-07-29: 期限なしで永久に伏せていた → **翌日には再挑戦**する (補URL側と同一規約)。
    #   台帳の行は消さない (履歴)。判定だけで再表示を制御する。
    _skip_existing = read_tab(REVIEW_SKIP_TAB)
    _today_for_skip = datetime.date.today().isoformat()
    _skip_iids = _review_skip_iids(_skip_existing, today=_today_for_skip)
    _revived_n = len(_review_skip_iids(_skip_existing)) - len(_skip_iids)
    if _revived_n:
        print(f"  ♻ cooldown 満了 {_revived_n}件 → 再確証の対象に復帰 (台帳の行は残す)")
    # 2026-06-20 価格NO-GO廃止(本丸): 仕入高も**除外せず照合に出す**(コストプラス=損なし・無在庫=
    # フリーオプション・既存メンテで追跡)。⚠仕入高 ラベルは残すので判別可。あなたが買うものを選ぶ。
    items = []
    high_n = 0
    _skipped_done = 0
    _skipped_review = 0
    # ★過去に人が「違う」と判定した候補は二度と出さない (補URL側と同じ台帳を共有・2026-07-30)。
    try:
        import psa_hoju_fill as _hf0
        _ng_by_iid = _hf0._ng_urls_by_iid(read_tab(_hf0.NG_CAND_TAB))
    except Exception:
        _ng_by_iid, _hf0 = {}, None
    _n_ng = 0
    for n, rc in enumerate(restock_cands):
        iid = rc.get("itemID")
        if iid and iid in _done_iids:
            _skipped_done += 1
            continue   # 既にRESTOCK確定済 → 再確証しない
        if iid and iid in _skip_iids:
            _skipped_review += 1
            continue   # 既にレビュー済(違う/見送り) → 再確証しない
        if _ng_by_iid and _hf0 and iid:
            _keep, _drop = _hf0.filter_candidates_rejected(rc.get("candidates") or [],
                                                           _ng_by_iid.get(iid))
            if _drop:
                _n_ng += len(_drop)
                rc["candidates"] = _keep
            if not _keep:
                continue          # 全部が既に「違う」判定済 → 見せる意味がない
        v8 = _v8_label(rc.get("cost"), rc.get("cur"), mp)
        if _is_high_cost(v8):
            high_n += 1
        ref = prc.ebay_listing_image(iid) or prc.psa_image_for_cert(cert_map.get(iid) if iid else None)
        # 多変種(同番号で別アート/色/パラレル/Gold)は絵柄取り違えが起きやすい → 確証UIに⚠️バッジ
        # (補URL slice3 と横展開・2026-07-26)。単一変種は番号一致=正で流し見OK。
        try:
            # カテゴリで絞る(別作品の同番号を変種として数えない・2026-07-29)
            _mv = bool(mp._is_multi_variant(rc.get("card_no") or "", mp.split_key(rc.get("key"))[0]))
        except Exception:
            _mv = False
        _cn, _pn = _cost_by_iid.get(iid, ("", ""))   # 現在の仕入れ値N / 現在価格M
        items.append({"idx": n, "title": rc["title"], "card_no": rc["card_no"],
                      "ebay_url": rc["ebay_url"], "ref_image": ref,
                      "candidates": rc["candidates"], "v8": v8, "multi_variant": _mv,
                      "cost_now": _cn, "price_now": _pn})
    if _skipped_done:
        print(f"  ⏭ 既にRESTOCK確定済 {_skipped_done}件は視覚確証スキップ(再作業防止)")
    if _skipped_review:
        print(f"  ⏭ レビュー済(違う/見送り) {_skipped_review}件は視覚確証スキップ(再表示しない・{REVIEW_SKIP_TAB}タブ)")
    if not items:
        print("  照合対象なし(新規の再仕入れ可ゼロ=全て確定/レビュー済)→ RESTOCK確定 変更なし")
        return
    if _n_ng:
        print(f"  🚫 過去に「違う」と判定済の候補 {_n_ng}件を除外(補URL側と共有の台帳)")
    if high_n:
        print(f"  🔵 うち仕入高 {high_n}件 含む(除外せず表示・既存メンテ追跡。⚠ラベルで判別)")
    print(f"▶ RESTOCK視覚確証: 再仕入れ可 {len(items)}件をブラウザ表示。候補ごとに①現物と同じか確認...")
    res = prc.restock_confirm(items)
    if res is None:
        print("⚠ RESTOCK確証 タイムアウト/未確定 — RESTOCK確定リストは未更新")
        return
    # res = {confirmed:[{idx,urls}], reasons:{diff,skip}, total}。confirmed=買う候補のみ記録。
    confirmed = res["confirmed"]
    sel = {c["idx"]: c["urls"] for c in confirmed}
    today = datetime.date.today().isoformat()
    _default_header = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定",
                       "確認済仕入URL", "ebay_url", "確証日"]
    new_rows = []
    for n, rc in enumerate(restock_cands):
        if n in sel:
            urls = sel[n] or [rc.get("url", "")]
            new_rows.append([rc.get("itemID", ""), rc.get("card_no", ""), rc.get("title", ""),
                             rc.get("channel", ""), rc.get("cost", ""), rc.get("cur", ""),
                             _v8_label(rc.get("cost"), rc.get("cur"), mp),
                             " | ".join(u for u in urls if u), rc.get("ebay_url", ""), today])
    # ★出品が終了していたらリストックでは戻せない → 新規出品に回す (2026-09-02)
    if new_rows:
        try:
            from ebay_getitem_images import fetch_listing_status as _fls
            _alive = {}

            def _alive_of(iid):
                if iid not in _alive:
                    st = _fls(iid)
                    _alive[iid] = None if st is None else (st == "Active")
                return _alive[iid]

            new_rows, _relist = split_confirmed_by_listing_alive(new_rows, _alive_of)
            if _relist:
                n = _append_new_listing_rows(_relist)
                print(f"  ♻→🆕 出品が終了していた {n}件は **新規出品**に回しました "
                      f"(商品管理シートに追加。リストックでは戻せないため)")
                for r in _relist:
                    print(f"       {r[0]} {(r[2] or '')[:52]}")
        except Exception as e:                                 # noqa: BLE001
            print(f"  ⚠ 出品状態の確認skip → 全件リストック扱い ({type(e).__name__}: {e})")

    # 既存(実行済含む)を維持しつつ新規確定を追加(上書きで既存を消さない)
    out = _merge_restock_out(_existing, new_rows, _default_header)
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("RESTOCK確定", out)
        print(f"🟢 RESTOCK確定: {len(out)-1}件 → タブ「RESTOCK確定」(手動で revise 実行 / POC-Bで自動化) {MAINT_URL}")
    except Exception as e:
        print(f"⚠ RESTOCK確定タブ更新skip ({type(e).__name__}: {e})")
    # レビュー済だが未確定(違う/見送り)を記録 → 次回から視覚確証に出さない(再表示の繰り返し防止)
    try:
        from sheet_io import write_rows_to_tab as _wt2
        shown_idxs = {it["idx"] for it in items}
        diff_idxs = {d.get("idx") for d in (res.get("diffs") or []) if d.get("idx") is not None}
        new_skip = _build_review_skip_rows(restock_cands, shown_idxs, set(sel.keys()), diff_idxs, today)
        if new_skip:
            skip_out = _merge_skip_rows(_skip_existing, new_skip, REVIEW_SKIP_HEADER)
            _wt2(REVIEW_SKIP_TAB, skip_out)
            print(f"  📝 {REVIEW_SKIP_TAB}: +{len(new_skip)}件 記録(次回は視覚確証に出さない・再検討は同タブ行削除で復活)")
    except Exception as e:
        print(f"  ⚠ {REVIEW_SKIP_TAB} 記録skip ({type(e).__name__}: {e})")
    _alert_restock_diffs(res.get("diffs") or [], res.get("skip") or 0, restock_cands, today)


def split_confirmed_by_listing_alive(new_rows, alive_of):
    """確定行を「リストック(出品が生きている)」と「新規出品(終了済)」に分ける。純関数。

    ★2026-09-02: 終了した出品まで RESTOCK確定 に入れていた。リストックは **生きている出品の
    数量を戻す**機能なので、終了済は何度回しても戻せず「cert#未解決→生成不可」で毎回止まる。
    実測で5件が 7/24 から 40日 その状態だった。**在庫が戻った時点で行き先を分ける**。

    alive_of(itemID) -> True(生きている) / False(終了済) / None(分からない)
    分からない時は **リストック側に残す** (勝手に新規出品へ回さない = fail-closed)。
    """
    restock, relist = [], []
    for r in new_rows:
        iid = (r[0] or "").strip() if r else ""
        (relist if (iid and alive_of(iid) is False) else restock).append(r)
    return restock, relist


def new_listing_rows_from_confirmed(rows):
    """確定行 → 商品管理シートに足す「出品待ち」行。純関数。

    B列(itemID)を空にするのが肝。空 = まだ出していない = 出品くんが拾う対象。
    鑑定番号(I列)は入れない。**現物ごとに変わる**もので、買う物が決まってから決まる
    (説明文側で吸収する作りなので、空のまま出せる)。
    """
    out = []
    for r in rows:
        urls = [u.strip() for u in (r[7] or "").split(" | ") if u.strip()]
        row = [""] * 40
        row[0] = urls[0] if urls else ""          # A 仕入元URL
        row[2] = r[2] or ""                       # C タイトル
        row[17] = "TCG"                           # R カテゴリ
        for n, u in enumerate(urls[1:6]):         # AC-AG 補URL
            row[28 + n] = u
        out.append(row)
    return out


def _append_new_listing_rows(rows):
    """終了済だった分を商品管理シートに「出品待ち」として足す (I/O)。失敗は警告のみ。"""
    if not rows:
        return 0
    try:
        import sheet_io as _sio
        ws = _sio._product_ws()
        ws.append_rows(new_listing_rows_from_confirmed(rows), value_input_option="RAW")
        return len(rows)
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 新規出品行の追加skip ({type(e).__name__}: {e})")
        return 0


def split_diffs_by_number_match(diffs, restock_cands):
    """目視で外した候補を「検索の事故」と「絵柄違い」に分ける。純関数。

    ★2026-09-03: 「違う」を全部 **検索の精度事故** として 🚨 を出していたが、
    候補は基本 **カード番号で引いている**ので、番号が合っている候補を人が外すのは
    **同じ番号の別の絵柄**を弾いただけ = 目視ゲートが正しく働いた形。直すものが無い。
    実測 2026-09-03: 10件全部がこれで、毎回「今すぐ直せ」と出ていた (直す先が無い)。

    本当に直すべきなのは **番号で引けなかった候補** (`number_ok=False` = 名前一致だけで
    積んだ枠)。ここで別カードを掴んだなら検索側の問題。

    戻り: (検索の事故[diff...], 絵柄違い[diff...])
    """
    bug, art = [], []
    for d in diffs:
        i = d.get("idx")
        rc = restock_cands[i] if isinstance(i, int) and 0 <= i < len(restock_cands) else {}
        url = (d.get("url") or "").strip()
        cand = next((c for c in (rc.get("candidates") or [])
                     if (c.get("url") or "").strip() == url), {})
        (bug if cand.get("number_ok") is False else art).append(d)
    return bug, art


def _alert_restock_diffs(diffs, skip, restock_cands, today):
    """「違う(別カード)」=検索の精度事故。**率を待たず1件でも即対応**(悠長な閾値・トレンドは捨てる)。
    どのカードのどの候補が別物かを個別に surface + 即対応リスト化(各サイクルで空が正=放置は精度事故)。
    生成側(メルカリkeyword/スニダンvariant確証)を即修正する根拠。見送りは business判断で action 不要。
    """
    if not diffs:
        print(f"  外し: 見送り{skip} / 違う0(検索の誤検出なし=精度OK)")
        return
    # ★2026-07-30: 「違う」を **負例として貯める**。補URL側 (slice3) と **同じタブを共有**するので、
    #   どちらで押した判断も両方に効く。これが無いと次回また同じ候補を見せることになり、
    #   人の1クリックが捨てられる (実測: 1走行で9件が捨てられていた)。
    try:
        import psa_hoju_fill as _hf
        from sheet_io import read_tab as _rt, write_rows_to_tab as _wt
        _new = []
        for d in diffs:
            i = d.get("idx")
            rc = restock_cands[i] if isinstance(i, int) and 0 <= i < len(restock_cands) else {}
            iid, url = (rc.get("itemID") or "").strip(), (d.get("url") or "").strip()
            if iid and url:
                # ★2026-08-13: 候補側のタイトル/価格も残す (NG_CAND_HEADER 7列)。
                #   url しか無いと、後で「捨てた候補を新規出品の種に戻す」時に何だったか引けない。
                _ci = _hf.cand_info_by_url(rc.get("candidates"))
                _ct, _cp = _ci.get(_hf._norm_url(url), ("", ""))
                _new.append([iid, "", url, (rc.get("title") or "")[:60], today, _ct, _cp])
        if _new:
            _wt(_hf.NG_CAND_TAB,
                _hf._merge_ng_rows(_rt(_hf.NG_CAND_TAB), _new, _hf.NG_CAND_HEADER))
            print(f"  🚫 {_hf.NG_CAND_TAB}: +{len(_new)}件 記録"
                  f"(この出品にこのURLは次回から出さない・補URL側と共有)")
    except Exception as e:
        print(f"  ⚠ 候補NG台帳への記録skip ({type(e).__name__}: {e})")
    # ★番号で引けた候補を人が外した = 同番号の別絵柄を弾いただけ。直す先が無いので騒がない
    _bug, _art = split_diffs_by_number_match(diffs, restock_cands)
    if _art:
        print(f"  ✋ 絵柄違いで外した {len(_art)}件 (番号は一致。目視ゲートが効いた形= 正常。"
              f"候補NG台帳に記録済なので次回は出ません)")
    if not _bug:
        print(f"  外し: 見送り{skip} / 検索の事故0(番号で引けた候補だけ=精度OK)")
        return
    print(f"🚨 違う即対応 {len(_bug)}件(見送り{skip})— **番号で引けなかった枠**が別カードを拾った"
          f"=検索の事故。生成(検索)を直す:")
    rows = [["日付", "card_no", "title", "チャネル", "誤候補URL", "状態"]]
    for d in _bug:
        i = d.get("idx")
        rc = restock_cands[i] if isinstance(i, int) and 0 <= i < len(restock_cands) else {}
        ch = next((c.get("channel") for c in (rc.get("candidates") or []) if c.get("url") == d.get("url")), "")
        cn, title = rc.get("card_no", ""), rc.get("title", "")
        print(f"   ⚠ {cn} [{ch}] が別カード候補を返した: {d.get('url')}  ({title})")
        rows.append([today, cn, title, ch, d.get("url", ""), "未対応"])
    try:
        from sheet_io import write_rows_to_tab
        write_rows_to_tab("RESTOCK違う即対応", rows)
        print("   → タブ「RESTOCK違う即対応」。**生成側の検索(keyword/variant確証)を即修正し空にすること**"
              "(残存=精度事故の放置)。")
    except Exception as e:
        print(f"   ⚠ 即対応リスト記録skip ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
