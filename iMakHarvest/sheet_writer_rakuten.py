"""sheet_writer_rakuten - 楽天ガチャポン収集を中間スプシの `rakuten_<label>` タブに append.

2026-08-19 新設。 `sheet_writer_mercari_search.py` の楽天版。 差分は 2つ:
  - dedupe key: 楽天は `<shop>/<商品コード>` が一意 (URL の形は変わらない)
  - 列: **HQ 回答 (2026-08-19) に合わせる**

| 列 | 中身 |
|---|---|
| A | 楽天の商品URL |
| C | 日本語タイトル |
| E | `新品` |
| F | **仕入原価 = 商品価格 + 送料** (数値のみ) |
| G | 写真URL |
| H | 商品説明 (無ければ空) |
| I | **公式URL** (商品ページ優先 / 無ければメーカー公式サイト) |
| W | 公式の商品画像URL (`|` 区切り。 無ければ空) |
| M | **仕入原価 = 商品価格 + 送料** (数値のみ) |
| R | `カプセルトイ` |
| S | **食玩** (お菓子付き) の行だけ `食玩`。 通常は空欄 |

★**N (仕入れ価格) と P (CTR) には書かない**。 本番 HIGH ではどちらも数式で、
値を貼ると列全体が壊れる (N は ARRAYFORMULA の spill、 P は countif)。
仕入れ値を本番へ渡したい時は M列を使う。
"""
from __future__ import annotations

import re

import gspread

from gacha_maker import official_url
from sheet_writer_amazon import (
    COL_CATEGORY, COL_CONDITION, COL_DESCRIPTION, COL_IMAGES, COL_PRICE,
    COL_TITLE, COL_URL, DEFAULT_COLUMN_COUNT,
)

CATEGORY = "カプセルトイ"     # R列 (HQ 確認: 表記ゆれ禁止。 ガシャポン/ガチャガチャ は別扱い)
CONDITION = "新品"
# ★M列には **書かない** (2026-09-08 user 確定「仕入値は F のみ。他にあると HIGH が壊れる」)。
#   仕入原価は F列 (本体+送料) の1か所だけに置く。
COL_CURRENT_PRICE = 13        # M: 現在価格(円) - 監視くんが後で入れる列。 こちらは触らない
# ★公式URL は **I列** (2026-08-21 user 確定)。 HQ から「I は英語タイトル列なので
#   V に移してほしい」と依頼が来て一度移したが、 **I列は user が指定した場所**なので戻した。
#   入れる中身は 公式の **商品ページ** を優先し、 無ければメーカー公式サイト。
COL_OFFICIAL_PAGE = 9         # I: 公式URL (商品ページ優先。 推測URLは入れない)
COL_OFFICIAL_IMAGES = 23      # W: 公式の商品画像URL (`|` 区切り)
# S: 食玩の印 (2026-08-23 HQ 依頼 `2026-08-22_hq_gacha_foodtoy_column_response`)。
# 出品くん `gacha_to_csv.py` の `FOOD_TOY_COL = 18` (0起点) が読む列。
#   空欄 → 通常のカプセルトイ / `食玩` → 食玩 / それ以外 → 出品側で落とす (fail-closed)
COL_FOOD_TOY = 19

_ITEM_RE = re.compile(r"item\.rakuten\.co\.jp/([a-z0-9_-]+)/([a-z0-9_-]+)")


