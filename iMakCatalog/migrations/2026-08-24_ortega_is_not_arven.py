"""オルティガ 3行が Arven (=ペパー) になっている — Jacq / Poké Kid と同じ型の3例目.

依頼: requests/2026-08-24_hq_ortega_is_not_arven.md (判定①)

## 根拠

    PSA cert 80181108  Subject = "ORTEGA SUPER"   -> SV3-130 は Ortega
    Arven は **ペパー** の英名 (カタログ内で確認: ペパーのノノクラゲ = "Arven's Toedscool")

つまり別人の名前が入っている。出所は 3行とも `claude_api` で、ジニア→Zinnia と同じ。

    SV3-104 SV3-130 SV8a-189   name_en / character_name = 'Arven' -> 'Ortega'

★日本語名で対象を絞る。英名 'Arven' で置換すると **本物のペパー (Arven) の行**を壊す。

実行:
  python migrations/2026-08-24_ortega_is_not_arven.py           # dry-run
  python migrations/2026-08-24_ortega_is_not_arven.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
JP, WRONG, RIGHT = "オルティガ", "Arven", "Ortega"
# 出所は回答書 `2026-08-24_hq_ortega_is_not_arven_response.md` §1 が指定した形にする
# (PSA cert80181108 Subject="ORTEGA SUPER" が根拠。cert 番号を出所に残す)。
SOURCE = "psa_label_cert80181108"


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, name, name_en, name_en_source, specs "
                      "FROM products "
                      "WHERE category='pokemon_tcg' AND name=?", (JP,)).fetchall()
    print(f"=== {JP} {len(rows)} 行 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    n = 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if (r["name_en"] == RIGHT and s.get("character_name") == RIGHT
                and r["name_en_source"] == SOURCE):
            print(f"  - {r['product_id']:12s} 既に {RIGHT} → skip")
            continue
        print(f"  + {r['product_id']:12s} {r['name_en']!r} / char={s.get('character_name')!r} -> {RIGHT!r}")
        s["character_name"] = RIGHT
        s["name_en_fix"] = "2026-08-24_cert80181108_ortega"
        n += 1
        if commit:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, "
                       "updated_at=? WHERE id=?",
                       (RIGHT, SOURCE,
                        json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    # 本物のペパー (Arven) を壊していないことを確認
    keep = db.execute("SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                      "AND name_en LIKE 'Arven%'").fetchone()[0]
    print(f"\nArven のまま残る行 (ペパー) = {keep}")
    if commit:
        db.commit()
        print(f"[OK] 適用 {n} 行")
    else:
        print(f"対象 {n} 行 (dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
