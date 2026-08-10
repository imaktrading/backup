"""zozo_scraper - ZOZOTOWN 商品ページの在庫スクレイパー (Selenium ベース・非headless).

設計原則 (2026-08-10 窓口 [IMPLEMENT-GO] 起票):
  - 既存モジュール (iMakeBayAPI / iMakInventory / 他プロジェクト) を一切 import しない
  - undetected_chromedriver **非headless** 固定 (headless はナビ失敗、窓口実測 2026-08-10)
  - **ZOZO 専用 profile** 必須 (mercari profile 共有は SingletonLock 競合で起動不能。実測再現)
  - **オフスクリーン (`--window-position=-32000,-32000`) 禁止** — 付けると弾かれる (2,577 bytes)
  - **PreOrder は variation 単位で除外** — 同一商品に PreOrder 25 / InStock 15 が混在するため
    商品単位で弾くと在庫分まで捨てる (窓口 2026-08-10 実サンプル対比で確定)
  - ログイン不要 (空の専用 profile で 200 OK / 280,690 bytes)

在庫判定 (schema.org ld+json availability):
  https://schema.org/InStock         → 在庫あり (in_stock=True)
  https://schema.org/PreOrder        → **PreOrder** (in_stock=False、excluded=True)
  https://schema.org/OutOfStock      → 在庫なし (in_stock=False)
  上記以外 (BackOrder/MadeToOrder 等) → 保守的に 在庫なし扱い (fail-closed)

補助: HTML の `"sellType":"在庫・予約商品"` は「商品全体に予約が混在」の警告として使う
      (variation 単位判定で十分だが、ログに残す)

★ 「判定不能 = 在庫なし」に倒すな (snkrdunk 事故の轍を踏まない):
  - HTTP/Selenium 例外 → 例外送出 (呼出側で fail-closed=None 扱い)
  - ld+json 欠損 → ValueError 送出 (在庫なしに倒さない)
  - PreOrder は「除外」= in_stock=False にはするが `excluded=True` フラグで区別
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


# ============================================================================
# 定数 (窓口 [IMPLEMENT-GO] で実測確定)
# ============================================================================
# ★ ZOZO 専用 profile — mercari profile 共有禁止 (SingletonLock 競合で稼働中の巡回が死ぬ)
ZOZO_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakZozo\chrome_profile"

# uc.Chrome 起動時のタイムアウト・pacing
SELENIUM_PAGE_LOAD_TIMEOUT_SEC = 45
SELENIUM_GET_WAIT_SEC = 8         # driver.get() 後 ld+json 描画待ち (JS で埋め込まれるため)
PACING_SEC_DEFAULT = 0.5           # 同一 driver で複数商品を巡回する際の間隔


def _pacing_sec() -> float:
    v = os.environ.get("ZOZO_PACING_SEC")
    try:
        return float(v) if v is not None else PACING_SEC_DEFAULT
    except ValueError:
        return PACING_SEC_DEFAULT


# ============================================================================
# URL パーサ
# ============================================================================
# 例: https://zozo.jp/shop/minius/goods/103638934/?did=166413955
_GOODS_URL_RE = re.compile(
    r"zozo\.jp/shop/([^/]+)/goods/(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)


def parse_zozo_url(url: str) -> dict:
    """ZOZO 商品 URL から shop / goods_id / did (SKU query) を抽出.

    Returns: {"shop": "minius", "goods_id": "103638934", "did": "166413955" or ""}
    """
    if not url:
        raise ValueError("URL が空です")
    m = _GOODS_URL_RE.search(url)
    if not m:
        raise ValueError(f"ZOZO goods URL 形式が不正: {url}")
    shop, goods_id = m.group(1), m.group(2)
    did = ""
    try:
        q = urllib.parse.urlparse(url).query
        if q:
            qs = urllib.parse.parse_qs(q)
            did = (qs.get("did") or [""])[0]
    except Exception:
        did = ""
    return {"shop": shop, "goods_id": goods_id, "did": did}


# ============================================================================
# ld+json 抽出 (fetch と分離、pure function・テスト容易)
# ============================================================================
_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
# HTML 内 "sellType":"在庫・予約商品" は商品全体の予約混在マーカー
_SELLTYPE_PREORDER_RE = re.compile(
    r'"sellType"\s*:\s*"[^"]*(?:予約|在庫・予約)[^"]*"'
)
# ★ ZOZO の Next.js SSR data (size/color の正本、ld+json には size フィールドが無い)
#   root.props.pageProps.frontServerResult.goodsShelfInfo.shelves[]:
#     { "goodsDetailId": 166413955,       # = ld+json の sku (canonical KEY)
#       "sizeShortName": "M", "sizeName": "MEDIUM",
#       "colorName": "ブラック", "colorId": 8, "sizeId": 2,
#       "captionType": "INSTOCK" / (predorder-like), "stockQuantity": N,
#       "reserveDeliveryDatetime": null or ISO }
_NEXT_DATA_RE = re.compile(
    r'<script id=["\']__NEXT_DATA__["\'] type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_next_data_shelves(html: str) -> dict:
    """__NEXT_DATA__ から shelves を抽出し {goodsDetailId(str): shelf_dict} を返す.

    ★ ZOZO の ld+json Product には `size` が入らない実装 (2026-08-10 実測、8商品全件で size 欠損)。
    Next.js の SSR 状態 (__NEXT_DATA__) の shelves が **size/color/stockQuantity の canonical source**。
    ld+json の availability と組合せて使う (in_stock/excluded は ld+json 側で確定、size は shelves)。

    パース不能 or 経路不在は **空 dict を返す** (捏造しない・落とさない fail-safe)。
    呼出側は size を "" のまま許容し、name フォールバックへ回す。
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}
    try:
        shelves = data["props"]["pageProps"]["frontServerResult"]["goodsShelfInfo"]["shelves"]
    except (KeyError, TypeError):
        return {}
    if not isinstance(shelves, list):
        return {}
    out = {}
    for s in shelves:
        if not isinstance(s, dict):
            continue
        gid = s.get("goodsDetailId")
        if gid is None:
            continue
        out[str(gid)] = s
    return out


