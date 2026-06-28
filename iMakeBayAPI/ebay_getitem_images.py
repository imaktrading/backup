#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eBay Trading API GetItem で既存listingの画像URL(PictureURL)を取得。

取下再出品②の「画像現状流用」用。relist は End+新Add なので、新listingの PicURL に
**元listingの eBay-hosted 画像(i.ebayimg.com EPS URL)** を渡して画像を引き継ぐ。
(元の old_item_id は ended 後も暫く GetItem で画像取得可能 = eBay が ~90日保持)。

999.png ダミーは *新規出品* (仕入前で画像なし) の正規設計だが、relist は元画像が在るので
それを流用する (2026-06-06 G-shock relist で画像消失が発覚し新設)。
"""
import os
import re
import time

import requests

_KEYS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ebay keys.txt")
_ENDPOINT = "https://api.ebay.com/ws/api.dll"
_COMPAT = "967"


def _load_keys():
    k = {}
    with open(_KEYS_PATH, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                a, b = line.split("=", 1)
                k[a.strip()] = b.strip()
    return k


def fetch_listing_images(item_id, _cache={}):
    """item_id の listing の PictureURL を順序保持で返す (失敗時は空list)。

    ended listing でも暫くは取得可。同一 item_id は cache (1実行内の重複呼出抑制)。
    """
    item_id = str(item_id).strip()
    if not item_id:
        return []
    if item_id in _cache:
        return _cache[item_id]
    try:
        k = _load_keys()
        hdr = {
            "X-EBAY-API-CALL-NAME": "GetItem",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": _COMPAT,
            "X-EBAY-API-APP-NAME": k["AppID"],
            "X-EBAY-API-DEV-NAME": k["DevID"],
            "X-EBAY-API-CERT-NAME": k["AppSecret"],
            "Content-Type": "text/xml",
        }
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
        )
        # DNS瞬断/接続エラーは数回リトライ(無いと画像が虫食いで欠落する。2026-06-17)。
        # 成功 or リトライ尽きるまで _cache に [] を入れない(失敗を確定キャッシュしない)。
        r = None
        for attempt in range(4):
            try:
                r = requests.post(_ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30)
                break
            except requests.exceptions.ConnectionError:
                if attempt < 3:
                    time.sleep(3)
                    continue
                raise
        # PictureDetails 内の PictureURL を順序保持で抽出
        pics = re.findall(r"<PictureURL>(.*?)</PictureURL>", r.text)
        # 重複除去 (順序保持)
        seen, out = set(), []
        for p in pics:
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        _cache[item_id] = out
        return out
    except Exception:
        return []


def build_pic_url(images, extra, relist_mode, cap=24):
    """eBay PicURL 文字列を組む (純関数, test可)。

    relist時は画像が eBay EPS(i.ebayimg.com)なので、自前ホストの extra(999.png/banner)を
    混ぜると "mixture of Self Hosted and EPS pictures" で eBay が拒否 → relist は extra 無し。
    通常出品は従来通り extra を末尾連結(上限 cap=24)。
    """
    extra = [] if relist_mode else list(extra or [])
    pics = list(images)[:cap - len(extra)] + extra
    return "|".join(pics)


def fetch_listing_condition(item_id):
    """item_id の listing の ConditionID(int)を返す。失敗/不明は None。

    取下再出品の condition 継承用: relist は既存listingの再出品なので condition は既知(元の
    ConditionID)。これを権威にすれば Claude の画像推定で New↔Used がブレて title marker 不一致
    HOLD になるのを根治できる(2026-06-28 New品relist が Pre-owned 誤推定で HOLD→native Relist
    回避策が③非互換を生んだ。設計修正=元condition継承で Add 一本化)。
    """
    item_id = str(item_id).strip()
    if not item_id:
        return None
    try:
        k = _load_keys()
        hdr = {
            "X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": _COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
            "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"],
            "Content-Type": "text/xml",
        }
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
        )
        text = None
        for attempt in range(4):
            try:
                text = requests.post(_ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
                break
            except requests.exceptions.ConnectionError:
                if attempt < 3:
                    time.sleep(3)
                    continue
                raise
        m = re.search(r"<ConditionID>(\d+)</ConditionID>", text)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def img_media_type(data):
    """画像バイト先頭(マジックバイト)から media_type を判定 (純関数, test可)。

    Claude API は media_type と実体の不一致で 400 を返す。eBay画像(i.ebayimg.com)は .JPG/.PNG
    混在で URL拡張子も実体と食い違うため**バイトで判定**する(2026-06-28 relist画像流用で
    PNG混入が jpeg 固定指定により Claude 400 全失敗したのを根治)。Claude 対応4形式 + 既定 jpeg。
    """
    if data[:8].startswith(b"\x89PNG"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def relist_photo_source(relist_mode, item_id, source_urls, fetch_fn=None):
    """取下再出品②の画像ソース選択 (純関数, test可)。

    relist 時は **取下げた元eBay listing の画像をそのまま流用**(ユーザー方針
    「リスティング中の画像を流用するだけ」2026-06-28)。ソース(mercari/1kuji.com)から
    取り直さない=1kuji.com 汎用OG画像混入・画像取得失敗での行スキップを根治。
    eBay画像が0(ended >90日 / API失敗)の時のみ source に fallback(画像消失で誤出品しないため)。
    戻り: (photo_urls_str, note)。note は print 用(空=非relist)。
    """
    if not relist_mode:
        return source_urls, ""
    fn = fetch_fn or fetch_listing_images
    try:
        pics = fn(item_id)
    except Exception:
        pics = []
    if pics:
        return "|".join(pics), f"relist: 元eBay listing({item_id})の画像 {len(pics)}枚を流用"
    return source_urls, f"relist: 元eBay画像0(itemID={item_id}) → ソース画像で続行"


def fetch_listing_qty(item_id):
    """item_id の listing の **販売可能数(Quantity - QuantitySold)** を返す。失敗/不明は None。

    RESTOCK後の状態同期に使う: revise(qty=1)が実反映されたか実状態で verify(fail-OPEN防止)。
    DNS/接続エラーはリトライ。
    """
    item_id = str(item_id).strip()
    if not item_id:
        return None
    try:
        k = _load_keys()
        hdr = {
            "X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": _COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
            "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"],
            "Content-Type": "text/xml",
        }
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
        )
        text = None
        for attempt in range(4):
            try:
                text = requests.post(_ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
                break
            except requests.exceptions.ConnectionError:
                if attempt < 3:
                    time.sleep(3)
                    continue
                raise

        def _g(tag):
            m = re.search(rf"<{tag}>(\d+)</{tag}>", text)
            return int(m.group(1)) if m else None
        q, qs = _g("Quantity"), _g("QuantitySold")
        if q is None:
            return None
        return q - (qs or 0)
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    for iid in sys.argv[1:]:
        urls = fetch_listing_images(iid)
        print(f"{iid}: {len(urls)} pics / avail_qty={fetch_listing_qty(iid)}")
        for u in urls:
            print("  ", u)
