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

SEARCH_URL = ("https://search.rakuten.co.jp/search/mall/{kw}/"
              "?sid={sid}&s={sort}&p={page}{extra}")
# 送料無料だけに絞る (実測 2026-08-19: `&f=2` で サンリオ 381件 → 232件)。
# ★仕入原価は「商品価格 + 送料」でなければならない (user 指摘)。 送料は都道府県で変わり
# 商品ページからも簡単には出ないので、 **送料無料の物だけ扱う** = 表示価格が総額。
FREE_SHIPPING_PARAM = "&f=2"
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

# ★実際の食べ物は扱わない (user 指摘 2026-08-19)。 食品は輸出・出品の制約が別物。
# 「お菓子のミニチュア」は扱うので、 **おもちゃを示す語がある物だけ通す** (fail-closed)。
TOY_RE = re.compile(
    r"ミニチュア|フィギュア|マスコット|チャーム|キーホルダー|ガチャ|ガシャポン|"
    r"ぬいぐるみ|アクリル|ポーチ|バッグ|コレクション|スタンド|クリップ|リング|"
    r"カプセル|レプリカ|模型")
# 明らかに実食品を指す語 (あれば通さない)
REAL_FOOD_RE = re.compile(r"賞味期限|内容量|詰め合わせ|お徳用|業務用|生菓子|食品")


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


def is_toy(title: str) -> bool:
    """おもちゃ (ミニチュア等) と分かるか。 実食品を通さないための正の条件."""
    t = title or ""
    if REAL_FOOD_RE.search(t):
        return False
    return bool(TOY_RE.search(t))


def looks_preorder(title: str) -> bool:
    """タイトルで分かる予約品か (安い一次フィルタ)."""
    return bool(PREORDER_RE.search(title or ""))


def search_shop(shop: str, keyword: str, max_pages: int = 3,
                sort: int = SORT_NEWEST, sleep_sec: float = 1.2,
                progress=None, free_shipping: bool = True) -> list[dict]:
    """店舗内をキーワード検索して {url, code, title, shop} を返す (新着順).

    free_shipping=True (既定) は **送料無料の商品だけ**。 仕入原価を
    「表示価格 = 総額」で扱えるようにするため (user 指摘 2026-08-19)。
    """
    sid = SHOP_IDS.get(shop)
    if not sid:
        raise ValueError(f"未知のショップ: {shop}")
    kw = urllib.parse.quote(keyword)
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        html = fetch(SEARCH_URL.format(
            kw=kw, sid=sid, sort=sort, page=page,
            extra=FREE_SHIPPING_PARAM if free_shipping else ""))
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
