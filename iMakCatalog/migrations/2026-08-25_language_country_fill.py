"""specs.language / country_of_origin_ebay の空欄 2,859行を埋める.

## なぜ埋めてよいか (推測ではない)

値が入っている 86,280行は **例外なく `Japanese` / `Japan`** で、
`language` 列 (both / en / ja / None) とは無関係。実物が日本語版の刷りだから。

    one_piece の実測: (both,Japanese) 2783 / (None,Japanese) 2443 /
                      (en,Japanese) 1706 / (ja,Japanese) 1698

= `language` 列は「バンダイのどの言語データから取ったか」で、
  `specs.language` は「現物が何語で刷られているか」。当社が扱うのは日本語版だけ。

空欄 2,859行は Card Size と同じ行で、単に埋め損ね (出所: dbfw_official 1552 /
pokemon_card_jp 675 / gundam_official 系 323 ほか)。

## やらないこと

**遊戯王は触らない。** 英語刷りのみで `language=English`、原産国は不明のまま空欄が正。

英語版の刷りを扱い始めたら、この定数は成り立たない。その時は行ごとに持たせる。

実行:
  python migrations/2026-08-25_language_country_fill.py           # dry-run
  python migrations/2026-08-25_language_country_fill.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
# ★遊戯王は対象外。英語刷りだけのカテゴリで `language=English` 50,098行、
#   country_of_origin は空 (英語版の原産国は日本とは限らない)。当社は遊戯王を出していない。
CATS = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg")


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    # 前提確認: 既存値が Japanese / Japan 以外なら止める
    for key, want in (("language", "Japanese"), ("country_of_origin_ebay", "Japan")):
        vals = {v for (v,) in db.execute(
            f"SELECT DISTINCT json_extract(specs,'$.{key}') FROM products "
            f"WHERE category IN ({','.join('?' * len(CATS))}) "
            f"AND coalesce(json_extract(specs,'$.{key}'),'')<>''", CATS)}
        if vals - {want}:
            print(f"✗ {key} に {vals - {want}} が在る → 中止 (定数の前提が崩れている)")
            db.close()
            return

    per, updates = Counter(), []
    for r in db.execute(
            f"SELECT id, category, specs FROM products "
            f"WHERE category IN ({','.join('?' * len(CATS))})", CATS).fetchall():
        s = json.loads(r["specs"] or "{}")
        changed = False
        if not (s.get("language") or ""):
            s["language"] = "Japanese"; changed = True
        if not (s.get("country_of_origin_ebay") or ""):
            s["country_of_origin_ebay"] = "Japan"; changed = True
        if not changed:
            continue
        s["language_source"] = "constant_fill_20260825"
        per[r["category"]] += 1
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== language / country_of_origin の穴埋め (%s) ==="
          % ("APPLY" if commit else "DRY-RUN"))
    for k, v in per.most_common():
        print(f"   {k:16s} {v}")
    print(f"   合計 {len(updates)} 行")
    if commit:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
