#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""credentials.py — eBay の鍵とトークンの置き場所を **1か所で決める**。

★なぜ要るか (2026-08-21 カタログからの依頼):
    eBay のトークンは使うたびに更新されて書き戻される。鍵が2か所にあると
    **片方だけ新しくなって、もう片方が腐る**。
    同じ日に「変換表が2か所にあって片方だけ直る」で1日つぶしたのと同じ形。

決まり:
    - 共有領域 `C:/dev/iMak_data/credentials/` を **本物**とする
    - 無ければ従来の場所 (このファイルの隣) を使う ← 移行期の保険
    - **両方あって中身が違えば警告を出す**。黙って古い方を使わない

使い方:
    from credentials import ebay_keys, keys_path, token_path
    keys = ebay_keys()          # {'AppID':…, 'AppSecret':…, …}
    p    = token_path("sell")   # Marketing API 用 / "trading" で Trading API 用

自己診断:
    python credentials.py
"""
from __future__ import annotations

import hashlib
import os
import sys

SHARED_DIR = r"C:/dev/iMak_data/credentials"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

KEYS_NAME = "ebay keys.txt"
TOKEN_NAMES = {"sell": "ebay_oauth_token_sell.json",
               "trading": "ebay_oauth_token.json"}

_WARNED = set()


# ── 純関数 (test 可) ────────────────────────────────────────────────
def pick(shared, local, exists, digest, warn=None):
    """共有 / 従来 のどちらを使うかを決める (純関数)。

    - 共有が在れば共有。**中身が違えば警告**して、それでも共有を使う
      (共有が本物。黙って古い方に落ちない)
    - 共有が無ければ従来 (移行期の保険)
    """
    has_s, has_l = exists(shared), exists(local)
    if has_s and has_l and digest(shared) != digest(local):
        if warn:
            warn("⚠️ 鍵が2か所にあって中身が違います。共有側を使います\n"
                 "   共有 : %s\n   従来 : %s\n"
                 "   → 従来側は消してください (片方だけ古いまま腐ります)"
                 % (shared, local))
    if has_s:
        return shared
    return local if has_l else shared      # どちらも無ければ共有を返す (エラーは呼側で)


def parse_keys(text):
    """`ebay keys.txt` の中身 → dict (純関数)。`AppID=xxx` 形式。"""
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ── 実際に触る側 ───────────────────────────────────────────────────
def _exists(p):
    return os.path.exists(p)


def _digest(p):
    try:
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:                                          # noqa: BLE001
        return ""


def _warn(msg):
    if msg in _WARNED:
        return
    _WARNED.add(msg)
    print(msg, file=sys.stderr, flush=True)


def keys_path():
    """`ebay keys.txt` の場所。"""
    return pick(os.path.join(SHARED_DIR, KEYS_NAME),
                os.path.join(LOCAL_DIR, KEYS_NAME), _exists, _digest, _warn)


def token_path(kind="sell"):
    """OAuth トークンの場所。kind = "sell" / "trading"。"""
    name = TOKEN_NAMES.get(kind)
    if not name:
        raise ValueError("kind は %s のどれか" % list(TOKEN_NAMES))
    return pick(os.path.join(SHARED_DIR, name),
                os.path.join(LOCAL_DIR, name), _exists, _digest, _warn)


def ebay_keys():
    """AppID / AppSecret 等を dict で返す。読めなければ例外 (推測しない)。"""
    p = keys_path()
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        keys = parse_keys(f.read())
    if not keys.get("AppID") or not keys.get("AppSecret"):
        raise RuntimeError("鍵が読めません: %s" % p)
    return keys


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    print("共有領域:", SHARED_DIR, "(在り)" if os.path.isdir(SHARED_DIR) else "(無し)")
    print("従来の場所:", LOCAL_DIR)
    print()
    for label, p in (("鍵", keys_path()),
                     ("トークン(sell)", token_path("sell")),
                     ("トークン(trading)", token_path("trading"))):
        where = "共有" if p.replace("\\", "/").startswith(SHARED_DIR) else "従来"
        print("  %-18s %s  [%s]%s" % (label, p, where,
                                      "" if os.path.exists(p) else "  ★ファイルが無い"))
    try:
        k = ebay_keys()
        print("\n  鍵の項目:", sorted(k))
    except Exception as e:                                     # noqa: BLE001
        print("\n  ★鍵を読めません:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
