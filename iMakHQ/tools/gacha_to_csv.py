#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gacha_to_csv.py — ガチャポンのコンプ品 (楽天) → eBay 入稿CSV (2026-08-20)。

出品の形は **既存のカプセルトイ出品をそのまま踏襲**する。実物 (itemID 357200557035
VIRUSWEETS フィギュアコレクション) を eBay から読んで写した:
    カテゴリ 69528 / ストアカテゴリ 41827562010 / SKU = 仕入元ID
    Set=Complete Set / Number of Pieces=N / Material=PVC / Age Level=15+ /
    Type=Mini Figure / Brand / Series / Character / Franchise / Theme /
    Country of Origin=Japan / MPN=Does not apply
    タイトル: "<シリーズ> Full Set of N Gashapon NEW"

入力は中間スプシ (Harvest が入れる) か HIGH の商品管理シート。列は PSA10 と同じ:
    A=URL / C=日本語タイトル / E=状態 / F=商品価格 / G=写真URL / M=現在価格(円) / R=カテゴリ

★出さない物 (fail-closed・米国 CPSC)
    - サンリオ: user 判断で「今後扱わない」(2026-06-29、ぬいぐるみ22件を取下げた時)
    - ぬいぐるみ / マスコット等: stuffed animals は **対象年齢の印字と無関係に**
      児童製品確定。4要素判定で逃げられず、第三者試験 + CPC が要る
    実測 2026-08-20: 中間スプシ93行のうち、この2つで75行が落ち、残り18行。

使い方:
    python gacha_to_csv.py --list                     # 出せる行を一覧 (CSVは作らない)
    python gacha_to_csv.py --limit 5                  # 5件だけ CSV 生成
    python gacha_to_csv.py --sheet <id> --tab <name>  # 読む先を変える (既定=中間スプシ)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (SCRIPT_DIR, r"C:\dev\iMak\iMakeBayAPI"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 中間スプシ (Harvest が rakuten_gacha タブに入れる)
STAGING_SHEET_ID = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"
STAGING_TAB = "rakuten_gacha"

OUTPUT_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "csv_output")

# eBay 固定値 — 既存のカプセルトイ出品 (itemID 357200557035) から実測
EBAY_CATEGORY = 69528          # Collectibles > Animation Art & Merchandise > Other Animation Merchandise
STORE_CATEGORY = 41827562010
CONDITION_ID = 1000            # New
LOCATION = "Osaka"
PROFIT_CATEGORY = "ガシャポン"   # pricing_engine のカテゴリ名 (R列の「カプセルトイ」の内部名)
SHEET_CATEGORY = "カプセルトイ"   # シート R列の値
MODEL = "claude-opus-5"
SCHEDULE_WEEKS = 2

# ★出さない語 (fail-closed)。増やすのは可、減らすのは不可。
NG_FRANCHISE = ("サンリオ",)
NG_PLUSH = ("ぬいぐるみ", "マスコット", "フロッキー", "パペット",
            "もこもこ", "ふわふわ", "プラッシュ", "plush", "Plush")

# 日本語タイトルから落とすノイズ
_NOISE = ("ガチャポン", "ガチャガチャ", "コンプリート", "コンプ", "ガチャ",
          "カプセルトイ", "コンプリートセット")


# ── 純関数 (test 可) ────────────────────────────────────────────────


def strip_shop_suffix(title: str) -> str:
    """楽天タイトル末尾の店名 (`：遊you　楽天市場店`) を落とす。"""
    return (title or "").split("：")[0].strip()


def piece_count(title: str):
    """「全N種」の N。取れなければ None (= 出さない)。"""
    m = re.search(r"全\s*(\d+)\s*種", title or "")
    return int(m.group(1)) if m else None


def has_display_board(title: str) -> bool:
    """台紙付きかどうか (同じ商品の台紙あり/なしを見分ける)。"""
    return "ディスプレイ台紙" in (title or "")


def blocked_reason(title: str):
    """出せない理由。出せるなら None。

    ★2026-08-20: 米国 CPSC。対象年齢の印字では逃げられない区分なので、
      目視の年齢確認 (別途) とは独立にここで落とす。
    """
    t = title or ""
    if any(k in t for k in NG_FRANCHISE):
        return "サンリオ (2026-06-29 user 判断で今後扱わない)"
    if any(k in t for k in NG_PLUSH):
        return "ぬいぐるみ系 (CPSC: 対象年齢と無関係に児童製品)"
    return None


