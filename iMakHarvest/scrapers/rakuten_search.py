"""rakuten_search - 楽天の**店舗内検索**から商品 URL を集める (HTTP のみ・ブラウザ不要).

2026-08-19 新設 (user 依頼「楽天3店からガチャポンのコンプ品を」)。

実測 (2026-08-19):
  - `https://search.rakuten.co.jp/search/mall/<kw>/?sid=<shop id>` が
    curl でそのまま 200。 Cookie も JS も要らない。 ブロックも無い
  - 1ページ45件、 40ページ目でも 45件返る (メルカリのような早い頭打ちは無い)
  - `&s=4` が新着順 (1=標準/2=安い/3=高い/4=新着/5,6=レビュー)
  - 返る商品は **100% その店舗のもの** (sid の絞り込みは効いている)

検索は無料なので広く取り、 高い判定 (商品ページを開く) は呼出側で絞ってから行う。
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://search.rakuten.co.jp/search/mall/{kw}/?sid={sid}&s={sort}&p={page}"
SORT_NEWEST = 4
PER_PAGE = 45
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

# 店舗ID (2026-08-19 実測)
SHOP_IDS = {
    "auc-yuyou": 274922,
    "kidsroom": 256218,
    "mirakikaku": 402046,
}

_PAIR_RE = re.compile(
    r'href="(https://item\.rakuten\.co\.jp/([a-z0-9_-]+)/([a-z0-9_-]+)/)[^"]*"[^>]*>([^<]{6,120})<'
)
_COUNT_RE = re.compile(r"([0-9,]+)件")

# 予約品を落とす語 (タイトルで分かる分。 最終判定は商品ページの配送予定で行う)
PREORDER_RE = re.compile(r"予約|発売予定|入荷予定|再入荷|[0-9０-９]{1,2}月→")
# コンプ品の目印 (3店とも「全N種セット」「コンプ」を必ず入れる)
COMPLETE_RE = re.compile(r"全\s*[0-9０-９]{1,2}\s*種|コンプ")


def fetch(url: str, timeout: int = 30) -> str:
    """HTTP GET (楽天は User-Agent 等が無いと 503 を返す)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    for enc in ("utf-8", "euc_jp", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_results(html: str, shop: str) -> list[dict]:
    """検索結果 HTML から {url, code, title} を取り出す (純関数)."""
    out: list[dict] = []
    seen: set[str] = set()
    for url, sh, code, title in _PAIR_RE.findall(html):
        if sh != shop or code in seen:
            continue
        seen.add(code)
        out.append({"url": url, "code": code, "title": title.strip()})
    return out


def parse_total(html: str) -> int:
    """「N件」表記を返す (取れなければ 0)."""
    m = _COUNT_RE.search(html)
    return int(m.group(1).replace(",", "")) if m else 0


def is_complete_set(title: str) -> bool:
    """コンプ品 (全N種セット) か。 タイトルだけで判定できる."""
    return bool(COMPLETE_RE.search(title or ""))


def looks_preorder(title: str) -> bool:
    """タイトルで分かる予約品か (安い一次フィルタ)."""
    return bool(PREORDER_RE.search(title or ""))


def search_shop(shop: str, keyword: str, max_pages: int = 3,
                sort: int = SORT_NEWEST, sleep_sec: float = 1.2,
                progress=None) -> list[dict]:
    """店舗内をキーワード検索して {url, code, title, shop} を返す (新着順)."""
    sid = SHOP_IDS.get(shop)
    if not sid:
        raise ValueError(f"未知のショップ: {shop}")
    kw = urllib.parse.quote(keyword)
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        html = fetch(SEARCH_URL.format(kw=kw, sid=sid, sort=sort, page=page))
        rows = parse_results(html, shop)
        if not rows:
            break
        for r in rows:
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            r["shop"] = shop
            out.append(r)
        if progress:
            progress(f"{shop} '{keyword}' p{page}: {len(rows)}件 (累計 {len(out)})")
        if len(rows) < PER_PAGE:
            break
        time.sleep(sleep_sec)
    return out
