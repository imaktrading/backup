"""zozo_scraper - ZOZOTOWN 商品ページの出品側スクレイパー (Selenium ベース・非headless).

依頼書: C:/dev/iMak_data/harvest/requests/2026-08-10_zozo_preorder_detection_confirmed_response.md

設計原則 (窓口 2026-08-10/11 [IMPLEMENT-GO]):
  - undetected_chromedriver **非headless** 固定 (headless はナビ失敗、窓口実測)
  - **ZOZO 専用 profile** 必須。listing 側専有 = 監視側は将来別 profile を切る
    (mercari で SingletonLock を踏んだ事故を繰り返さない)
  - **オフスクリーン (`--window-position=-32000,-32000`) 禁止** — 付けると弾かれる (2,577 bytes)
  - **PreOrder は variation 単位で除外** — 同一商品に PreOrder / InStock が混在するため
    商品単位で弾くと在庫分まで捨てる (窓口 2026-08-10 実サンプル対比で確定)
  - ログイン不要 (空の専用 profile で 200 OK)

在庫判定 (schema.org ld+json availability):
  https://schema.org/InStock      → in_stock=True
  https://schema.org/PreOrder     → in_stock=False, excluded=True (variation 単位で除外)
  https://schema.org/OutOfStock   → in_stock=False
  上記以外 (BackOrder/MadeToOrder 等) → 保守的に fail-closed (in_stock=False, excluded=True)

補助: HTML の `"sellType":"在庫・予約商品"` は「商品全体に予約が混在」の警告フラグ
      (窓口指示: CSV に列は足さない・別レポートで出す)

★ 「判定不能 = 在庫あり」に倒すな (BAN 事故防止):
  - fetch/parse 失敗 → 例外送出 (呼出側で fail-closed 判断)
  - PreOrder は variation を CSV から落とすが、product 単位では reject しない

★ 同時実行禁止: 監視くん側 (feature/inventory-phase1) の zozo_scraper も
  同じ profile path を使う。両者を同時起動しないこと (時間ずらし前提)。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


# ============================================================================
# 定数 (窓口 [IMPLEMENT-GO] で実測確定)
# ============================================================================
# ★ 出品側専有 profile (回答書 §profile 排他)
ZOZO_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakZozo\chrome_profile"

SELENIUM_PAGE_LOAD_TIMEOUT_SEC = 45
SELENIUM_GET_WAIT_SEC = 8
PACING_SEC_DEFAULT = 0.5

MIN_HTML_BYTES = 5000  # bot 判定検知の下限 (2,577 bytes が既知の弾かれ値)


def _pacing_sec() -> float:
    v = os.environ.get("ZOZO_PACING_SEC")
    try:
        return float(v) if v is not None else PACING_SEC_DEFAULT
    except ValueError:
        return PACING_SEC_DEFAULT


# ============================================================================
# データ構造
# ============================================================================
@dataclass
class ZozoSku:
    sku_code: str       # ld+json sku (canonical, ZOZO did= と一致)
    color: str
    size: str
    price_jpy: Optional[int]
    availability: str   # 末端トークン ("InStock" / "PreOrder" / "OutOfStock" 等)
    in_stock: bool
    excluded: bool      # PreOrder / MadeToOrder / 判定不能 → True (CSV から除外)
    stock_label: str    # 人間向けラベル ("在庫あり" / "予約商品" / "在庫なし")


@dataclass
class ZozoProduct:
    goods_id: str                      # URL の goods/<id>
    shop: str                          # URL の shop/<name> (= ブランド識別子)
    url: str
    name_jp: str                       # ld+json ProductGroup.name (商品タイトル)
    brand_jp: str                      # ld+json brand.name (= shop の日本語表記)
    description_jp: str                # ld+json description
    image_urls: list                   # ld+json image[]
    has_preorder_flag: bool            # HTML "sellType":"在庫・予約商品" 検出
    skus: list                         # list[ZozoSku] (全 SKU、excluded 含む)
    fetched_at: str
    material_jp: str = ""              # ld+json.material (無い場合は空欄)
    color_of_manufacture: str = ""     # ld+json.countryOfOrigin 等 (取れない時は空欄)


# ============================================================================
# URL パーサ
# ============================================================================
_GOODS_URL_RE = re.compile(
    r"zozo\.jp/shop/([^/]+)/goods/(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)


def parse_zozo_url(url: str) -> dict:
    """ZOZO 商品 URL から shop / goods_id / did を抽出."""
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
# ld+json / __NEXT_DATA__ 抽出 (pure functions)
# ============================================================================
_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_SELLTYPE_PREORDER_RE = re.compile(
    r'"sellType"\s*:\s*"[^"]*(?:予約|在庫・予約)[^"]*"'
)
_NEXT_DATA_RE = re.compile(
    r'<script id=["\']__NEXT_DATA__["\'] type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_ldjson_blocks(html: str) -> list:
    """ld+json ブロック群を parse して list[dict] で返す (parse 失敗は skip)."""
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


def _extract_next_data_shelves(html: str) -> dict:
    """__NEXT_DATA__ から shelves を抽出し {goodsDetailId(str) -> shelf} を返す.

    ★ ZOZO の ld+json Product は size フィールドが空 (2026-08-10 実測、全 SKU で size="")。
    size / color の canonical source は Next.js SSR (__NEXT_DATA__.props.pageProps.
    frontServerResult.goodsShelfInfo.shelves[])。
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