def series_jp(title: str) -> str:
    """日本語タイトルからシリーズ名だけ取り出す (全N種より前 − ノイズ)。"""
    head = re.split(r"全\s*\d+\s*種", strip_shop_suffix(title))[0]
    for n in _NOISE:
        head = head.replace(n, " ")
    return re.sub(r"\s+", " ", head).strip()


def maker_jp(title: str) -> str:
    """「全N種…セット」の直後に来るメーカー名。取れなければ空 (推測しない)。"""
    m = re.search(r"全\s*\d+\s*種(?:\+ディスプレイ台紙)?セット\s+(\S+)",
                  strip_shop_suffix(title))
    if not m:
        return ""
    w = m.group(1)
    return "" if w in _NOISE else w


def parse_row(row: list) -> dict | None:
    """シート1行 → 中間表現。出せない行は None。

    row は PSA10 と同じ列並び (A=0 / C=2 / E=4 / F=5 / G=6 / M=12 / R=17)。
    """
    def g(i):
        return (row[i].strip() if len(row) > i else "")

    url, title, cat = g(0), g(2), g(17)
    if not url or not title:
        return None
    if cat != SHEET_CATEGORY:
        return None
    if g(1):
        return None                      # itemID 済 = 出品済
    if blocked_reason(title):
        return None
    n = piece_count(title)
    if not n:
        return None                      # 全N種が読めない = 出さない (fail-closed)
    cost = re.sub(r"[^\d]", "", g(12) or g(5))
    if not cost:
        return None
    pics = [p for p in g(6).split("|") if p.startswith("http") and not is_banner(p)]
    if not pics:
        return None                      # 商品写真が1枚も無い = 出さない
    return {"url": url, "title_jp": strip_shop_suffix(title), "pieces": n,
            "with_board": has_display_board(title), "series_jp": series_jp(title),
            "maker_jp": maker_jp(title), "cost_jpy": int(cost), "pics": pics}


def is_banner(url: str) -> bool:
    """店のバナー画像か (商品写真ではない)。

    ★2026-08-20 実測: 中間スプシ93行の **全行** で1枚目が店のバナーだった
      (遊you=bn_math…jpg 82件 / アミュームショップ=rkanban.jpg 11件)。
      1枚目は eBay のギャラリー画像になるので、そのまま出すと商品が写らない。
      収集側にも直してもらうが、こちらでも落とす (fail-safe)。
    """
    name = re.sub(r".*/", "", (url or "").lower())
    return name.startswith("bn_") or "kanban" in name or "banner" in name