def _extract_ldjson_blocks(html: str) -> list:
    """<script type="application/ld+json"> ブロックを JSON parse して list で返す.

    parse 失敗ブロックは silently skip (他ブロックが有効なら救う fail-safe)。
    """
    out = []
    for block in _LDJSON_RE.findall(html):
        text = block.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _iter_products(blocks: list):
    """ld+json ブロック群から Product / ProductGroup / hasVariant を平坦化.

    Yields: (product_dict, parent_dict_or_None)
      parent は ProductGroup の場合セット (name/productGroupID 参照用).
    """
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types:
            yield b, None   # ProductGroup 本体も列挙対象 (name 参照)
            for v in (b.get("hasVariant") or []):
                if isinstance(v, dict):
                    yield v, b
        elif "Product" in types:
            yield b, None


def _normalize_availability(availability: Optional[str]) -> str:
    """schema.org URL を末端トークン化: 'https://schema.org/InStock' → 'InStock'."""
    if not availability or not isinstance(availability, str):
        return ""
    return availability.rstrip("/").rsplit("/", 1)[-1]


# 在庫判定: schema.org availability → in_stock / excluded / stock_label
_AVAILABILITY_MAP = {
    "InStock":       {"in_stock": True,  "excluded": False, "label": "在庫あり"},
    "OutOfStock":    {"in_stock": False, "excluded": False, "label": "在庫なし"},
    "SoldOut":       {"in_stock": False, "excluded": False, "label": "在庫なし"},
    "Discontinued":  {"in_stock": False, "excluded": False, "label": "在庫なし"},
    # ★ PreOrder は variation 単位で除外 (無在庫では納期が読めない)
    "PreOrder":      {"in_stock": False, "excluded": True,  "label": "予約商品"},
    "BackOrder":     {"in_stock": False, "excluded": True,  "label": "予約商品"},
    "MadeToOrder":   {"in_stock": False, "excluded": True,  "label": "受注生産"},
    "LimitedAvailability": {"in_stock": True, "excluded": False, "label": "残りわずか"},
}


