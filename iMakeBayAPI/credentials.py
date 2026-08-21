#!/usr/bin/env python3
"""eBay の鍵とトークンの置き場を決める**唯一の口**.

2026-08-21 制定。ユーザー指示「共有側を本物にして、コードの参照先をそちらに切り替える」。

## なぜ1か所にするのか
切替前は 12ファイル / 16箇所が **それぞれ自前で** `../iMakeBayAPI/ebay keys.txt` を
組み立てていた。同じ値がコードの中に散らばっている状態で、参照先を変えるには
12箇所を直すことになる。**1つ直し忘れると、そこだけ古い鍵/トークンを使い続ける。**

トークンは使うたびに更新されて書き戻されるため、これは実害になる
(片方だけ新しくなり、もう片方が腐る)。変換表が2か所にあって片方だけ直った、
というのと同じ形 (2026-08-21 に同型の問題を1日かけて潰した)。

## 決め方
1. 共有領域 `C:/dev/iMak_data/credentials/` を**本物**とする
2. そこに無ければ、従来の `iMakeBayAPI/` 配下を使う (移行期の保険)
3. **両方に在って中身が違えば警告を出す** — 黙って古い方を使わない

実行:
    from credentials import ebay_keys, token_path
    keys = ebay_keys()                 # {'AppID': ..., 'AppSecret': ...}
    p    = token_path("sell")          # Path (Marketing API 用)

自己診断:
    python iMakeBayAPI/credentials.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

SHARED = Path("C:/dev/iMak_data/credentials")
LOCAL = Path(__file__).resolve().parent

KEYS_NAME = "ebay keys.txt"
TOKEN_NAMES = {
    "trading": "ebay_oauth_token.json",      # Trading API 用
    "sell": "ebay_oauth_token_sell.json",    # Marketing API 用
}


def _resolve(name: str) -> Path:
    """共有 → 本体 の順で解決し、両方在って中身が違えば警告する."""
    shared, local = SHARED / name, LOCAL / name
    if shared.exists() and local.exists():
        try:
            if shared.read_bytes() != local.read_bytes():
                warnings.warn(
                    f"[credentials] {name} が2か所に在り、中身が違います。共有側を使います。\n"
                    f"  共有(本物): {shared}\n"
                    f"  本体(古い): {local}\n"
                    f"  → 本体側を消すか、書き手を共有側だけに向けてください",
                    RuntimeWarning, stacklevel=3)
        except OSError:
            pass
        return shared
    if shared.exists():
        return shared
    if local.exists():
        return local
    raise FileNotFoundError(
        f"eBay の {name} が見つかりません。置き場: {shared} (または {local})")


def keys_path() -> Path:
    return _resolve(KEYS_NAME)


def token_path(kind: str = "sell") -> Path:
    if kind not in TOKEN_NAMES:
        raise ValueError(f"kind は {list(TOKEN_NAMES)} のどれか (受領: {kind!r})")
    return _resolve(TOKEN_NAMES[kind])


def ebay_keys() -> dict:
    """'ebay keys.txt' を dict にして返す (AppID / AppSecret / DevID / AuthToken)."""
    out = {}
    with keys_path().open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> int:
    print("=== eBay 資格情報の解決先 ===")
    ok = True
    for label, fn in (("keys", keys_path),
                      ("token(trading)", lambda: token_path("trading")),
                      ("token(sell)", lambda: token_path("sell"))):
        try:
            p = fn()
            where = "共有" if str(p).startswith(str(SHARED)) else "本体(要移行)"
            print(f"  {label:<16} {where:<10} {p}")
        except FileNotFoundError as e:
            ok = False
            print(f"  {label:<16} ✗ {e}")
    try:
        k = ebay_keys()
        print(f"  keys の項目: {sorted(k)}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  ✗ keys 読取失敗: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
