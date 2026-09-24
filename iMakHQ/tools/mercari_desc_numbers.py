#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番号がタイトルに無いメルカリ候補の **商品説明** を読み、書いてあるカード番号を台帳に貯める (2026-09-24)。

★ユーザー (2026-09-24):「商品説明に書いている場合もあるけどな」→「そだね」。
  同じ名前のカードが複数の番号にある時、タイトルに番号の無い候補は出さないことにした
  (ジンベエ / ミュウツーEX / ヒビキのホウオウex で3件続けて全部別の版だった)。
  ただし商品説明に番号を書く出品者もいるので、夜のうちに読んでおき、画面を作る時に使う:
    同じ番号がある → 「説明に番号あり」として出す / 別の番号しか無い → 外す / 無い → 出さない

台帳 (URL ごとに、説明に書いてあった番号。どのカードの候補かに依らないので、どの画面でも使える):
    C:/dev/iMak_data/hq/mercari_desc_numbers.json
    {url: {"codes": [["OP11","021"], ...], "fracs": [["020","063"], ...], "at": "2026-09-24"}}

    python mercari_desc_numbers.py              # 夜間 (既定 200件まで)
    python mercari_desc_numbers.py --limit=20
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                     # 後片付けで uc が quit を2回呼び「ハンドルが無効」を出す (結果には無害)
    import undetected_chromedriver as _uc
    _uc.Chrome.__del__ = lambda self: None
except Exception:                        # noqa: BLE001
    pass

LEDGER = r"C:/dev/iMak_data/hq/mercari_desc_numbers.json"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_research_cache.json")
RECHECK_DAYS = 30
# 削除済み・ページが無い (2026-09-24 実測: 読めなかった分のほとんどがこれ。記録しないと毎晩読み直す)
_GONE_WORDS = ("該当する商品は削除されています", "ページが見つかりませんでした")

_CODE = re.compile(r"(?<![A-Z0-9])([A-Z]{1,4}\d{0,3}[A-Z]?)\s*[-‐－]\s*(\d{3})(?!\d)")
_FRAC = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*(\d{2,3})(?!\d)")


def norm_url(u):
    return str(u or "").split("?")[0].split("#")[0].strip().rstrip("/")


def extract_numbers(text):
    """説明文 → {"codes": [[SET, NNN]], "fracs": [[NNN, MMM]]} (純関数)。"""
    t = unicodedata.normalize("NFKC", text or "").upper()
    codes = sorted({(m.group(1), m.group(2)) for m in _CODE.finditer(t)
                    if not m.group(1).startswith("PSA")})
    fracs = sorted({(m.group(1).zfill(3), m.group(2).zfill(3)) for m in _FRAC.finditer(t)})
    return {"codes": [list(x) for x in codes], "fracs": [list(x) for x in fracs]}


def verdict(entry, card_no):
    """台帳の1件と対象の番号 → 'same' / 'other' / '' (判らない) (純関数)。

    対象 'OP11-021' / 'SV9A-020' → 型番 (OP11,021) が一致 or 分数の番号 (020/xxx) が一致なら same。
    番号が書いてあり、どれも一致しなければ other。両方ある (一致も別もある) 時は '' (決めない)。
    """
    if not entry or not card_no:
        return ""
    c = unicodedata.normalize("NFKC", card_no).upper().split("/")[0]
    m = _CODE.search(c)
    my_set, my_no = (m.group(1), m.group(2)) if m else ("", (re.findall(r"\d+", c) or [""])[-1].zfill(3))
    if not my_no.strip("0") and not my_set:
        return ""
    same = other = False
    for s_, n_ in entry.get("codes") or []:
        if my_set and s_ == my_set and n_ == my_no:
            same = True
        else:
            other = True
    for n_, _tot in entry.get("fracs") or []:
        if n_ == my_no:
            same = True
        else:
            other = True
    if same and not other:
        return "same"
    if other and not same:
        return "other"
    return ""


def load(path=LEDGER):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(data, path=LEDGER):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def urls_to_check(cache, ledger, today=None):
    """補URL の検索結果に残っている **番号未確認の候補** のうち、まだ読んでいない URL (純関数)。"""
    today = today or dt.date.today()
    out, seen = [], set()
    for e in (cache or {}).values():
        m = (e or {}).get("mercari") or {}
        for t in m.get("loose_cands") or []:
            u = norm_url(t[1] if len(t) > 1 else "")
            if not u or u in seen or "mercari.com" not in u:
                continue
            seen.add(u)
            at = (ledger.get(u) or {}).get("at") or ""
            try:
                fresh = (today - dt.date.fromisoformat(at)).days < RECHECK_DAYS
            except ValueError:
                fresh = False
            if not fresh:
                out.append(u)
    return out


def run(limit=200):
    import undetected_chromedriver as uc
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError) as e:
        print(f"検索結果を読めませんでした: {e}")
        return 1
    ledger = load()
    todo = urls_to_check(cache, ledger)
    print(f"番号未確認の候補 {len(todo)}件 (今回 {min(len(todo), limit)}件を読む)")
    if not todo:
        return 0
    _quiet_chromedriver()
    o = uc.ChromeOptions()
    for a in ("--headless=new", "--lang=ja-JP", "--window-size=1280,1400"):   # ログインしない
        o.add_argument(a)
    maj = _chrome_major()
    d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    n = found = 0
    try:
        for u in todo[:limit]:
            try:
                d.get(u)
                text, gone, seen_el = "", False, False
                for _ in range(10):
                    time.sleep(1.5)
                    body = d.find_element("tag name", "body").text
                    if any(w in body for w in _GONE_WORDS):
                        gone = True
                        break
                    els = d.find_elements("css selector", '[data-testid="description"]')
                    if els:
                        seen_el = True
                        text = els[0].text
                        if text.strip():
                            break
            except Exception as e:                             # noqa: BLE001
                print(f"  ⚠ 読めませんでした {u}: {str(e)[:60]}")
                continue
            if gone:
                ledger[u] = {"codes": [], "fracs": [], "gone": True, "at": dt.date.today().isoformat()}
                n += 1
                continue
            if not seen_el:
                continue                                       # 読めなかった分は台帳に書かない (次の夜にまた読む)
            ent = extract_numbers(text)
            ent["at"] = dt.date.today().isoformat()
            ledger[u] = ent
            n += 1
            found += 1 if (ent["codes"] or ent["fracs"]) else 0
            if n % 20 == 0:
                _save(ledger)                                  # 落ちても読んだ分は残す
    finally:
        try:
            d.quit()
        except Exception:                                      # noqa: BLE001
            pass
        _save(ledger)
    print(f"読んだ {n}件 / 説明に番号が書いてあった {found}件")
    return 0


if __name__ == "__main__":
    lim = next((int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--limit=")), 200)
    sys.exit(run(lim))
