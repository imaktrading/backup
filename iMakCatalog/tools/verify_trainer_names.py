# -*- coding: utf-8 -*-
"""ポケモンのトレーナー名 (日本語 → 英語) を Bulbapedia と突き合わせる (2026-09-11).

## なぜ要るか

HQ 依頼 `requests/2026-09-09_trainer_name_en_3way_wrong.md`: ボタン / ピーニャ / シュウメイ の
英語名が入れ替わっていた。元の表 `scrapers/pokemon_name_translation.TRAINER_NAME_MAP` を
見ると、同じ種類の誤りが他にもある (カエデ→Tulip は Katy、リップ→Tyme は Tulip 等)。
**1件ずつ直すのではなく、表と DB を全部 機械で突き合わせる。**

## 突き合わせ方 (推測しない)

    英語名のページの jname (Bulbapedia の日本語名) == 日本語名   → 正しい
    一致しない → Bulbapedia を日本語名で検索し、候補ページの jname が日本語名と
                **完全一致**したものだけを「正しい英語名」として出す。無ければ空欄 (要確認)

対象:
  - 元の表 `TRAINER_NAME_MAP` の全行
  - DB (pokemon_tcg) で **同じ name_en が 2つ以上の name_jp に付いている組** (入れ替わりの兆候)

出力: `C:/dev/iMak_data/catalog/trainer_name_check.json`
★DB は書き換えない (確認だけ)。直すのは migration で。

実行:
    python tools/verify_trainer_names.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
from pokemon_name_translation import TRAINER_NAME_MAP  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API = "https://bulbapedia.bulbagarden.net/w/api.php"
UA = {"User-Agent": "iMakCatalog name check (contact via repo owner)"}
OUT = Path("C:/dev/iMak_data/catalog/trainer_name_check.json")
PACE = 1.0
_JN: dict[str, str | None] = {}


def _api(params: dict) -> dict:
    u = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
                time.sleep(PACE)
                return json.loads(r.read())
        except Exception:
            time.sleep(5 * (i + 1))
    return {}


def jname(en: str) -> str | None:
    """英語名のページの日本語名 (infobox の jname)。ページが無ければ None."""
    if en in _JN:
        return _JN[en]
    wt = (_api({"action": "parse", "prop": "wikitext", "redirects": 1, "page": en})
          .get("parse", {}).get("wikitext", {}).get("*", ""))
    m = re.search(r"\|\s*jname\s*=\s*([^\n|}]+)", wt)
    _JN[en] = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None
    return _JN[en]


def correct_en(jp: str) -> str | None:
    """日本語名で検索し、jname が完全一致する (括弧なしの) ページ名だけを返す."""
    hits = (_api({"action": "query", "list": "search", "srlimit": 6, "srsearch": f'"{jp}"'})
            .get("query", {}).get("search", []))
    for h in hits:
        t = h["title"]
        if "(" in t:
            continue
        if jname(t) == jp:
            return t
    return None


def main() -> None:
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for jp, en in TRAINER_NAME_MAP.items():
        pairs[(jp, en)].add("表")
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    by_en: dict[str, set[str]] = defaultdict(set)
    for jp, en in db.execute("SELECT DISTINCT name_jp, name_en FROM products "
                             "WHERE category='pokemon_tcg' AND name_en <> '' AND name_jp <> ''"):
        by_en[en].add(jp)
    for en, jps in by_en.items():
        if len(jps) >= 2:
            for jp in jps:
                pairs[(jp, en)].add("DB重複")
    print(f"=== トレーナー名の突き合わせ — {len(pairs)}組 (表 {len(TRAINER_NAME_MAP)} / DB重複) ===",
          flush=True)
    out, bad = [], 0
    for i, ((jp, en), where) in enumerate(sorted(pairs.items()), 1):
        jn = jname(en)
        if jn == jp:
            verdict, fix = "ok", en
        elif jn is None:
            verdict, fix = "英語名のページが無い", correct_en(jp)
        else:
            verdict, fix = f"不一致 (Bulbapedia: {en}={jn})", correct_en(jp)
        if verdict != "ok":
            bad += 1
            print(f"    {jp:10s} {en:20s} -> {fix or '(要確認)'}   {verdict} [{'/'.join(sorted(where))}]",
                  flush=True)
        out.append({"jp": jp, "en": en, "where": sorted(where), "verdict": verdict,
                    "bulbapedia_en": fix})
        if i % 25 == 0:
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  合わない {bad}組 / 全 {len(out)}組 → {OUT}")


if __name__ == "__main__":
    main()
