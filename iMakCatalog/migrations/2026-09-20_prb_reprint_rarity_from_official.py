# -*- coding: utf-8 -*-
"""PRB 再録の重複行のレアリティを公式に合わせる (2026-09-20).

判定 (1丁目1番地): **①カタログのデータ**。出品くんは KEY だけで引いており正しい。
依頼: `catalog/requests/2026-09-20_prb_reprint_rarity_fix.md` (元 2026-09-14 の調査)

## 何が起きていたか

同じカードが2行ある (`EB02-061_p3` = 公式取り込み / `EB02-061_PRB02_p3` = EN 取り込み)。
EN 側は **元カードのレアリティ** (`SEC` 等) を持っており、**SP 版の `SPカード` ではない**。
tcg_plus 行が引かれるとレアリティを誤って出す。
2026-09-03 の OP-17 の是正 (`2026-09-03_op_rarity_name_from_official.py`) と同じ原因で、
PRB は その migration の対象弾に入っていなかった。

## 直し方 (公式をその場で取り直す)

公式カードリスト PRB-01 (550301) / PRB-02 (550302) を取得し、
**カードの画像ファイル名から枝番を取って** (`EB02-061_p3.png` → `EB02-061_p3`)
「番号+枝番 → レアリティ」の表を作る。catalog の行は `_PRB0n` を外した形で引く。

★`tools/official_drift_check.py` ではこの誤りを見つけられない。あの道具は同じ番号の
  **全行のレアリティを1つの集合にまとめ、どれか1つでも公式と合えば OK** とするため、
  正しい行が隣に在ると誤った行が隠れる (2026-09-20 実測: 差分0件と出る)。

実行:
  python migrations/2026-09-20_prb_reprint_rarity_from_official.py [--commit]
"""
from __future__ import annotations

import json
import re
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

CAT = "one_piece_tcg"
SERIES = ("550301", "550302")
TAG = "prb_rarity_from_official_20260920"
IMG_RE = re.compile(r'src="[^"]*/([A-Z0-9-]+-\d+(?:_[a-z]\d+)?)\.png')
ROW_RE = re.compile(r"<span>([A-Z0-9-]+-\d+)</span>\s*\|\s*<span>([^<]+)</span>")


def official_rarity() -> dict[str, str]:
    """{番号+枝番: レアリティ}. 公式をその場で取得する."""
    out: dict[str, str] = {}
    for sid in SERIES:
        html = D._get(D.LIST_URL.format(sid=sid))
        for b in re.split(r'(?=<dl class="modalCol)', html):
            m = IMG_RE.search(b)
            r = ROW_RE.search(re.sub(r"\s+", " ", b))
            if m and r:
                out.setdefault(m.group(1), r.group(2).strip())
    if not out:
        raise SystemExit("公式からレアリティを1件も読めなかった (ページ構造が変わった?)")
    print(f"公式 {len(out)}枚 (PRB-01 + PRB-02 / 取得 {datetime.now():%Y-%m-%d %H:%M})")
    return out


def matches(got: str, want: str) -> bool:
    # `SPカード` = `SP`。複合コード (`SP P`) は分けて見る (2026-09-05 の規約)
    return bool({want, want.replace("カード", "")} & (set(got.split()) | {got}))


def find(db, off: dict[str, str]):
    pairs = mism = 0
    out = []
    for rid, pid, src, specs in db.execute(
            "SELECT id, product_id, source, specs FROM products "
            "WHERE category=? AND product_id LIKE '%!_PRB0%' ESCAPE '!'", (CAT,)):
        variant = re.sub(r"_PRB0\d", "", pid)
        want = off.get(variant) or off.get(variant + "_r1")
        if not want:
            continue          # 公式 PRB の一覧に無い行 (EN 側だけの括り) は対象外
        pairs += 1
        s = json.loads(specs or "{}")
        got = str(s.get("rarity") or "").strip()
        if matches(got, want):
            continue
        mism += 1
        out.append((rid, pid, src, got, want, s))
    return pairs, mism, out


def main(commit: bool) -> None:
    off = official_rarity()
    db = api._connect()
    pairs, mism, rows = find(db, off)
    print(f"公式 PRB に在る catalog 行 {pairs}行 / 食い違い {mism}行")
    for _, pid, src, got, want, _ in rows:
        print(f"  {pid:26} {src:16} {got!r} → {want!r}")

    if not commit:
        print("dry-run (書いていない)")
        return

    now = datetime.now().isoformat(timespec="seconds")
    for rid, pid, _, got, want, s in rows:
        s["rarity_prev"] = got
        s["rarity"] = want
        re_ = api.derive_rarity_ebay(CAT, want)
        if re_:
            s["rarity_ebay"] = re_
        s["rarity_source"] = TAG
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                   (json.dumps(s, ensure_ascii=False), now, rid))
    db.commit()
    _, left, _ = find(db, off)
    print(f"書いた {len(rows)}行 / 同じ基準で数え直し: 残り {left}行")


if __name__ == "__main__":
    main("--commit" in sys.argv)