def _classify_availability(availability: Optional[str]) -> dict:
    """availability → {in_stock, excluded, label, raw}.

    未知値 (schema.org の新規/私設値) は **保守的に 在庫なし扱い + excluded=True**
    (fail-closed。「判定不能を在庫あり」に倒すと誤出品→キャンセル→BAN)。
    """
    tok = _normalize_availability(availability)
    if tok in _AVAILABILITY_MAP:
        r = dict(_AVAILABILITY_MAP[tok])
        r["raw"] = tok
        return r
    return {"in_stock": False, "excluded": True, "label": "判定不能",
            "raw": tok or "(none)"}


def _extract_offer(prod: dict) -> dict:
    """Product.offers から 1 件を抽出 (単独 or 配列/AggregateOffer 対応).

    Returns: {"availability": str, "price": str_or_None, "currency": str}
    未取得値は "" / None。
    """
    off = prod.get("offers")
    if isinstance(off, list) and off:
        off = off[0]
    if isinstance(off, dict) and off.get("@type") == "AggregateOffer":
        # AggregateOffer は代表オファーとして low/high の代わりに availability があるはず
        return {
            "availability": off.get("availability", ""),
            "price": off.get("lowPrice") or off.get("price"),
            "currency": off.get("priceCurrency", "JPY"),
        }
    if isinstance(off, dict):
        return {
            "availability": off.get("availability", ""),
            "price": off.get("price"),
            "currency": off.get("priceCurrency", "JPY"),
        }
    return {"availability": "", "price": None, "currency": "JPY"}


