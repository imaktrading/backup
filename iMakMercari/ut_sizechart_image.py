# -*- coding: utf-8 -*-
"""UT / GU の汎用サイズ表の画像の URL を返す (2026-09-14 / 2026-09-15 置き場を GitHub に変更)。

ユーザー「サイズ表は 1.png だけじゃなくて、UT なら v3 を入れた方がトラブルない」→
「目安だからね」(UT と GU を1枚にまとめる) →「そうしよか」(メンズ・ユニセックスのレギュラーだけ)。

- 画像: assets/tshirt_sizechart_ut_gu.png (カタログの実寸 メンズ・ユニセックスの中央値。袖丈だけ UT〜GU の幅)
- 使う条件は ut_catalog_values.chart_applies (実寸表が無い / メンズ・ユニセックス / レギュラー)
- 置く位置は 2枚目 (ユーザー「サイズ表は、２枚目がよくない？」)
- 失敗しても **出品は止めない** (空文字を返す = サイズ表の写真を付けないだけ)

★2026-09-15: 置き場を eBay の画像置き場 (UploadSiteHostedPictures) から **GitHub に変えた**。
  eBay は「eBay に置いた画像」と「外の URL の画像」を1出品に混ぜると弾く
  (Failure: A mixture of Self Hosted and EPS pictures are not allowed)。
  ほかの写真 (image.uniqlo.com / static.mercdn.net) は外の URL なので、サイズ表も外に置く。
  実害: 9/15 の🤖自動 17件中15件にこの画像が入り、1件目で弾かれて 0件出品。
  置き場は G-SHOCK の 999.png と同じ公開リポジトリ (imaktrading/imaktrading.github.io)。
  画像を描き直したら、同じ名前でそこにも上げ直す (中身が違えば付けない = 古い表を出さない)。
"""
from __future__ import annotations

import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CHART_PATH = os.path.join(HERE, "assets", "tshirt_sizechart_ut_gu.png")
CHART_URL = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/tshirt_sizechart_ut_gu.png"


def sha1_bytes(b):
    return hashlib.sha1(b or b"").hexdigest()


def fetch(url):
    """URL の画像の中身 (I/O)。画像として取れなければ None。"""
    import requests
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and (r.headers.get("Content-Type") or "").startswith("image/"):
            return r.content
    except Exception:                                              # noqa: BLE001
        pass
    return None


def ensure_chart_url(path=CHART_PATH, url=CHART_URL, log=print, fetch=fetch):
    """使える URL を返す。見られない / 手元の画像と中身が違う時は "" (出品は続ける)。"""
    try:
        with open(path, "rb") as f:
            local = sha1_bytes(f.read())
        remote = fetch(url)
        if remote is None:
            log(f"    ⚠ サイズ表の画像が見られない ({url}) → この回はサイズ表の写真を付けない")
            return ""
        if sha1_bytes(remote) != local:
            log("    ⚠ GitHub のサイズ表が手元の画像と違う (描き直した後に上げ直していない) "
                "→ この回はサイズ表の写真を付けない")
            return ""
        return url
    except Exception as e:                                         # noqa: BLE001
        log(f"    ⚠ サイズ表の画像の準備に失敗 ({type(e).__name__}: {e}) → サイズ表の写真を付けない")
        return ""


if __name__ == "__main__":
    print(ensure_chart_url() or "(用意できませんでした)")
