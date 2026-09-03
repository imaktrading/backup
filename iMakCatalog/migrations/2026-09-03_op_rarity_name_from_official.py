"""公式と食い違っていた レアリティ11件 / 名前3件 を公式に合わせる (2026-09-03).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

`tools/official_drift_check.py` で公式カードリスト全62弾 (3,956枚) と突き合わせて出た分。
値は **その場で公式ページを取り直して**入れる (保存値を根拠にしない)。

## レアリティ (11件)

OP-17 のページで、SP パラレルが `SPカード`、`OP17-033` が `TR` なのに、
catalog は元弾の値 (`SR` / `R` / `P`) のままだった。
昨日 OP-17 を取り込んだ時、EN 側 (bandai_tcg_plus) の値しか入っていないため。

    EB04-007_OP17_p2 / OP12-056_OP17_p2 / OP13-028_OP17_p2 / OP14-108_OP17_p1 /
    OP16-098_OP17_p2 / P-084_OP17_p2 / P-107_OP17_p2 / ST27-005_OP17_p1 /
    ST31-004_OP17_p1 / ST32-002_OP17_p1   … SR/R/P -> SPカード (rarity_ebay: Special)
    OP17-033                              … R      -> TR      (rarity_ebay: Treasure Rare)

## 名前 (3件)

    OP17-024  ハウリングガブ                -> "ハウリング"ガブ            (引用符が落ちていた)
    OP07-077  ひとつなぎの大秘宝を獲りに行くぞ!!!  -> "ひとつなぎの大秘宝"を獲りに行くぞ!!!
    P-155     name_jp が空                -> トラファルガー・ロー

実行:
  python migrations/2026-09-03_op_rarity_name_from_official.py
  python migrations/2026-09-03_op_rarity_name_from_official.py --commit
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
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import official_drift_check as D  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
CAT = "one_piece_tcg"
SERIES = ("550117", "550107", "550901")   # 差分が出ていた弾


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    n_rar = n_name = 0
    print(f"=== 公式に合わせる ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for sid in SERIES:
        res = D.check_series(db, sid)
        for c, _got in res["rarity_ng"]:
            # その弾の行だけ直す (元弾の行は触らない)
            rows = db.execute(
                "SELECT id, product_id, specs FROM products WHERE category=? "
                "AND (product_id=? OR product_id LIKE ?) "
                "AND set_name_official LIKE ?",
                (CAT, c["no"], c["no"] + "_%", "%" + _set_key(sid) + "%")).fetchall()
            for r in rows:
                s = json.loads(r["specs"] or "{}")
                if str(s.get("rarity") or "") == c["rarity"]:
                    continue
                old = s.get("rarity")
                s["rarity"] = c["rarity"]
                re_ = api.derive_rarity_ebay(CAT, c["rarity"])
                if re_:
                    s["rarity_ebay"] = re_
                print(f"  [レア] {r['product_id']:24s} {old!r} -> {c['rarity']!r} / {re_!r}")
                n_rar += 1
                if commit:
                    db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                               (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        for c, _got in res["name_ng"]:
            rows = db.execute(
                "SELECT id, product_id, name, name_jp FROM products WHERE category=? "
                "AND (product_id=? OR product_id LIKE ?)",
                (CAT, c["no"], c["no"] + "_%")).fetchall()
            for r in rows:
                if (r["name_jp"] or "") == c["name"]:
                    continue
                print(f"  [名前] {r['product_id']:24s} name_jp={r['name_jp']!r} -> {c['name']!r}")
                n_name += 1
                if commit:
                    db.execute("UPDATE products SET name_jp=?, updated_at=? WHERE id=?",
                               (c["name"], NOW, r["id"]))
    if commit:
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}: レアリティ {n_rar} / 名前 {n_name}")


def _set_key(sid: str) -> str:
    """その弾の catalog 側 set_name_official に必ず入る語 (行を取り違えないため)."""
    return {"550117": "WORLD", "550107": "500", "550901": "Promo"}[sid]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
