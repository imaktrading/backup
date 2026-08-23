"""ポケモンの進化段階を、保存済の公式HTML から取り直す (2,366行).

依頼: requests/2026-08-23_trainer_rows_have_stage.md (判定①)

## なぜ

取り込みが **ページ全文** から進化段階の語を探していたので、進化段階の欄を持たない
トレーナーズ/エネルギーで効果テキストやセット名に当たっていた。

    M4-074 変化の書      「自分のトラッシュから たね ポケモンを1枚選び」   -> 'たね'
    MC-650 ハイパーアロマ  「自分の山札から 1進化 ポケモンを3枚まで選び」  -> '1進化'
    M2a-148 改造ハンマー   「ハイクラスパック 『MEGAドリームex』」        -> 'MEGA'

依頼書の指摘は Trainer 479行だったが、実測すると **2,366行**ズレていた
(Trainer 1,047 / Energy 788 / Pokémon 503 / 種別なし 28)。ポケモン側も誤っている。

## どう直すか

`<span class="type">たね</span>` に **アンカーして**取り直す。欄が無いカード
(トレーナーズ/エネルギー) は空が正しい。取得元は保存済の公式HTML
(`_raw/pokemon_tcg/<cardID>.html.gz`) で、**取り直しの通信はしない**。
scraper 側も同じ形に差し替え済 (scrapers/pokemon_tcg.py)。

★公式は `1&nbsp;進化` と書くので、実体参照を戻してから空白を落とす。

## 公式が持つ進化段階の全値 (2026-08-23 実測 21,982枚)

    たね 9906 / (空) 5411 / 1進化 4750 / 2進化 1484 / V進化 276 /
    レベルアップ 72 / BREAK進化 43 / 復元 14 / M進化 11 / 伝説 9 / V-UNION 6

実行:
  python migrations/2026-08-23_pokemon_stage_from_anchor.py           # dry-run
  python migrations/2026-08-23_pokemon_stage_from_anchor.py --commit
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
from tcg_ebay_normalized_fields_20260615 import norm_stage  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAW = Path(r"C:/dev/iMak_data/catalog/_raw/pokemon_tcg")
SPAN = re.compile(r'<span class="type">([^<]*)</span>')
NOW = datetime.now().isoformat(timespec="seconds")


def anchored_stage(card_id: str) -> str | None:
    """保存済 HTML から進化段階を取る。ファイルが無ければ None (= 触らない)."""
    p = RAW / f"{card_id}.html.gz"
    if not p.exists():
        return None
    try:
        h = gzip.open(p, "rt", encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    m = SPAN.search(h)
    if not m:
        return ""          # 欄が無い = 空が正しい
    return re.sub(r"\s+", "", html.unescape(m.group(1))).strip()


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, source_url, specs FROM products "
        "WHERE category='pokemon_tcg' AND source_url LIKE '%/card/%'").fetchall()

    pairs, by_type, updates, no_raw = Counter(), Counter(), [], 0
    for r in rows:
        cid = str(r["source_url"]).rsplit("/", 1)[-1]
        got = anchored_stage(cid)
        if got is None:
            no_raw += 1
            continue
        s = json.loads(r["specs"] or "{}")
        cur = re.sub(r"\s+", "", html.unescape(s.get("stage") or "")).strip()
        if got == cur:
            continue
        pairs[(cur or "(空)", got or "(空)")] += 1
        by_type[s.get("card_type_ebay") or "(なし)"] += 1
        if got:
            s["stage"] = got
        else:
            s.pop("stage", None)
        # stage_ebay も同時に引き直す (確証あるものだけ。不明は空欄 = fail-closed)
        se = norm_stage(got) if got else ""
        if se:
            s["stage_ebay"] = se
        else:
            s.pop("stage_ebay", None)
        s["stage_source"] = "official_span_type_20260823"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== 進化段階の取り直し (%s) ===" % ("APPLY" if commit else "DRY-RUN"))
    print("対象 %d 行 / 変わる %d 行 / raw が無くて触らなかった %d 行\n"
          % (len(rows), len(updates), no_raw))
    print("種別ごとの内訳:", by_type.most_common())
    print("\n%-12s %-14s %s" % ("今の値", "公式の欄", "行数"))
    for (a, b), n in pairs.most_common(25):
        print("%-12s %-14s %d" % (a, b, n))

    # ── 手順2: 公式の語彙に無い値を落とす ────────────────────────────────
    #   公式サイトに無いカード (bulbapedia 由来 等) に `-` が入っていた。`-` は
    #   「無し」を表すプレースホルダで公式の進化段階ではないので、空に戻す。
    #   推測で 'たね' 等を入れない (fail-closed)。
    OFFICIAL = {"たね", "1進化", "2進化", "V進化", "レベルアップ",
                "BREAK進化", "復元", "M進化", "伝説", "V-UNION"}
    stray = []
    for r in db.execute("SELECT id, product_id, specs FROM products "
                        "WHERE category='pokemon_tcg'").fetchall():
        s = json.loads(r["specs"] or "{}")
        v = (s.get("stage") or "").strip()
        if not v or v in OFFICIAL:
            continue
        s.pop("stage", None)
        s.pop("stage_ebay", None)
        s["stage_source"] = "dropped_non_official_value_20260823"
        stray.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        print("  - %s: 公式に無い値 %r → 空に戻す" % (r["product_id"], v))
    print("\n手順2 公式の語彙に無い値: %d 行" % len(stray))

    if commit:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       updates + stray)
        db.commit()
        print("\n[OK] 適用 %d 行 (手順1 %d / 手順2 %d)"
              % (len(updates) + len(stray), len(updates), len(stray)))
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
