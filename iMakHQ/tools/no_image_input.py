# -*- coding: utf-8 -*-
"""NO-IMAGE (カタログに画像が無く目視できない) のカードを、カタログの入力 no_image_input.json に1件書く (2026-10-16)。

ブラボー B-20261016-009 / カタログ回答 catalog/requests/2026-10-16_no_image_input_go_response.md:
- キー "<category>:<product_id>" → {cert, image_url (PSA の写真・cloudfront), psa_subject, at}。同じ product_id は上書き
- カタログが毎時に写真を落とし、窓で目視して入れる。**新しく書いた時だけ** ブラボーに呼び鈴 (ミラーの行と違いここは鳴らす)
- 依頼書は書かない (同じ物を依頼書で何度も出していた: CLF-007/016 が10日連続)
"""
from __future__ import annotations

import datetime as dt
import json
import os

INPUT_PATH = r"C:/dev/iMak_data/catalog/requests/no_image_input.json"
PSA_CERTS_DIR = r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs"


def psa_photo_url(cert):
    """PSA の写真 (大きい方) の URL。キャッシュに無ければ ""。"""
    try:
        with open(os.path.join(PSA_CERTS_DIR, f"{cert}.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    u = d.get("CardImageUrl") or ""
    return u.replace("/small/", "/large/") if "cloudfront.net/cert/" in u else ""


def _subject(cert):
    try:
        with open(os.path.join(PSA_CERTS_DIR, f"{cert}.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("Subject") or ""
    except (OSError, ValueError):
        return ""


def add(category, product_id, cert, path=INPUT_PATH, now=None, image_url=None, subject=None):
    """1件書く。戻り: "new" (新しく書いた) / "same" (同じ cert で既にある) / "no_photo" (写真が無く書けない)。"""
    url = image_url if image_url is not None else psa_photo_url(cert)
    if not url:
        return "no_photo"
    key = f"{category}:{product_id}"
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f) or {}
    except (OSError, ValueError):
        cur = {}
    old = cur.get(key) or {}
    if str(old.get("cert")) == str(cert):
        return "same"
    cur[key] = {"cert": str(cert), "image_url": url,
                "psa_subject": subject if subject is not None else _subject(cert),
                "at": (now or dt.datetime.now()).isoformat(timespec="seconds")}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return "new"


def ring(n_new, frm="出品くん (no_image_input)"):
    """新しく書いた時だけブラボーに呼び鈴 (0件なら鳴らさない)。"""
    if n_new <= 0:
        return False
    try:
        import bell
        bell.notify_bg(frm, INPUT_PATH, f"NO-IMAGE の写真を {n_new}件 渡した (カタログの窓で目視して入れる)")
        return True
    except Exception:                                          # noqa: BLE001
        return False
