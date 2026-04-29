"""montbell_scraper - モンベル仕入元の在庫・価格スクレイパー (独立モジュール).

設計原則 (UNIQLO scraper と同じ哲学):
  - 既存モジュール (psa_to_csv 等) を一切 import しない
  - requests + BeautifulSoup のみで完結 (Selenium 不要)
  - 失敗時は例外送出 or 空 skus 返却

データ取得方式:
  モンベルは静的 HTML (SSR) で在庫情報が <table summary="在庫状況・注文数"> に格納.
  - 9 個のテーブルが並ぶ:
      Table 0: id="size_"     (placeholder, 「サイズを選択すると表示されます」)
      Table 1: id="size_XS"
      Table 2: id="size_S"
      ... etc (size code は select option と完全一致)
  - 各テーブルの行 = カラー (img alt にカラーコード "BK", "BL" 等)
  - 各セルの在庫テキストで判定:
      "在庫あり 翌日〜翌々日出荷予定"     → ◎ IN_STOCK
      "直営店在庫あり 在庫のある店舗から〜" → ◎ STORE_STOCK (取り寄せ可、出荷可)
      "入荷待ち（受付可）..."            → △ ON_BACKORDER (受付可だが納期遅) → 無在庫運用上は ✕
      "完売 今期の入荷はありません"      → ✕ SOLD_OUT
      "入荷時期未定（受付不可）"          → ✕ NO_RESTOCK
      "サイズを選択すると表示されます"    → placeholder (skip)

無在庫運用判定:
  - eBay handling time (1-3日) 内に出荷可能なものだけ「在庫あり ◎」とする
  - IN_STOCK / STORE_STOCK のみ ◎、それ以外は ✕ (ON_BACKORDER 含む)

URL 形式:
  https://webshop.montbell.jp/goods/disp.php?product_id=1103322       (基本商品)
  https://webshop.montbell.jp/goods/disp_fo.php?product_id=1128635&top_sk=1128635  (フェスティバル系)

使用例:
    from montbell_scraper import fetch_product_inventory
    info = fetch_product_inventory("https://webshop.montbell.jp/goods/disp.php?product_id=1103322",
                                    target_color_code="BK")
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}
TIMEOUT_SEC = 15


# ============================================================================
# 在庫状況テキスト → 状態コード分類
# ============================================================================
def _classify_stock_text(txt: str) -> tuple:
    """在庫文字列 → (status_code, in_stock_bool, label).

    無在庫運用の安全側判定:
      - eBay handling time (1-3日) 内に出荷可能なもののみ ◎
      - 「直営店在庫あり (取り寄せ)」は数日で出荷可能 → ◎
      - 「入荷待ち (受付可)」は数週間〜数ヶ月待ち → ✕ (DRSAR 直結)
    """
    t = (txt or "").strip()
    if not t:
        return ("EMPTY", False, "")

    # placeholder
    if "サイズを選択" in t or "選択すると表示" in t:
        return ("PLACEHOLDER", False, t[:30])

    # 完売 / 入荷予定なし
    if "完売" in t or "入荷はありません" in t or "今期の入荷" in t:
        return ("SOLD_OUT", False, "完売")

    # 入荷時期未定
    if "未定" in t and "受付不可" in t:
        return ("NO_RESTOCK", False, "入荷時期未定")

    # 入荷待ち (受付可だが納期遅い → 無在庫運用上は ✕)
    if "入荷待ち" in t and "受付可" in t:
        return ("ON_BACKORDER", False, "入荷待ち")

    # 直営店在庫あり (取り寄せ、数日で出荷可能)
    if "直営店在庫" in t:
        return ("STORE_STOCK", True, "直営店在庫あり")

    # 在庫あり (翌日出荷)
    if "在庫あり" in t:
        return ("IN_STOCK", True, "在庫あり")

    # 未知パターン → 警告 + 安全側 (✕)
    return ("UNKNOWN", False, t[:50])


# ============================================================================
# URL パーサ
# ============================================================================
def parse_montbell_url(url: str) -> dict:
    """モンベル URL から product_id を抽出.

    対応形式:
      disp.php?product_id=1103322
      disp_fo.php?product_id=1128635&top_sk=1128635
    """
    if not url:
        raise ValueError("URL が空です")
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    product_id = (qs.get("product_id") or [None])[0]
    if not product_id:
        raise ValueError(f"product_id を URL から抽出できません: {url}")
    return {
        "product_id": product_id,
        "page_type": "disp_fo" if "disp_fo" in parsed.path else "disp",
    }


# ============================================================================
# HTML fetch
# ============================================================================
def _fetch_html(product_id: str, page_type: str = "disp") -> BeautifulSoup:
    """商品ページ HTML を取得して BeautifulSoup 返却."""
    base = "disp_fo.php" if page_type == "disp_fo" else "disp.php"
    url = f"https://webshop.montbell.jp/goods/{base}?product_id={product_id}"
    if page_type == "disp_fo":
        url += f"&top_sk={product_id}"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


# ============================================================================
# 価格抽出
# ============================================================================
def _extract_price(soup: BeautifulSoup) -> Optional[int]:
    """商品ページから価格 (税込円) を抽出. 失敗時 None."""
    # `<table>` 内 <th>価格</th><td>¥9,680（税込）</td> パターン
    for th in soup.find_all("th"):
        if th.get_text(strip=True) in ("価格", "税込価格", "本体価格"):
            td = th.find_next_sibling("td")
            if td:
                txt = td.get_text(" ", strip=True)
                m = re.search(r"[¥￥]\s*([\d,]+)", txt)
                if m:
                    return int(m.group(1).replace(",", ""))
    # フォールバック: テキスト全体から最初の ¥XXXX を拾う
    body_text = soup.get_text(" ")
    m = re.search(r"[¥￥]\s*([\d,]{3,8})\s*[\(（]?税込[\)）]?", body_text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


# ============================================================================
# 商品名抽出
# ============================================================================
def _extract_name(soup: BeautifulSoup) -> str:
    """商品名抽出. <title> から「モンベル ｜ オンラインストア ｜ XXX」の XXX 部分."""
    if not soup.title:
        return ""
    title = soup.title.get_text(strip=True)
    parts = [p.strip() for p in re.split(r"[｜|]", title)]
    if len(parts) >= 3:
        return parts[-1]
    return title


# ============================================================================
# サイズ × カラー × 在庫テーブルパース (status text 経由、補助用)
# ============================================================================
def _parse_size_table(table) -> list:
    """1 サイズ分の在庫テーブルを行ごとにパース → 各カラーの状態を返す.

    補助モード: ステータステキスト ("在庫あり" / "完売" 等) から判定.
    主は `_extract_stock_quantities` (select option 数字抽出).

    Returns: [
        {"color_code": "BK", "stock_text": "完売...", "status_code": "SOLD_OUT",
         "in_stock": False, "stock_label": "完売"},
        ...
    ]
    """
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        # ヘッダ行 (カラー / 在庫状況 / 注文数) は skip
        header_text = cells[0].get_text(strip=True)
        if header_text in ("カラー", "Color"):
            continue

        # 1 列目: カラーコード (img alt から抽出 or テキスト)
        color_code = ""
        img = cells[0].find("img")
        if img and img.get("alt"):
            color_code = img.get("alt").strip()
        else:
            color_code = re.sub(r"\s+", "", cells[0].get_text(strip=True))[:6]

        # 2 列目: 在庫状況テキスト
        stock_text = cells[1].get_text(" ", strip=True) if len(cells) >= 2 else ""
        status_code, in_stock, label = _classify_stock_text(stock_text)
        if status_code == "PLACEHOLDER":
            continue

        rows.append({
            "color_code": color_code,
            "stock_text": stock_text[:60],
            "status_code": status_code,
            "in_stock": in_stock,
            "stock_label": label,
        })
    return rows


# ============================================================================
# 在庫数抽出 (主: select[name$='_num'] の option value から実数取得)
# 既存 montbell_outlet_scraper.py の手法を移植 (Selenium 不要、BS4 で同等取得可能)
# ============================================================================
_STOCK_SELECT_NAME_RE = re.compile(r"^([A-Z0-9\-]+)_([A-Z0-9\-/]+)_num$")


def _extract_stock_quantities(soup: BeautifulSoup) -> dict:
    """商品ページ全体から `select[name='SZ_CO_num']` の最大 option 値を抽出.

    Returns: {("XS","BK"): 5, ("XS","BL"): 11, ("M","DGN"): 0, ...}
      - 値 = 注文可能数量の最大 (= 概ね在庫数)
      - 0 or select 不在 = 在庫切れ
      - UNIQLO の段階値 (0/2/5/11) と違い、montbell は実数 (1〜N)

    根拠: モンベル商品ページは「数量選択」プルダウンを各 (size, color) ごとに表示し、
    在庫が少ないほど option の最大値が小さい. 「完売」サイズはこの select が無い or 空.
    """
    quantities = {}
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        m = _STOCK_SELECT_NAME_RE.match(name)
        if not m:
            continue
        size_code, color_code = m.group(1), m.group(2)
        digits = []
        for opt in sel.find_all("option"):
            v = (opt.get("value") or "").strip()
            if v.isdigit() and int(v) > 0:
                digits.append(int(v))
        quantities[(size_code.upper(), color_code.upper())] = max(digits) if digits else 0
    return quantities


def _extract_canonical_colors(soup: BeautifulSoup) -> list:
    """`<input name='all_color' value='BK,BL,DGN,...'>` から正規カラーリスト取得."""
    inp = soup.find("input", attrs={"name": "all_color"})
    if not inp:
        return []
    value = (inp.get("value") or "").strip()
    return [c.strip().upper() for c in value.split(",") if c.strip()]


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    target_color_code: Optional[str] = None,
) -> Optional[dict]:
    """モンベル商品 URL から在庫・価格を取得.

    Args:
        url: モンベル商品 URL
        target_color_code: 特定カラー (例: "RD") のみ抽出. None なら全カラー.

    Returns: UNIQLO scraper と同じ形式の dict
        {
            "name":               商品名,
            "product_id":         "1103322",
            "page_type":          "disp" / "disp_fo",
            "color":              カラーコード (target 指定時) or "ALL",
            "color_display_code": target_color_code or "",
            "fetched_at":         ISO8601,
            "skus": [
                {
                    "size":              "XS" / "S" / "M" / ... (montbell 形式そのまま),
                    "size_display_code": "XS",
                    "l2Id":              "1103322-XS-BK"  # 合成 SKU ID
                    "communication_code":同上,
                    "color_code":        "BK",
                    "in_stock":          True/False,
                    "stock_status":      "IN_STOCK" / "STORE_STOCK" / "SOLD_OUT" 等,
                    "stock_label":       "在庫あり" / "完売" 等,
                    "quantity":          1 (in_stock True) or 0,
                    "price_jpy":         9680,
                    "promo_price_jpy":   同上,
                    "sales_active":      True,
                },
                ...
            ],
        }
    """
    from datetime import datetime

    info = parse_montbell_url(url)
    soup = _fetch_html(info["product_id"], info["page_type"])
    name = _extract_name(soup)
    price = _extract_price(soup)
    target = (target_color_code or "").upper()

    # 主: select[name='SZ_CO_num'] から (size, color) → 実 quantity
    quantities = _extract_stock_quantities(soup)
    canonical_colors = _extract_canonical_colors(soup)

    # 補助: status table から status_code / label (BK 完売 / 直営店在庫 等の人間可読情報)
    status_by_size_color = {}
    for div in soup.find_all("div", id=re.compile(r"^size_")):
        size_id = div.get("id", "")
        size_code = size_id[len("size_"):]
        if not size_code:
            continue
        table = div.find("table", attrs={"summary": re.compile(r"在庫|注文")})
        if not table:
            continue
        for cr in _parse_size_table(table):
            status_by_size_color[(size_code.upper(), cr["color_code"].upper())] = cr

    # SKU 構築: quantities をベースに、status_table を補完情報として merge
    skus = []
    for (size_code, color_code), qty in sorted(quantities.items()):
        if target and color_code != target:
            continue
        # 補助 status (見つからなければ in_stock = (qty > 0) で判定)
        cr = status_by_size_color.get((size_code, color_code))
        if cr:
            status = cr["status_code"]
            label = cr["stock_label"]
        else:
            status = "IN_STOCK" if qty > 0 else "STOCK_OUT"
            label = f"在庫数 {qty}" if qty > 0 else "在庫なし"
        # 「完売 / 入荷未定」だが select に option が残ってる稀なケースは status を信頼
        in_stock_qty = qty > 0
        in_stock_status = (cr["in_stock"] if cr else in_stock_qty)
        # 安全側: 両方 True の時のみ ◎
        in_stock = in_stock_qty and in_stock_status

        skus.append({
            "size":              size_code,
            "size_display_code": size_code,
            "l2Id":              f"{info['product_id']}-{size_code}-{color_code}",
            "communication_code":f"{info['product_id']}-{size_code}-{color_code}",
            "color_code":        color_code,
            "in_stock":          in_stock,
            "stock_status":      status,
            "stock_label":       label,
            "quantity":          qty if in_stock else 0,
            "price_jpy":         price,
            "promo_price_jpy":   price,
            "sales_active":      status != "NO_RESTOCK",
        })

    # canonical_colors にあるが quantities に出てこなかった color (= 全サイズ完売 → select 無し)
    # を補完 (✕ 扱い)
    if canonical_colors and skus:
        seen_colors = {s["color_code"] for s in skus}
        # 全 size を一度カバーしてるはずだが念のため、欠損補完は status_by_size_color 経由
        for (sz, co), cr in status_by_size_color.items():
            if target and co != target:
                continue
            if (sz, co) in quantities:
                continue
            # quantity 出ない = stock 0 確定
            skus.append({
                "size":              sz,
                "size_display_code": sz,
                "l2Id":              f"{info['product_id']}-{sz}-{co}",
                "communication_code":f"{info['product_id']}-{sz}-{co}",
                "color_code":        co,
                "in_stock":          False,
                "stock_status":      cr["status_code"],
                "stock_label":       cr["stock_label"],
                "quantity":          0,
                "price_jpy":         price,
                "promo_price_jpy":   price,
                "sales_active":      cr["status_code"] != "NO_RESTOCK",
            })

    return {
        "name": name,
        "product_id": info["product_id"],
        "page_type": info["page_type"],
        "color": target if target else "ALL",
        "color_display_code": target,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": skus,
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import json
    import sys
    test_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://webshop.montbell.jp/goods/disp.php?product_id=1103322"
    )
    target = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"--- URL: {test_url}")
    if target:
        print(f"--- target color: {target}")
    info = fetch_product_inventory(test_url, target_color_code=target)
    print(f"\n商品: {info['name']}")
    print(f"価格: ¥{info['skus'][0]['price_jpy'] if info['skus'] else '?'}")
    print()
    # status 分類サマリー
    from collections import Counter
    by_status = Counter(s["stock_status"] for s in info["skus"])
    print(f"=== 状態分布 ({len(info['skus'])} SKU) ===")
    for status, n in by_status.most_common():
        print(f"  {status:>15}: {n}")
    print()
    print(f"=== 在庫サマリー ===")
    for sku in info["skus"][:30]:
        mark = "◎" if sku["in_stock"] else "✕"
        print(f"  {mark} {sku['size']:>4} × {sku['color_code']:>4}  "
              f"{sku['stock_status']:>13}  {sku['stock_label']}")
    if len(info["skus"]) > 30:
        print(f"  ... ({len(info['skus']) - 30} 件省略)")