def _price_to_int(v) -> Optional[int]:
    """'4950' / 4950 / 4950.0 → 4950。 パース不能 → None。 空文字は None (0 円と誤認しない)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        try:
            return int(float(s))
        except ValueError:
            return None
    return None


# 色/サイズを name から補完するための緩い抽出 (Product.color/.size が無い場合)
# 例: "商品名 (ブラック/MEDIUM)" / "商品名 [BLACK][M]"
_NAME_COLOR_SIZE_PARENS = re.compile(r"[（(]\s*([^/()（）]+?)\s*/\s*([^/()（）]+?)\s*[）)]")
_NAME_COLOR_SIZE_BRACKETS = re.compile(r"[\[［]\s*([^\]／]+?)\s*[\]］]\s*[\[［]\s*([^\]／]+?)\s*[\]］]")


def _extract_color_size_from_name(name: str) -> tuple:
    """Product.color/.size が無い場合の緩いフォールバック抽出.
    見つからなければ ("", "") を返す (捏造しない)。
    """
    if not name:
        return ("", "")
    m = _NAME_COLOR_SIZE_PARENS.search(name)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    m = _NAME_COLOR_SIZE_BRACKETS.search(name)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return ("", "")


def parse_zozo_html(html: str, url: str) -> dict:
    """ZOZO 商品ページ HTML から variation 単位の SKU 一覧を抽出 (pure function).

    Returns: {
        "name":              商品名 (ProductGroup / Product name),
        "product_id":        goods_id (URL 由来),
        "shop":              shop 名 (URL 由来),
        "color":             "" (multi-color 前提),
        "color_code":        "",
        "has_preorder_flag": bool (HTML "sellType":"在庫・予約商品" 検出),
        "fetched_at":        取得時刻 ISO,
        "skus": [
            {
                "size":              "MEDIUM",
                "size_display_code": "MEDIUM",
                "sku_code":          "166413955",   # ld+json sku (canonical KEY)
                "l2Id":              "166413955",   # uniqlo 互換 alias
                "communication_code":"166413955",
                "in_stock":          True/False,
                "stock_status":      "InStock" / "PreOrder" / "OutOfStock" / "(none)",
                "stock_label":       "在庫あり" / "予約商品" / "在庫なし",
                "quantity":          1 or 0,
                "price_jpy":         4950,        # 実際に払う額 (base=promo 区別不能)
                "promo_price_jpy":   4950,
                "list_price_jpy":    None,        # ZOZO は base/promo 区別不能 → U 列空欄
                "sales_active":      True,        # ld+json に販売期間がないので True 固定
                "color":             "ブラック",
                "color_code":        "ブラック",
                "excluded":          False/True,  # PreOrder は True
                "raw_availability":  末端トークン (デバッグ用),
            },
            ...
        ],
    }
    """
    info = parse_zozo_url(url)
    goods_id = info["goods_id"]
    shop = info["shop"]

    blocks = _extract_ldjson_blocks(html)
    if not blocks:
        raise ValueError(f"ld+json ブロックが見つかりません (URL={url})")

    # ★ shelves 索引 (size の canonical source、ld+json には size フィールド無し)
    #   {goodsDetailId(str) -> shelf_dict}。取得不能なら空 dict = size は名前 fallback のみ。
    shelves = _extract_next_data_shelves(html)

    # ProductGroup 名 or Product 名を優先
    top_name = ""
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types and b.get("name"):
            top_name = b["name"]
            break
    if not top_name:
        for b in blocks:
            t = b.get("@type")
            types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if "Product" in types and b.get("name"):
                top_name = b["name"]
                break

    has_preorder_flag = bool(_SELLTYPE_PREORDER_RE.search(html))

    # variation 抽出
    skus_out = []
    seen_skus = set()
    for prod, parent in _iter_products(blocks):
        # ProductGroup 本体 (variant を持つ側) は SKU 化しない
        t = prod.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types and prod.get("hasVariant"):
            continue

        sku = prod.get("sku") or prod.get("productID") or ""
        sku = str(sku).strip()
        if not sku or sku in seen_skus:
            continue
        seen_skus.add(sku)

        name = prod.get("name") or ""
        color = prod.get("color") or ""
        size = prod.get("size") or ""
        # ★ __NEXT_DATA__ shelves から size/color を補完 (ZOZO の実 ld+json には size 無し)
        shelf = shelves.get(sku) if shelves else None
        if shelf:
            if not size:
                # sizeShortName (M/L/XL) を優先。 uniqlo 巡回と粒度が揃う (JP L 等)。
                # sizeName ("MEDIUM") はフルネームで match 精度落ちるため補助扱い。
                size = str(shelf.get("sizeShortName") or shelf.get("sizeName") or "").strip()
            if not color:
                color = str(shelf.get("colorName") or "").strip()
        # 最後の砦: name パターンからの緩い抽出 (Product.color/.size も shelves も無い場合)
        if not color or not size:
            fc, fs = _extract_color_size_from_name(name)
            if not color:
                color = fc
            if not size:
                size = fs

        off = _extract_offer(prod)
        cls = _classify_availability(off["availability"])
        price_int = _price_to_int(off["price"])

        skus_out.append({
            "size":              size,
            "size_display_code": size,
            "sku_code":          sku,
            "l2Id":              sku,
            "communication_code": sku,
            "in_stock":          cls["in_stock"],
            "stock_status":      cls["raw"],
            "stock_label":       cls["label"],
            "quantity":          1 if cls["in_stock"] else 0,
            # ZOZO は base/promo 区別不能。J=U 同値の supplier ではなく **U は None** で
            # 「定価不明」を明示 (workman/montbell/amazon と同じ扱い)。
            "price_jpy":         price_int,
            "promo_price_jpy":   price_int,
            "list_price_jpy":    None,
            "sales_active":      True,
            "color":             color,
            "color_code":        color,
            "excluded":          cls["excluded"],
            "raw_availability":  cls["raw"],
        })

    if not skus_out:
        raise ValueError(f"ld+json から variation を抽出できません (URL={url})")

    # 決定的順序: sku_code 昇順
    skus_out.sort(key=lambda s: s["sku_code"])

    return {
        "name":              top_name,
        "product_id":        goods_id,
        "shop":              shop,
        "color":             "",
        "color_code":        "",
        "has_preorder_flag": has_preorder_flag,
        "fetched_at":        datetime.now().isoformat(timespec="seconds"),
        "skus":              skus_out,
    }


# ============================================================================
# orphan chrome 一掃 (ZOZO 専用 profile 対象、非headless も含む)
# ============================================================================
# ★ 監視くん既存の掃除条件 (「--headless かつ自分の profile」限定) は非headless の
# ZOZO chrome を残す構造なので、ZOZO 専用 profile を明示追加する必要がある
# (窓口回答書 2026-08-10 §c)。 dedicated profile なのでユーザーの通常ブラウザは絶対に
# ここに来ない = headless 有無を問わず kill してよい。
def _select_stale_zozo_pids(procs, profile_dir: str, self_pid: int = 0) -> list:
    """kill すべき PID を選ぶ純粋関数 (test 容易).

    - chrome.exe: CommandLine に ZOZO profile を含めば **headless 有無を問わず** kill 対象
    - undetected_chromedriver: 親プロセスが既に死んでいる真の orphan のみ (fail-safe)
    - CommandLine 取得不能 → kill しない (fail-safe: 判定不能なら触らない)
    """
    if not profile_dir:
        return []
    profile_low = profile_dir.strip().lower()
    if not profile_low:
        return []
    live = {int(p.get("ProcessId") or 0) for p in procs if p.get("ProcessId")}
    out = []
    for p in procs:
        try:
            pid = int(p.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if not pid or pid == self_pid:
            continue
        name = (p.get("Name") or "").lower()
        cmd = (p.get("CommandLine") or "")
        if not cmd:
            continue  # fail-safe: 判定不能なら触らない
        low = cmd.lower()
        if name == "chrome.exe":
            if profile_low in low:
                out.append(pid)
        elif name.startswith("undetected_chromedriver"):
            try:
                ppid = int(p.get("ParentProcessId") or 0)
            except (TypeError, ValueError):
                continue
            if ppid and ppid not in live:
                out.append(pid)
    return out


def kill_stale_zozo_chrome(log=print) -> None:
    """ZOZO 専用 profile 配下の orphan chrome + orphan driver を kill (clean slate).

    driver 生成"前"に呼ぶこと。 cycle 途中で呼ぶと稼働中の driver を巻き込む。
    非-Windows / powershell 例外は silent skip (fail-safe: cycle を止めない)。
    """
    if sys.platform != "win32":
        return
    ps = ("Get-CimInstance Win32_Process | "
          "Select-Object ProcessId,ParentProcessId,Name,CommandLine "
          "| ConvertTo-Json -Compress -Depth 2")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        procs = json.loads((r.stdout or "").strip() or "[]")
        if isinstance(procs, dict):
            procs = [procs]
        pids = _select_stale_zozo_pids(procs, ZOZO_CHROME_PROFILE_DIR, self_pid=os.getpid())
        if not pids:
            log("  [zozo cleanup] orphan なし (ZOZO 専用 profile 配下のみ対象)")
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Stop-Process -Id " + ",".join(str(p) for p in pids) +
             " -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log(f"  [zozo cleanup] {len(pids)} 個を一掃 (ZOZO 専用 profile 限定)")
    except Exception as e:
        log(f"  [zozo cleanup] skip ({type(e).__name__}: {e})")


# ============================================================================
# Selenium driver factory (非headless 固定・専用 profile 必須)
# ============================================================================
def create_driver():
    """undetected_chromedriver の非headless driver を生成 (ZOZO 専用).

    ★ **headless 禁止** (窓口 2026-08-10 実測: headless はナビ失敗)
    ★ **オフスクリーン (`--window-position=-32000,-32000`) 禁止** (弾かれる、2,577 bytes)
    ★ **専用 profile 必須** (mercari profile 共有は SingletonLock 競合)
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。pip install undetected-chromedriver"
        )

    # 専用 profile dir を作成 (無ければ)
    os.makedirs(ZOZO_CHROME_PROFILE_DIR, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={ZOZO_CHROME_PROFILE_DIR}")
    # page_load_strategy=eager: DOMContentLoaded で返る (画像/サブリソース待たない)
    options.page_load_strategy = "eager"
    # ★ headless / offscreen を絶対に付けない (両方とも実測で弾かれる)

    # Chrome major を自動検出 (version_main ハードコード禁止・グローバル規約)
    version_main = _detect_chrome_major()
    driver = uc.Chrome(options=options, version_main=version_main)
    try:
        driver.set_page_load_timeout(SELENIUM_PAGE_LOAD_TIMEOUT_SEC)
    except Exception:
        pass
    return driver


def _detect_chrome_major() -> Optional[int]:
    """Windows レジストリから Chrome major を検出 (無ければ None = uc 自動検出)."""
    try:
        import winreg  # noqa: PLC0415
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                ver, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                return int(str(ver).split(".")[0])
            except OSError:
                continue
    except Exception:
        return None
    return None


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(url: str, driver=None) -> dict:
    """ZOZO 商品 URL から在庫・価格情報を取得 (uniqlo_scraper と同 shape).

    Args:
        url: ZOZO goods URL (例 https://zozo.jp/shop/minius/goods/103638934/)
        driver: 既存 driver を渡せば再利用 (複数商品を巡回する呼出側で節約可)

    Returns: parse_zozo_html の出力。取得失敗時は例外送出 (呼出側で fail-closed 判断).
    """
    if not url:
        raise ValueError("URL が空です")
    parse_zozo_url(url)   # 早期 URL 検証

    owns_driver = driver is None
    if owns_driver:
        kill_stale_zozo_chrome(log=lambda *a, **k: None)  # 起動前に自分の残骸を一掃
        driver = create_driver()

    try:
        time.sleep(_pacing_sec())
        driver.get(url)
        # ld+json は SSR で即入っているはずだが、JS で追記される可能性を考慮して短時間待機
        time.sleep(SELENIUM_GET_WAIT_SEC)
        html = driver.page_source or ""
        if not html or len(html) < 5000:
            # 2,577 bytes 弾き検知 (オフスクリーン起動時に再現した事故モード)
            raise RuntimeError(
                f"ZOZO レスポンスが小さすぎる (bytes={len(html)})、bot 判定の可能性")
        return parse_zozo_html(html, url)
    finally:
        if owns_driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    # Windows cp932 コンソール向け UTF-8 化
    for _stream_name in ("stdout", "stderr"):
        _s = getattr(sys, _stream_name, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    test_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://zozo.jp/shop/minius/goods/103638934/"
    )
    print(f"--- URL: {test_url}")
    result = fetch_product_inventory(test_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print(f"=== 在庫サマリー ({result['name']}) ===")
    for sku in result["skus"]:
        mark = "◎" if sku["in_stock"] else ("△" if sku["excluded"] else "✕")
        p = sku["price_jpy"]
        price_str = f"¥{p}" if p is not None else "¥?"
        print(f"  {mark} {sku['color']:>8} {sku['size']:>10} sku={sku['sku_code']} "
              f"{sku['stock_label']:>7} {price_str}")