def _iter_products(blocks: list):
    """ProductGroup / Product / hasVariant を平坦化して yield."""
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types:
            yield b, None
            for v in (b.get("hasVariant") or []):
                if isinstance(v, dict):
                    yield v, b
        elif "Product" in types:
            yield b, None


def _normalize_availability(availability: Optional[str]) -> str:
    """'https://schema.org/InStock' → 'InStock'."""
    if not availability or not isinstance(availability, str):
        return ""
    return availability.rstrip("/").rsplit("/", 1)[-1]


_AVAILABILITY_MAP = {
    "InStock":              {"in_stock": True,  "excluded": False, "label": "在庫あり"},
    "OutOfStock":           {"in_stock": False, "excluded": False, "label": "在庫なし"},
    "SoldOut":              {"in_stock": False, "excluded": False, "label": "在庫なし"},
    "Discontinued":         {"in_stock": False, "excluded": False, "label": "在庫なし"},
    # ★ PreOrder は variation 単位で除外 (無在庫では納期が読めない)
    "PreOrder":             {"in_stock": False, "excluded": True,  "label": "予約商品"},
    "BackOrder":            {"in_stock": False, "excluded": True,  "label": "予約商品"},
    "MadeToOrder":          {"in_stock": False, "excluded": True,  "label": "受注生産"},
    "LimitedAvailability":  {"in_stock": True,  "excluded": False, "label": "残りわずか"},
}


def _classify_availability(availability: Optional[str]) -> dict:
    """availability → {in_stock, excluded, label, raw}. 未知値は fail-closed で excluded=True."""
    tok = _normalize_availability(availability)
    if tok in _AVAILABILITY_MAP:
        r = dict(_AVAILABILITY_MAP[tok])
        r["raw"] = tok
        return r
    return {"in_stock": False, "excluded": True, "label": "判定不能",
            "raw": tok or "(none)"}


def _extract_offer(prod: dict) -> dict:
    """Product.offers から代表 offer を1件抽出."""
    off = prod.get("offers")
    if isinstance(off, list) and off:
        off = off[0]
    if isinstance(off, dict) and off.get("@type") == "AggregateOffer":
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


def _first_ldjson_field(blocks: list, field_name: str) -> str:
    """ProductGroup / Product の指定フィールドを最初に見つかった値で返す (空文字 fallback)."""
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types or "Product" in types:
            v = b.get(field_name)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _ldjson_images(blocks: list) -> list:
    """ProductGroup / Product から image[] を最初に見つかった配列で返す."""
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types or "Product" in types:
            imgs = b.get("image")
            if isinstance(imgs, str) and imgs.strip():
                return [imgs.strip()]
            if isinstance(imgs, list):
                out = [x for x in imgs if isinstance(x, str) and x.strip()]
                if out:
                    return out
    return []


def _ldjson_brand(blocks: list) -> str:
    for b in blocks:
        t = b.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types or "Product" in types:
            br = b.get("brand")
            if isinstance(br, dict):
                n = br.get("name")
                if isinstance(n, str) and n.strip():
                    return n.strip()
            if isinstance(br, str) and br.strip():
                return br.strip()
    return ""


def parse_zozo_html(html: str, url: str) -> ZozoProduct:
    """ZOZO 商品ページ HTML → ZozoProduct (pure function、テスト容易).

    Raises:
        ValueError: URL 不正 / ld+json 欠損 / variation ゼロ.
    """
    info = parse_zozo_url(url)
    goods_id = info["goods_id"]
    shop = info["shop"]

    blocks = _extract_ldjson_blocks(html)
    if not blocks:
        raise ValueError(f"ld+json ブロックが見つかりません (URL={url})")

    shelves = _extract_next_data_shelves(html)

    # Product/ProductGroup レベルの共通情報
    top_name = _first_ldjson_field(blocks, "name")
    description_jp = _first_ldjson_field(blocks, "description")
    material_jp = _first_ldjson_field(blocks, "material")
    brand_jp = _ldjson_brand(blocks) or shop
    image_urls = _ldjson_images(blocks)
    has_preorder_flag = bool(_SELLTYPE_PREORDER_RE.search(html))

    skus_out = []
    seen = set()
    for prod, parent in _iter_products(blocks):
        t = prod.get("@type")
        types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
        if "ProductGroup" in types and prod.get("hasVariant"):
            continue

        sku_code = prod.get("sku") or prod.get("productID") or ""
        sku_code = str(sku_code).strip()
        if not sku_code or sku_code in seen:
            continue
        seen.add(sku_code)

        color = str(prod.get("color") or "").strip()
        size = str(prod.get("size") or "").strip()

        # __NEXT_DATA__ shelves から補完 (ZOZO の実 ld+json は size 空)
        shelf = shelves.get(sku_code) if shelves else None
        if shelf:
            if not size:
                size = str(shelf.get("sizeShortName") or shelf.get("sizeName") or "").strip()
            if not color:
                color = str(shelf.get("colorName") or "").strip()

        off = _extract_offer(prod)
        cls = _classify_availability(off["availability"])
        price_int = _price_to_int(off["price"])

        skus_out.append(ZozoSku(
            sku_code=sku_code,
            color=color,
            size=size,
            price_jpy=price_int,
            availability=cls["raw"],
            in_stock=cls["in_stock"],
            excluded=cls["excluded"],
            stock_label=cls["label"],
        ))

    if not skus_out:
        raise ValueError(f"ld+json から variation を抽出できません (URL={url})")

    skus_out.sort(key=lambda s: (s.color, s.size, s.sku_code))

    return ZozoProduct(
        goods_id=goods_id,
        shop=shop,
        url=url,
        name_jp=top_name,
        brand_jp=brand_jp,
        description_jp=description_jp,
        image_urls=image_urls,
        has_preorder_flag=has_preorder_flag,
        skus=skus_out,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
        material_jp=material_jp,
    )


