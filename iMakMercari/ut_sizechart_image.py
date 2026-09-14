# -*- coding: utf-8 -*-
"""UT / GU の汎用サイズ表の画像を eBay の画像置き場に置き、その URL を返す (2026-09-14)。

ユーザー「サイズ表は 1.png だけじゃなくて、UT なら v3 を入れた方がトラブルない」→
「目安だからね」(UT と GU を1枚にまとめる) →「そうしよか」(メンズ・ユニセックスのレギュラーだけ)。

- 画像: assets/tshirt_sizechart_ut_gu.png (カタログの実寸 メンズ・ユニセックスの中央値。袖丈だけ UT〜GU の幅)
- 使う条件は ut_catalog_values.chart_applies (実寸表が無い / メンズ・ユニセックス / レギュラー)
- 置く位置は 2枚目 (ユーザー「サイズ表は、２枚目がよくない？」)
- 出品写真はインターネット上の URL が要る。1回アップロード (UploadSiteHostedPictures) した URL を
  保存して使い回す。画像ファイルが変わった時・URL が見られなくなった時だけ上げ直す
- 失敗しても **出品は止めない** (空文字を返す = サイズ表の写真を付けないだけ)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHART_PATH = os.path.join(HERE, "assets", "tshirt_sizechart_ut_gu.png")
CACHE_PATH = r"C:\dev\iMak_data\hq\ut_sizechart_eps.json"
EP = "https://api.ebay.com/ws/api.dll"


def file_sha1(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def upload_request_xml(name):
    """UploadSiteHostedPictures の XML 部分 (純関数)。"""
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<PictureName>{name}</PictureName>"
            "<PictureSet>Supersize</PictureSet>"
            "</UploadSiteHostedPicturesRequest>")


def parse_full_url(xml):
    """応答 → FullURL。取れなければ "" (純関数)。"""
    if "<Ack>Success</Ack>" not in (xml or "") and "<Ack>Warning</Ack>" not in (xml or ""):
        return ""
    m = re.search(r"<FullURL>(.*?)</FullURL>", xml or "")
    return m.group(1).strip() if m else ""


def cached_url(cache, sha1):
    """保存済みの URL が今の画像のものなら返す (純関数)。"""
    if isinstance(cache, dict) and cache.get("sha1") == sha1 and (cache.get("url") or "").startswith("https://"):
        return cache["url"]
    return ""


def _token():
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    return fx.token()


def upload(path=CHART_PATH, tok=None):
    """画像を eBay の画像置き場に上げて FullURL を返す (I/O)。失敗は ""。"""
    import requests
    tok = tok or _token()
    hdr = {"X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": "1271", "X-EBAY-API-IAF-TOKEN": tok}
    with open(path, "rb") as f:
        files = {"XML Payload": (None, upload_request_xml("imak_tshirt_sizechart"), "text/xml"),
                 "image": (os.path.basename(path), f.read(), "image/png")}
    r = requests.post(EP, headers=hdr, files=files, timeout=120)
    return parse_full_url(r.text)


def url_alive(url):
    """URL が画像として見られるか (I/O)。"""
    import requests
    try:
        r = requests.get(url, timeout=30)
        return r.status_code == 200 and (r.headers.get("Content-Type") or "").startswith("image/")
    except Exception:                                              # noqa: BLE001
        return False


def ensure_chart_url(path=CHART_PATH, cache_path=CACHE_PATH, log=print):
    """使える URL を返す。無ければ上げる。どこで失敗しても "" を返して出品は続ける。"""
    try:
        sha1 = file_sha1(path)
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        url = cached_url(cache, sha1)
        if url and url_alive(url):
            return url
        url = upload(path)
        if not url or not url_alive(url):
            log("    ⚠ サイズ表の画像を eBay に置けなかった → この回はサイズ表の写真を付けない")
            return ""
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "sha1": sha1, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False)
        log(f"    🖼 サイズ表の画像を eBay に置いた: {url}")
        return url
    except Exception as e:                                         # noqa: BLE001
        log(f"    ⚠ サイズ表の画像の準備に失敗 ({type(e).__name__}: {e}) → サイズ表の写真を付けない")
        return ""


if __name__ == "__main__":
    print(ensure_chart_url() or "(用意できませんでした)")
