#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入稿CSV の画像と、今 eBay に出ている画像を突き合わせる (残務 №221 / 依頼 2026-09-27)。

使い方:
    python iMakHQ/tools/tshirt_pic_parity.py iMakHQ/csv_output/tshirt_upload_YYYYMMDD_HHMMSS.csv

★入稿した直後に走らせるのが肝。後から走らせると、価格やタイトルの改訂・人の手直しが
  混ざって「出品時にズレたのか、後で変わったのか」が切り分けられない (2026-09-14/15 の
  24件で実際に切り分けられなかった)。

出すもの: 枚数の差 / 1枚目が同じか / CSV にあって eBay に無い画像
画像は eBay が作り直す (白で正方形に埋める・圧縮し直す・切り方を変える) ので、
完全一致では比べられない。白い余白を落としてから見比べ、差が大きい物だけを挙げる。
"""
import csv
import hashlib
import io
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI"),
                os.path.dirname(__file__)]

import requests                                    # noqa: E402
from PIL import Image, ImageChops                  # noqa: E402

import ebay_getitem_images as _g                   # noqa: E402
import sheet_io as _si                             # noqa: E402

SAME = 25        # これ以下なら同じ写真 (256bit 中)
CROP = 90        # これ以下なら「同じ写真の切り方ちがい」の疑い
_CACHE = os.path.join(os.environ.get("TEMP", "."), "tshirt_pic_parity")


def _fetch(url):
    os.makedirs(_CACHE, exist_ok=True)
    p = os.path.join(_CACHE, hashlib.md5(url.encode()).hexdigest())
    if os.path.exists(p):
        return open(p, "rb").read()
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception:                               # noqa: BLE001
        return None
    open(p, "wb").write(r.content)
    return r.content


def trim_white(im):
    """白い余白を落とす (eBay は正方形に白で埋めるため、そのままでは比べられない)。"""
    im = im.convert("L")
    bbox = ImageChops.difference(im, Image.new("L", im.size, 255)) \
        .point(lambda p: 255 if p > 12 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def ahash(data):
    """白余白を落として 16x16 の明暗 256bit にする (純関数, test可)。"""
    if not data:
        return None
    px = list(trim_white(Image.open(io.BytesIO(data))).resize((16, 16)).tobytes())
    avg = sum(px) / len(px)
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v > avg else 0)
    return bits


def diff(a, b):
    return 999 if a is None or b is None else bin(a ^ b).count("1")


def nearest(h, pool):
    return min((diff(h, p) for p in pool if p is not None), default=999)


def compare(csv_hashes, ebay_hashes):
    """CSV と eBay の画像ハッシュ列 → 判定 (純関数, test可)。"""
    first = diff(csv_hashes[0] if csv_hashes else None,
                 ebay_hashes[0] if ebay_hashes else None)
    return {
        "n_csv": len(csv_hashes), "n_ebay": len(ebay_hashes),
        "first": ("同じ" if first <= SAME else
                  "切り方ちがいの疑い" if first <= CROP else "★別の写真"),
        "lost": [i for i, h in enumerate(csv_hashes) if nearest(h, ebay_hashes) > CROP],
    }


def sku_to_itemid(skus):
    """CustomLabel (仕入元の番号) → itemID を商品管理シートから引く。"""
    rows = _si._product_ws().get_all_values()
    out = {}
    for row in rows:
        joined = "\t".join(row)
        for sku in skus:
            if sku in joined and sku not in out:
                iid = next((c for c in row[:12] if c.isdigit() and len(c) >= 9), "")
                if iid:
                    out[sku] = iid
    return out


def main(path):
    pics = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r.get("CustomLabel"):
            pics[r["CustomLabel"]] = (r.get("PicURL") or "").split("|")
    ids = sku_to_itemid(list(pics))
    ng = 0
    for sku, urls in pics.items():
        iid = ids.get(sku)
        if not iid:
            print(f"{sku} itemID がシートに無い (まだ出品されていない?)")
            continue
        res = compare([ahash(_fetch(u)) for u in urls],
                      [ahash(_fetch(u)) for u in _g.fetch_listing_images(iid)])
        bad = res["first"] != "同じ" or res["n_csv"] != res["n_ebay"] or res["lost"]
        ng += 1 if bad else 0
        print(f"{'★' if bad else '  '}{sku} {iid} CSV={res['n_csv']} eBay={res['n_ebay']} "
              f"1枚目={res['first']} eBayに無い={res['lost']}")
    print(f"\n合わない出品 {ng} / {len(pics)} 件")
    return 1 if ng else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