def supply_sku(url: str) -> str:
    """仕入元URL → SKU (既存出品と同じ規約: 仕入元の商品ID)。"""
    m = re.search(r"/item/(m\d+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"item\.rakuten\.co\.jp/([^/]+)/([^/?#]+)", url or "")
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def build_title(series_en: str, pieces: int, maker_en: str = "") -> str:
    """英語タイトル (80字以内)。既存出品と同じ形。

    "VIRUSWEETS Figure Collection Sweets Shop Full Set of 6 Gashapon NEW"
    """
    tail = f"Full Set of {pieces} Gashapon NEW"
    head = " ".join(x for x in (maker_en, series_en) if x).strip()
    t = f"{head} {tail}".strip()
    if len(t) <= 80:
        return t
    room = 80 - len(tail) - 1
    return (head[:room].rstrip() + " " + tail).strip()


def dedup_board_variants(items: list) -> list:
    """同じ商品の「台紙あり/なし」を1本に寄せる (台紙なしを残す)。

    ★2026-08-20 実測: 93行のうち20組が台紙あり/なしの重複。両方出すと
      同じ絵柄で2出品になる。
    """
    out, seen = [], {}
    for it in sorted(items, key=lambda x: (x["series_jp"], x["with_board"])):
        key = (it["series_jp"], it["pieces"])
        if key in seen:
            continue
        seen[key] = True
        out.append(it)
    return out


# ── I/O ────────────────────────────────────────────────────────────


def read_sheet(sheet_id: str, tab: str) -> list:
    import gspread
    from google.oauth2.service_account import Credentials
    import dns_cache                                            # noqa: F401
    import sheet_io as S
    gc = gspread.authorize(Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    sh = gc.open_by_key(sheet_id)
    ws = next(w for w in sh.worksheets() if w.title == tab)
    return ws.get_all_values()[1:]


def _api_key() -> str:
    """API key を読む。既存の置き場所 (一番くじ) をそのまま使う (新しい規約を作らない)。"""
    for p in (os.environ.get("ANTHROPIC_API_KEY", ""),):
        if p:
            return p
    f = r"C:\dev\iMak\iMak_ichibankuji\API key.txt"
    if os.path.isfile(f):
        return open(f, encoding="utf-8").read().strip()
    raise SystemExit("★中止: ANTHROPIC_API_KEY が無く 'API key.txt' も読めません")


def translate(items: list) -> dict:
    """日本語のシリーズ名/メーカーを英語にする (Claude)。{jp: en}。

    取れなければ空 dict を返す = 呼び側は日本語のまま出さずに skip する
    (推測でローマ字化しない)。
    """
    if not items:
        return {}
    import anthropic
    pairs = sorted({(it["series_jp"], it["maker_jp"]) for it in items})
    listing = "\n".join(f"{i+1}. series={s} / maker={m or '(なし)'}"
                        for i, (s, m) in enumerate(pairs))
    prompt = (
        "以下は日本のガチャポン (カプセルトイ) の商品名です。eBay の英語タイトルに使う"
        "英語表記に直してください。\n\n"
        "ルール:\n"
        "- 公式の英語名がある物 (キャラクター名・作品名・メーカー名) は公式表記を使う\n"
        "- 無い物はローマ字ではなく **意味の通る英語** にする\n"
        "- 「全N種」「ガチャ」等の語は入れない (別に付ける)\n"
        "- 分からない物は空文字にする。**推測で埋めない**\n\n"
        f"{listing}\n\n"
        'JSON だけを返す: [{"series_jp": "...", "series_en": "...", '
        '"maker_jp": "...", "maker_en": "..."}]'
    )
    try:
        client = anthropic.Anthropic(api_key=_api_key())
        r = client.messages.create(
            model=MODEL, max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}])
        txt = next((b.text for b in r.content if b.type == "text"), "")
        m = re.search(r"\[.*\]", txt, re.S)
        rows = json.loads(m.group(0)) if m else []
        return {(x.get("series_jp", ""), x.get("maker_jp", "")):
                (x.get("series_en", "").strip(), x.get("maker_en", "").strip())
                for x in rows}
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠️ 英訳できず ({type(e).__name__}: {e}) → CSVは作りません")
        return {}


def load_description() -> str:
    """説明文テンプレ。読めなければ **止める** (黙って代替文を使わない)。"""
    for name in ("GACHA.txt", "ICHIBANKUJI.txt"):
        for d in (SCRIPT_DIR, os.path.dirname(SCRIPT_DIR),
                  r"C:\dev\iMak\iMak_ichibankuji"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return open(p, encoding="utf-8").read()
    raise SystemExit("★中止: 説明文テンプレ (GACHA.txt / ICHIBANKUJI.txt) が見つかりません")


def build_description(item: dict, series_en: str, maker_en: str, base: str) -> str:
    specs = [
        f"<li><b>Series:</b> {series_en}</li>",
        f"<li><b>Set:</b> Complete Set ({item['pieces']} pcs)</li>",
        "<li><b>Material:</b> PVC</li>",
        "<li><b>Country of Origin:</b> Japan</li>",
    ]
    if maker_en:
        specs.insert(1, f"<li><b>Manufacturer:</b> {maker_en}</li>")
    if item["with_board"]:
        specs.append("<li><b>Includes:</b> Display board</li>")
    html = ('<p><span style="text-decoration: underline;"><strong>Specifications'
            "</strong></span></p>\n<ul>\n" + "\n".join(specs) + "\n</ul>")
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    return base.replace(marker, html + "\n" + marker, 1) if marker in base else base + html


def price_usd(cost_jpy: int) -> float:
    from pricing_engine import compute_listing_price
    p = round(compute_listing_price(cost_jpy, 0, PROFIT_CATEGORY)["target_usd"], 2)
    return int(p) + 0.98 if p > 10 else p


def schedule_time() -> str:
    t = datetime.datetime.utcnow() + datetime.timedelta(weeks=SCHEDULE_WEEKS)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def build_row(item: dict, series_en: str, maker_en: str, base_desc: str) -> dict:
    from listing_common import get_shipping_policy_name
    price = price_usd(item["cost_jpy"])
    return {
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)": "Add",
        "*Category": EBAY_CATEGORY,
        "*Title": build_title(series_en, item["pieces"], maker_en),
        "*Description": build_description(item, series_en, maker_en, base_desc),
        "PicURL": "|".join(item["pics"][:12]),
        "*StartPrice": price,
        "ConditionID": CONDITION_ID,
        "CustomLabel": supply_sku(item["url"]),
        "ScheduleTime": schedule_time(),
        "*Format": "FixedPrice",
        "*Duration": "GTC",
        "*Quantity": 1,
        "*Location": LOCATION,
        "BestOfferEnabled": 1,
        "ShippingProfileName": get_shipping_policy_name(price, PROFIT_CATEGORY),
        "ReturnProfileName": "customer1",
        "PaymentProfileName": "SALE",
        "Product:UPC": "Does not apply",
        "C:Set": "Complete Set",
        "C:Number of Pieces": item["pieces"],
        "C:Material": "PVC",
        # 対象年齢: パッケージ表記が15才以上の物だけ出す運用 (目視で確認)。
        # CPSC eFiling で児童製品 (12歳以下) 扱いを外す宣言。一番くじと同じ。
        "C:Age Level": "15+",
        "C:Type": "Mini Figure",
        "C:Brand": maker_en or "",
        "C:Series": series_en,
        "C:Character": series_en,
        "C:Franchise": series_en,
        "C:Theme": "Anime & Manga",
        "C:Original/Licensed Reproduction": "Original",
        "C:Country of Origin": "Japan",
        "C:MPN": "Does not apply",
        "C:Language": "Japanese",
        "StoreCategoryID": STORE_CATEGORY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default=STAGING_SHEET_ID)
    ap.add_argument("--tab", default=STAGING_TAB)
    ap.add_argument("--limit", type=int, default=0, help="この件数だけ作る (0=全部)")
    ap.add_argument("--list", action="store_true", help="出せる行を見るだけ (CSV作らない)")
    ap.add_argument("--no-review", action="store_true",
                    help="目視を飛ばす (★検証用。出品に使ってはいけない)")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                           # noqa: BLE001
        pass

    rows = read_sheet(a.sheet, a.tab)
    print(f"シート {a.tab}: {len(rows)}行")
    items, blocked = [], {}
    for r in rows:
        t = (r[2].strip() if len(r) > 2 else "")
        why = blocked_reason(t)
        if why:
            blocked[why] = blocked.get(why, 0) + 1
            continue
        it = parse_row(r)
        if it:
            items.append(it)
    for why, n in blocked.items():
        print(f"  ⏭️ 出さない {n}件: {why}")
    before = len(items)
    items = dedup_board_variants(items)
    if before != len(items):
        print(f"  ⏭️ 台紙あり/なしの重複を寄せた: {before} → {len(items)}件")
    print(f"  ✅ 出せる: {len(items)}件")
    if a.limit:
        items = items[:a.limit]

    if a.list:
        for it in items:
            print(f"   全{it['pieces']}種 ¥{it['cost_jpy']:,} "
                  f"{'[台紙]' if it['with_board'] else '     '} "
                  f"{it['maker_jp'] or '(メーカー不明)'} / {it['series_jp'][:44]}")
        return 0
    if not items:
        print("出せる行が0件 → CSVは作りません")
        return 0

    # ★対象年齢は機械的に取れない (2026-08-20 実測: 楽天HTMLにもメーカー公式HTMLにも
    #   記載なし。印字は台紙の写真の中)。人が見て 15才以上と確認した物だけ出す。
    if not a.no_review:
        import gacha_review as R
        ledger = R.run_review(items, open_browser=not a.no_browser)
        for why, n in R.skipped_reasons(items, ledger).items():
            print(f"  ⏭️ 出しません {n}件: {why}")
        items = R.confirmed(items, ledger)
        print(f"  ✅ 目視で15才以上と確認: {len(items)}件")
        if not items:
            print("出せる行が0件 → CSVは作りません")
            return 0

    en = translate(items)
    if not en:
        return 1
    base_desc = load_description()
    out, skipped = [], []
    for it in items:
        s_en, m_en = en.get((it["series_jp"], it["maker_jp"]), ("", ""))
        if not s_en:
            skipped.append(it["series_jp"])
            continue                    # 英語名が取れない = 出さない (推測しない)
        out.append(build_row(it, s_en, m_en, base_desc))
    for s in skipped:
        print(f"  ⏭️ 英語名が取れず skip: {s[:50]}")
    if not out:
        print("英語名が取れた行が0件 → CSVは作りません")
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR,
                        "gacha_upload_%s.csv" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(list(out[0].keys()))
        for r in out:
            w.writerow(list(r.values()))
    print(f"\n完了: {len(out)}行 → {path}")
    for r in out:
        print(f"  ${r['*StartPrice']:>7} {r['*Title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
