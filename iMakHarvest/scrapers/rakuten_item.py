"""rakuten_item - 楽天の商品ページから 即納判定 / 価格 / 画像を取る.

2026-08-19 新設。

★**在庫マーク (availability) は使えない**。 予約品も `InStock` を返す (実測21/21件)。
  予約品もカートに入るので当然で、 「買えるか」ではなく「いつ発送されるか」を見る必要がある。

★**配送予定は JS 描画後にしか出ない**ので、 ここだけブラウザが要る (1件6秒)。
  実測 (2026-08-19):
    即納  kidsroom   「8/20 9:00までの注文で最短8/23お届け」
    即納  mirakikaku 「1～2営業日内に発送」
    即納  auc-yuyou  「1〜2日以内に発送」
    予約  auc-yuyou  「★こちらの商品は【2026年11月入荷予定の予約商品】です。」
    予約  kidsroom   配送予定の下は注意書きのみ (日付が出ない)

判定は fail-closed。 **発送日が読めた物だけ即納**とし、 読めなければ通さない。
"""
from __future__ import annotations

import re
from html import unescape

DETAIL_WAIT_SEC = 8

# 「配送予定」ブロックの後ろに出る発送日の表記
SHIP_DATE_RE = re.compile(
    # 「(8/21) 13:00までの注文で最短 8/22 お届け」。 **頭の日付は出ない日がある**
    # (2026-08-20 実測: 「13:00までの注文で最短8/22お届け」だけの表示。 日付必須にしていた
    #  ため auc-yuyou が丸ごと no_shipping_info で落ちていた)
    r"(?:[0-9]{1,2}/[0-9]{1,2}\s*)?[0-9]{1,2}[:：][0-9]{2}\s*までの注文で最短\s*([0-9]{1,2}/[0-9]{1,2})\s*お届け"
    r"|([0-9０-９]{1,2}\s*[〜～]?\s*[0-9０-９]{0,2}\s*(?:営業)?日以内?に発送)"
    r"|([0-9０-９]{1,2}\s*[〜～]\s*[0-9０-９]{1,2}\s*営業日内に発送)"
)
# 予約と明記されている表記 (配送予定欄にも本文にも出る)
PREORDER_RE = re.compile(
    r"入荷予定の予約商品|予約商品です|発売予定[：: ]?\s*[0-9０-９]{4}年|予約入荷待ち"
)


def extract_shipping(text: str) -> str:
    """画面テキストから発送日の表記を返す (取れなければ "")."""
    m = SHIP_DATE_RE.search(text or "")
    if not m:
        return ""
    return next((g for g in m.groups() if g), "").strip()


def judge(text: str) -> dict:
    """商品ページの画面テキストから 即納かどうかを判定する (純関数).

    Returns: {"in_stock_now": bool, "shipping": str, "reason": str}
      in_stock_now=True は **発送日が読めた** 時だけ。
    """
    if PREORDER_RE.search(text or ""):
        return {"in_stock_now": False, "shipping": "", "reason": "preorder"}
    ship = extract_shipping(text)
    if ship:
        return {"in_stock_now": True, "shipping": ship, "reason": "ok"}
    return {"in_stock_now": False, "shipping": "", "reason": "no_shipping_info"}


_IMG_RE = re.compile(r"https://(?:tshop|shop|image)\.r?10?s?\.?(?:rakuten\.co\.jp|jp)/[^\"'\s]+?\.(?:jpg|jpeg|png)",
                     re.IGNORECASE)
_CODE_RE = re.compile(r"item\.rakuten\.co\.jp/[a-z0-9_-]+/([a-z0-9_-]+)", re.IGNORECASE)


def extract_images(html: str, url: str) -> list[str]:
    """商品ページから **その商品の写真だけ** を返す.

    2026-08-20 修正 (user 指摘「画像も取れない」)。 以前は `image.rakuten.co.jp` の
    URL を出現順に 8枚取っていたが、 楽天の店舗テンプレは **ヘッダ/サイドのバナーが
    先に並ぶ**ため、 実測 93件中 93件が バナーだけだった (商品写真 0枚)。

    確実に商品の物と言えるのは次の 2つだけ。 それ以外は入れない (fail-closed):
      ① `og:image` (= 楽天が出す代表画像)
      ② ファイル名に **商品コード** を含む画像 (例 `.../g260736s02t.jpg`,
         `.../2608001_c0.jpg`)。 バナーは `parts/header/...` `common1.jpg` 等で該当しない
    """
    out: list[str] = []
    m = re.search(r"""property=["']og:image["'][^>]*content=["']([^"']+)""", html)
    if m:
        out.append(m.group(1))
    cm = _CODE_RE.search(url or "")
    code = (cm.group(1) if cm else "").lower()
    if code:
        for u in _IMG_RE.findall(html):
            name = u.rsplit("/", 1)[-1].lower()
            if code in name:
                out.append(u)
    # 同じ写真が shop/tshop の両ドメインで出るので ファイル名で重複を潰す
    seen, uniq = set(), []
    for u in out:
        k = u.rsplit("/", 1)[-1].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(u)
    return uniq[:8]


