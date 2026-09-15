"""ドン!!カード 9行の set_name_official を公式の弾名に直す — 2026-09-15

週次の整合性チェック (2026-09-14・§5 map潰れ) で見つかった。ドンカード一覧 PDF (2026-05-21 取り込み) の行に、
**公式に存在しない弾名**が入っていた (推測で書いたと思われる)。eBay の値 (set_name_ebay) は正しく、
出品には影響していない。直すのは日本語の set_name_official だけ。

正の根拠: 公式カードリスト (onepiece-cardgame.com/cardlist/) の弾の選択肢。
2026-09-14 に倉庫へ保存したページ (`_raw/one_piece_tcg/site_series_*.html.gz`) から読んだ:

    【OP-10】 ブースターパック 王族の血統      (誤: 王者の咆哮)
    【OP-11】 ブースターパック 神速の拳        (誤: 神龍の咆哮)
    【OP-12】 ブースターパック 師弟の絆        (誤: 謀略の卵)
    【OP-14】 ブースターパック 蒼海の七傑      (誤: 最強の七皇)
    【OP-16】 ブースターパック 決戦の刻        (誤: 決断の刻)
    【ST-10】 アルティメットデッキ “三船長”集結 (誤: 三海皇編)
    【ST-13】 アルティメットデッキ 3兄弟の絆   (誤: 3兄弟)

ドンカードの行の書き方 (`ブースターパック <名前> [OP-10]` / 末尾 ` variant`) は他のドン行に合わせて残す。

実行:
    python migrations/2026-09-15_one_piece_don_set_name_official_fix.py            # dry-run
    python migrations/2026-09-15_one_piece_don_set_name_official_fix.py --commit
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"

FIX = {
    "DON-OP10-001": ("ブースターパック 王者の咆哮 [OP-10]", "ブースターパック 王族の血統 [OP-10]"),
    "DON-OP10-002": ("ブースターパック 王者の咆哮 [OP-10] variant", "ブースターパック 王族の血統 [OP-10] variant"),
    "DON-OP11-001": ("ブースターパック 神龍の咆哮 [OP-11]", "ブースターパック 神速の拳 [OP-11]"),
    "DON-OP12-001": ("ブースターパック 謀略の卵 [OP-12]", "ブースターパック 師弟の絆 [OP-12]"),
    "DON-OP14-001": ("ブースターパック 最強の七皇 [OP-14]", "ブースターパック 蒼海の七傑 [OP-14]"),
    "DON-OP14-002": ("ブースターパック 最強の七皇 [OP-14]", "ブースターパック 蒼海の七傑 [OP-14]"),
    "DON-OP16-001": ("ブースターパック 決断の刻 [OP-16]", "ブースターパック 決戦の刻 [OP-16]"),
    "DON-OP16-002": ("ブースターパック 決断の刻 [OP-16]", "ブースターパック 決戦の刻 [OP-16]"),
    "DON-ST10-13-001": ("アルティメットデッキ 三海皇編 [ST-10] / 3兄弟 [ST-13]",
                        "アルティメットデッキ “三船長”集結 [ST-10] / 3兄弟の絆 [ST-13]"),
}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    now = datetime.now().isoformat(timespec="seconds")
    todo, skip = [], []
    for pid, (old, new) in FIX.items():
        r = db.execute("SELECT id, set_name_official FROM products "
                       "WHERE category='one_piece_tcg' AND product_id=?", (pid,)).fetchone()
        if r and r[1] == old:
            todo.append((r[0], pid, new))
        else:
            skip.append((pid, r[1] if r else None))
    if commit:
        for rid, pid, new in todo:
            db.execute("UPDATE products SET set_name_official=?, updated_at=? WHERE id=?", (new, now, rid))
        db.commit()
    left = sum(1 for pid, (old, _) in FIX.items() if db.execute(
        "SELECT 1 FROM products WHERE category='one_piece_tcg' AND product_id=? AND set_name_official=?",
        (pid, old)).fetchone())
    print(f"対象 {len(todo)}行 / 想定と違うので触らない {skip} / 誤った名前の残り {left}行 / "
          f"{'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