def dedupe_key(url: str) -> str:
    """楽天 URL から `<shop>/<商品コード>` を作る。 取れなければ正規化 URL."""
    if not url:
        return ""
    m = _ITEM_RE.search(url.strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return url.strip().split("?")[0].rstrip("/").lower()


_BOARD_RE = re.compile(r"\+?\s*ディスプレイ台紙")


def base_title_key(title: str) -> str:
    """同じ商品の「台紙あり/なし」を **同じ物** とみなすキー.

    2026-08-22: 同じ絵柄で2出品すると重複になるので片方だけ入れる (HQ 依頼)。
    店名 (`：<店名>`) と 台紙表記と空白を落として比べる。
    """
    t = (title or "").split("：")[0]
    t = _BOARD_RE.sub("", t)
    return re.sub(r"[\s　+＋]", "", t)


def has_board(title: str) -> bool:
    """「+ディスプレイ台紙セット」表記があるか."""
    return bool(_BOARD_RE.search(title or ""))


def load_base_titles(sh, prefix: str = "rakuten_") -> set:
    """既に入っている商品の base キーを全タブから集める."""
    keys: set = set()
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(prefix):
            continue
        try:
            rows = ws.get_all_values()
        except Exception:  # noqa: BLE001
            continue
        for row in rows[1:]:
            if len(row) >= COL_TITLE and row[COL_TITLE - 1].strip():
                keys.add(base_title_key(row[COL_TITLE - 1]))
    return keys


def shop_of(url: str) -> str:
    """楽天の商品URLから 店ID を返す (取れなければ空)."""
    m = _ITEM_RE.search(url or "")
    return m.group(1) if m else ""


def build_tab_name(label: str) -> str:
    safe = re.sub(r"[^\w]", "_", (label or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"rakuten_{safe}" if safe else "rakuten_unknown"


def build_row(item: dict, column_count: int = DEFAULT_COLUMN_COUNT) -> list:
    """1 行を組み立てる (純関数). N と P は空のまま."""
    row = [""] * column_count
    price = str(item.get("price_jpy") or "").replace(",", "").strip()
    # M列は **送料込みの総額**。 送料が読めなかった物はそもそも採らない (runner 側で落とす)
    total = str(item.get("total_jpy") or "").replace(",", "").strip() or price
    images = item.get("image_urls") or []
    image_str = images if isinstance(images, str) else "|".join(str(u) for u in images if u)

    row[COL_URL - 1] = (item.get("url") or "").strip()
    row[COL_TITLE - 1] = str(item.get("title") or "").strip()
    row[COL_CONDITION - 1] = CONDITION
    # ★F列は **送料込みの総額** (2026-09-05 user 確定「価格はF列に入れる」)。
    #   本体だけを入れると、 送料が乗る店 (トイサンタは約9割が有料) で仕入原価を誤る。
    #   内訳は H列に文章で残してある。
    row[COL_PRICE - 1] = total
    row[COL_IMAGES - 1] = image_str
    desc = str(item.get("description") or "")
    fee = item.get("shipping_fee")
    if fee is not None and price:
        desc = f"{desc} 仕入原価: 本体{price}円 + 送料{fee}円 = {total}円".strip()
    row[COL_DESCRIPTION - 1] = desc
    # I: 公式の商品ページ > メーカー公式サイト の順。 どちらも無ければ空
    row[COL_OFFICIAL_PAGE - 1] = (str(item.get("official_page") or "")
                                  or official_url(item.get("title") or "",
                                                  str(item.get("description") or "")))
    imgs = item.get("official_images") or []
    row[COL_OFFICIAL_IMAGES - 1] = (imgs if isinstance(imgs, str)
                                    else "|".join(str(u) for u in imgs if u))  # W
    # M列は空のまま (上のコメント参照)
    row[COL_CATEGORY - 1] = CATEGORY            # R
    # S: 食玩の印。 判定は収集側 (`rakuten_item.classify_food_toy`) で済ませてある。
    # ここでタイトルから当て直さない (「チョコ」等はキャラ名にも出る = 必ず誤判定する)
    row[COL_FOOD_TOY - 1] = str(item.get("food_toy") or "").strip()
    return row


def load_keys_all_tabs(sh, prefix: str = "rakuten_") -> set:
    """rakuten_* 全タブから dedupe key を集める (タブを分けても二重に入れない)."""
    keys: set = set()
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(prefix):
            continue
        try:
            rows = ws.get_all_values()
        except Exception:  # noqa: BLE001
            continue
        for row in rows[1:]:
            if len(row) >= COL_URL:
                k = dedupe_key((row[COL_URL - 1] or "").strip())
                if k:
                    keys.add(k)
    return keys


def append_items(items: list[dict], label: str = "gacha",
                 column_count: int = DEFAULT_COLUMN_COUNT,
                 known_keys: set | None = None) -> dict:
    """`rakuten_<label>` タブに append (商品コード dedup).

    known_keys を渡すと タブを読み直さない (走行中に何度も書く時、
    毎回全タブを読むと Google の読取上限に当たる)。
    """
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter, _create_from_template, _ensure_header,
        open_seller_staging_sheet,
    )

    tab_name = build_tab_name(label)
    if not items:
        return {"tab": tab_name, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    try:
        ws = sh.worksheet(tab_name)
        _ensure_header(ws, sh)
    except gspread.WorksheetNotFound:
        ws = _create_from_template(sh, tab_name)

    existing: set = set(known_keys) if known_keys is not None else load_keys_all_tabs(sh)

    new_rows, skipped, seen = [], 0, set()
    for it in items:
        key = dedupe_key(it.get("url") or "")
        if not key or key in existing or key in seen:
            skipped += 1
            continue
        seen.add(key)
        new_rows.append(build_row(it, column_count))

    if not new_rows:
        return {"tab": tab_name, "appended": 0, "skipped_existing": skipped,
                "input": len(items)}

    next_row = len(ws.get_all_values()) + 1
    end = next_row + len(new_rows) - 1
    ws.update(range_name=f"A{next_row}:{_col_to_letter(column_count)}{end}",
              values=new_rows, value_input_option="USER_ENTERED")
    if known_keys is not None:
        known_keys.update(seen)
    return {"tab": tab_name, "appended": len(new_rows),
            "skipped_existing": skipped, "input": len(items)}