_DESC_RE = re.compile(r'class="item_desc"(.{0,12000}?)</td>', re.S)
_DESC_END = re.compile(r"(この商品の(セット|単品)|同シリーズ|関連商品一覧|商品番号[：:]|レビューを見る)")
_JAN_RE = re.compile(r'itemprop="gtin13"\s+content="(\d{8,14})"')


def extract_jan(html: str) -> str:
    """楽天が出す `itemprop="gtin13"` = JAN. 無ければ空."""
    m = _JAN_RE.search(html or "")
    return m.group(1) if m else ""


def extract_description(html: str) -> str:
    """商品説明 (ラインナップ / サイズ / 注意書き) を平文で返す.

    2026-08-20 新設。 それまで H列は空だった。 出品に要る「全何種の内訳」と
    「サイズ」はここにしか無い (タイトルには入らない)。
    末尾の 関連商品リンク (「この商品のセット、単品一覧を見る」等) は落とす。
    """
    m = _DESC_RE.search(html or "")
    if not m:
        return ""
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    txt = unescape(txt)
    txt = re.sub(r"[ -‏﻿]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" >　")
    cut = _DESC_END.search(txt)
    if cut:
        txt = txt[:cut.start()].strip()
    return txt[:1200]


# 「配送情報」欄に出る送料。 実測 2026-08-20 (auc-toysanta):
#   送料無料 → 「配送情報 送料無料 宅配便(佐川急便) 送料無料ライン対象」
#   有料     → 「配送情報 送料680円 宅配便[特定送料] 送料無料ライン対象外 6,500円以上で送料無料」
# ★「送料無料ライン対象外」「6,500円以上で送料無料」に引っかからないよう、
#   **金額表記を先に見る**。 どちらも読めなければ None (= 分からない) を返す。
_FEE_RE = re.compile(r"送料\s*([0-9][0-9,]*)\s*円")
_FREE_RE = re.compile(r"^[\s　]*送料無料")


def extract_shipping_fee(text: str) -> int | None:
    """画面テキストから **その商品の送料 (円)** を返す. 読めなければ None.

    仕入原価は「商品価格 + 送料」で見る (user 指示 2026-08-20)。
    表示は既定の配送先のもの。 離島等は別途かかる。
    """
    t = text or ""
    i = t.find("配送情報")
    if i < 0:
        return None
    seg = t[i + len("配送情報"):i + 400]
    m = _FEE_RE.search(seg)
    if m:
        return int(m.group(1).replace(",", ""))
    if _FREE_RE.search(seg):
        return 0
    return None


def _text_of(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text or ""
    except Exception:  # noqa: BLE001
        return ""


def fetch_detail(driver, url: str, wait_sec: int = DETAIL_WAIT_SEC) -> dict | None:
    """ブラウザで商品ページを開いて 即納判定 + 価格 + 画像を返す.

    Returns None は「ページを開けなかった」= 未判定 (呼出側で要対応として数える)。
    """
    import time  # noqa: PLC0415

    try:
        driver.get(url)
    except Exception:  # noqa: BLE001
        return None
    time.sleep(wait_sec)

    # ★消えた商品は **店トップへ飛ばされる** (2026-08-20 実測: jugem2020 の32件が
    #   検索には出るのに商品ページは 404 → `https://www.rakuten.co.jp/<shop>/` に転送)。
    #   気づかずに店トップの文言を商品情報として拾っていた。 URL が変わっていたら捨てる。
    try:
        now = driver.current_url or ""
    except Exception:  # noqa: BLE001
        now = ""
    if now and not now.startswith(url.split("?")[0].rstrip("/")):
        return None

    text = _text_of(driver)
    if not text:
        return None

    html = driver.page_source or ""
    price = ""
    m = re.search(r'itemprop="price"[^>]*content="([0-9]+)"', html)
    if m:
        price = m.group(1)
    title = ""
    m = re.search(r'property="og:title" content="([^"]{5,120})"', html)
    if m:
        title = re.sub(r"^【楽天市場】", "", m.group(1)).strip()
    images = extract_images(html, url)

    res = judge(text)
    desc = extract_description(html)
    jan = extract_jan(html)
    if jan:
        desc = (desc + f" JAN: {jan}").strip()
    fee = extract_shipping_fee(text)
    total = ""
    if price.isdigit() and fee is not None:
        total = str(int(price) + fee)
    res.update({"url": url, "price_jpy": price, "title": title,
                "image_urls": images[:8], "description": desc, "jan": jan,
                "shipping_fee": fee, "total_jpy": total})
    return res