# ============================================================================
# orphan chrome 掃除 (ZOZO 専用 profile 配下のみ)
# ============================================================================
def _select_stale_zozo_pids(procs, profile_dir: str, self_pid: int = 0) -> list:
    """kill 対象 PID を選ぶ純粋関数 (test 容易).

    - chrome.exe: CommandLine に ZOZO profile を含めば headless 有無を問わず対象
    - undetected_chromedriver: 親プロセスが既に死んでいる orphan のみ
    - CommandLine 取得不能 → 触らない (fail-safe)
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
            continue
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
    """ZOZO 専用 profile 配下の orphan chrome + driver を kill (clean slate)."""
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
            log("  [zozo cleanup] orphan なし")
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Stop-Process -Id " + ",".join(str(p) for p in pids) +
             " -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log(f"  [zozo cleanup] {len(pids)} 個を一掃")
    except Exception as e:
        log(f"  [zozo cleanup] skip ({type(e).__name__}: {e})")


# ============================================================================
# Selenium driver factory (非headless 固定・専用 profile 必須)
# ============================================================================
def _detect_chrome_major() -> Optional[int]:
    """Windows レジストリから Chrome major を検出 (無ければ None = uc 自動検出)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
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


def create_driver():
    """undetected_chromedriver の非headless driver を生成 (ZOZO 専用).

    ★ headless / offscreen 禁止 (両方とも実測で弾かれる)
    ★ 専用 profile 必須 (mercari profile 共有は SingletonLock 競合)
    """
    try:
        import undetected_chromedriver as uc
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。pip install undetected-chromedriver"
        )

    os.makedirs(ZOZO_CHROME_PROFILE_DIR, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={ZOZO_CHROME_PROFILE_DIR}")
    options.page_load_strategy = "eager"

    version_main = _detect_chrome_major()
    driver = uc.Chrome(options=options, version_main=version_main)
    try:
        driver.set_page_load_timeout(SELENIUM_PAGE_LOAD_TIMEOUT_SEC)
    except Exception:
        pass
    return driver


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product(url: str, driver=None) -> ZozoProduct:
    """ZOZO 商品 URL → ZozoProduct (fetch + parse).

    Args:
        url: ZOZO goods URL (例 https://zozo.jp/shop/minius/goods/103638934/)
        driver: 既存 driver を渡せば再利用 (複数 URL 巡回時に節約可)

    Raises:
        ValueError: URL 不正 / ld+json 欠損 / variation ゼロ
        RuntimeError: レスポンスが小さすぎる (bot 判定検知)
    """
    if not url:
        raise ValueError("URL が空です")
    parse_zozo_url(url)

    owns_driver = driver is None
    if owns_driver:
        kill_stale_zozo_chrome(log=lambda *a, **k: None)
        driver = create_driver()

    try:
        time.sleep(_pacing_sec())
        driver.get(url)
        time.sleep(SELENIUM_GET_WAIT_SEC)
        html = driver.page_source or ""
        if len(html) < MIN_HTML_BYTES:
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
    p = fetch_product(test_url)
    print(f"name  : {p.name_jp}")
    print(f"brand : {p.brand_jp}  shop={p.shop}  goods_id={p.goods_id}")
    print(f"images: {len(p.image_urls)}")
    print(f"preorder_flag: {p.has_preorder_flag}")
    print(f"=== SKU 一覧 ({len(p.skus)}) ===")
    for s in p.skus:
        mark = "◎" if s.in_stock else ("△" if s.excluded else "✕")
        price_str = f"¥{s.price_jpy}" if s.price_jpy is not None else "¥?"
        print(f"  {mark} {s.color:>8} {s.size:>10} sku={s.sku_code} "
              f"{s.stock_label:>7} {price_str}")
