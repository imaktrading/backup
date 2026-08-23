"""rakuten_item - 楽天の商品ページから 即納判定 / 価格 / 画像を取る.

2026-08-19 新設。

★**在庫マーク (availability) は使えない**。 予約品も `InStock` を返す (実測21/21件)。
  予約品もカートに入るので当然で、 「買えるか」ではなく「いつ発送されるか」を見る必要がある。

★**即納判定は `deliveryMessage` (静的HTML) と 共有の条件表だけ**で決める
  (`C:/dev/iMak_data/shared/rakuten_delivery_rule.json` / 窓口 8ケース検算済み)。
  2026-08-22: ブラウザで描画後の「配送予定」欄を **自前の正規表現**で読む道が
  残っており、 HTTP が取れなかった時にそちらだけで即納と判定できてしまっていた
  (= 共有表を迂回する fail-OPEN)。 判定口を1つに寄せた
  (窓口 回答 `2026-08-19_inventory_rakuten_delivery_static_response`)。
  ブラウザは **送料の金額を読むためだけ** に使う (静的HTMLに金額が無い)。

判定は fail-closed。 読めなければ通さない。
"""
from __future__ import annotations

import re
import sys
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rakuten_delivery  # noqa: E402

DETAIL_WAIT_SEC = 8

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
    """ブラウザで商品ページを開いて 送料 + 価格 + 画像 + 即納判定を返す.

    即納判定は **静的HTMLの `deliveryMessage` を共有の条件表にかけた結果**。
    ブラウザが要るのは **送料の金額** (静的HTMLに無い) と画面テキストのため。
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

    # ★即納判定は **共有の条件表** だけ。 画面テキストの自前パターンは使わない
    #   (2026-08-22 窓口回答)。 予約品を即納と誤ると 無在庫でキャンセル -> BAN。
    msg = ""
    mm = _DELIVERY_MSG_RE.search(html)
    if mm:
        msg = mm.group(1)
    verdict = rakuten_delivery.judge_message(msg)
    res = {"in_stock_now": verdict == rakuten_delivery.IMMEDIATE,
           "shipping": msg if verdict == rakuten_delivery.IMMEDIATE else "",
           "reason": "ok" if verdict == rakuten_delivery.IMMEDIATE
                     else ("preorder" if verdict == rakuten_delivery.PREORDER
                           else "no_shipping_info"),
           "delivery_message": msg,
           "breadcrumb": [n for _c, n in parse_breadcrumb(html)],
           "is_gacha_category": is_gacha_category(html),
           "is_foodtoy_category": is_foodtoy_category(html),
           "is_collectable_category": is_collectable_category(html, url)}
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


# ---------------------------------------------------------------------------
# HTTP だけで取る (2026-08-22。 窓口 依頼 `gacha_next_steps`)
# ---------------------------------------------------------------------------
# `deliveryMessage` と `postageIncluded` は **静的HTMLに入っている**ので、
# 即納判定と「送料無料か」はブラウザ無しで分かる (実測 2026-08-22)。
# 1件6秒 -> 1秒未満。 ★送料の **金額** だけは静的HTMLに無いので、
# 送料無料でない物は 呼出側がブラウザで開き直す (`fetch_detail`)。
# パンくず (ld+json)。 **収集条件の片方** = 楽天のカテゴリが「ガチャガチャ」か
# (窓口 回答 `2026-08-19_gacha_implement_go_response`: パンくず「ガチャガチャ」+
#  タイトルに 全N種/コンプ の **両方**が立つ物だけ拾う)。
# 実測 2026-08-22 (40件): 楽天市場 > ホビー > コレクション > ガチャガチャ (id 553785)。
_BREADCRUMB_ITEM_RE = re.compile(
    r'"@id"\s*:\s*"https://www\.rakuten\.co\.jp/category/(\d+)/"\s*,\s*"name"\s*:\s*"([^"]+)"')
GACHA_CATEGORY_ID = "553785"
GACHA_CATEGORY_NAME = "ガチャガチャ"


def parse_breadcrumb(html: str) -> list[tuple[str, str]]:
    """商品ページの ld+json から [(カテゴリID, 名前), ...] を返す (純関数)."""
    return _BREADCRUMB_ITEM_RE.findall(html or "")


def is_gacha_category(html: str) -> bool:
    """パンくずが「ガチャガチャ」か。 **読めなければ False** (fail-closed)."""
    return any(cid == GACHA_CATEGORY_ID or name == GACHA_CATEGORY_NAME
               for cid, name in parse_breadcrumb(html))


# 食玩・おまけ (id 406810)。 **auc-toysanta だけ** ここも通す
# (窓口 回答 2026-08-22 `hq_gacha_foodtoy_column_response`)。
# ★このパンくずは「食玩かどうかの印にはならない」(窓口も了承済)。 菓子と無関係の
#   チャームが同じ区分に入る。 食玩かどうかは 商品説明の `■分類：` で決める。
FOODTOY_CATEGORY_ID = "406810"
FOODTOY_CATEGORY_NAME = "食玩・おまけ"
FOODTOY_SHOPS = ("auc-toysanta",)

_SHOP_RE = re.compile(r"item\.rakuten\.co\.jp/([a-z0-9_-]+)/", re.IGNORECASE)


def shop_of_url(url: str) -> str:
    """楽天の商品URLから 店ID を返す (取れなければ空)."""
    m = _SHOP_RE.search(url or "")
    return m.group(1) if m else ""


def is_foodtoy_category(html: str) -> bool:
    """パンくずが「食玩・おまけ」か。 **読めなければ False** (fail-closed)."""
    return any(cid == FOODTOY_CATEGORY_ID or name == FOODTOY_CATEGORY_NAME
               for cid, name in parse_breadcrumb(html))


def is_collectable_category(html: str, url: str = "") -> bool:
    """パンくずで拾ってよい商品か。

    「ガチャガチャ」は全店。 「食玩・おまけ」は `FOODTOY_SHOPS` の店だけ。
    どちらでもない (フィギュア等) / 読めない → False (fail-closed)。
    """
    if is_gacha_category(html):
        return True
    return (shop_of_url(url) in FOODTOY_SHOPS) and is_foodtoy_category(html)


# ---------------------------------------------------------------------------
# 食玩かどうか = 商品説明の `■分類：` (2026-08-23。 窓口 回答 `..._foodtoy_column_response`)
# ---------------------------------------------------------------------------
# 中間スプシ S列 に書く値。 出品くん (`gacha_to_csv.py` FOOD_TOY_COL=18) が読む:
#   空欄 → 通常のカプセルトイ / `食玩` → 食玩 / それ以外 → 出さない (fail-closed)
FOOD_TOY_MARK = "食玩"
# `■分類：` の値 → S列に書く値。 **ここに無い値の行は採らない**
CLASS_TO_COLUMN = {"ガチャガチャ": "", "食玩": FOOD_TOY_MARK}
# `■分類：` を必ず書いている店。 この店で欄が無い行は採らない (fail-closed)。
# ★他店は欄そのものが無い (実測 2026-08-23 の debug dump: auc-toysanta 178/178件が
#   欄あり、 auc-yuyou/mirakikaku/jugem2020/smltrading/kidsroom は 641/641件が欄なし)。
#   よって「欄が無い = 採らない」を全店に効かせると 他4店が全滅する。 欄を書く店にだけ効かせる。
CLASS_REQUIRED_SHOPS = ("auc-toysanta",)

_CLASS_RE = re.compile(r"■\s*分類\s*[：:]\s*(\S+)")


def parse_item_class(description: str) -> str:
    """商品説明の `■分類：` の値を返す (無ければ空)."""
    m = _CLASS_RE.search(description or "")
    return m.group(1) if m else ""


def classify_food_toy(description: str, url: str = "") -> tuple[bool, str, str]:
    """(採るか, S列に書く値, 理由) を返す (純関数).

    `■分類：ガチャガチャ` → 空欄 / `■分類：食玩` → `食玩` /
    それ以外の値 → 採らない / 欄が無い → `CLASS_REQUIRED_SHOPS` の店なら採らない。
    """
    raw = parse_item_class(description)
    if not raw:
        if shop_of_url(url) in CLASS_REQUIRED_SHOPS:
            return False, "", "class_missing"
        return True, "", "ok"
    if raw not in CLASS_TO_COLUMN:
        return False, "", "class_ng"
    return True, CLASS_TO_COLUMN[raw], "ok"


_DELIVERY_MSG_RE = re.compile(r'"deliveryMessage"\s*:\s*"([^"]*)"')
_POSTAGE_INC_RE = re.compile(r'"shipping":\{"postageIncluded":(true|false)')
_PRICE_RE = re.compile(r'itemprop="price"[^>]*content="([0-9]+)"')
_OG_TITLE_RE = re.compile(r'property="og:title" content="([^"]{5,200})"')


def parse_detail_html(html: str, url: str) -> dict:
    """商品ページの HTML から 判定に要る物を取り出す (純関数).

    Returns: {delivery_message, postage_included, price_jpy, title,
              image_urls, description, jan, breadcrumb, is_gacha_category,
              is_foodtoy_category, is_collectable_category, item_class}
    """
    m = _DELIVERY_MSG_RE.search(html or "")
    inc = _POSTAGE_INC_RE.search(html or "")
    price = _PRICE_RE.search(html or "")
    title = _OG_TITLE_RE.search(html or "")
    desc = extract_description(html)
    jan = extract_jan(html)
    if jan:
        desc = (desc + f" JAN: {jan}").strip()
    return {
        "url": url,
        "delivery_message": m.group(1) if m else "",
        "postage_included": (inc.group(1) == "true") if inc else None,
        "price_jpy": price.group(1) if price else "",
        "title": re.sub(r"^【楽天市場】", "", title.group(1)).strip() if title else "",
        "image_urls": extract_images(html, url),
        "description": desc,
        "jan": jan,
        "breadcrumb": [name for _cid, name in parse_breadcrumb(html)],
        "is_gacha_category": is_gacha_category(html),
        "is_foodtoy_category": is_foodtoy_category(html),
        "is_collectable_category": is_collectable_category(html, url),
        "item_class": parse_item_class(desc),
    }
