# -*- coding: utf-8 -*-
"""C:Character が eBay の一覧に在る綴りかを毎日見る (2026-09-18 常設).

依頼: `iMak_data/catalog/requests/2026-09-18_character_normalize_implement.md` 項4。

## 何を出すか — **綴りのゆれだけ**。「一覧に無い」は出さない

Character は FREE_TEXT なので、**一覧に無い値は誤りではない** (新しい種・ワンピース /
ドラゴンボールのキャラは eBay の一覧にそもそも無い。2026-09-18 実測で ワンピは 0.5%)。
「一覧に無い」を数えると 1万行の赤が毎日出て、誰も見なくなる。だから出すのは
**直せる形の3つだけ**で、0件で維持する:

    §C1 綴りのゆれ    正規化すると一覧の値と一致する (`Ho-oh` → `Ho-Oh`)
    §C2 形の違い      末尾の形を外すと一覧に在る (`Mewtwo-EX` → `Mewtwo` + Speciality EX)
    §C3 キャラでない  `DON!! Card` / `Energy Marker` / `Basic * Energy`

新しい弾で同じ形が生えたら翌日ここに出る。直し方は
`migrations/2026-09-18_pokemon_character_ebay_spelling.py` を流すだけ (同じ判定を使っている)。

## 一覧は毎回取り直す

**保存値で判断しない** (1丁目1番地の判定基準)。既定で `tools/fetch_ebay_aspects.py` を
呼んで取り直し、失敗したら保存済みの最新を使って**取得日を添えて**出す (落とさない)。

実行:
  python tools/character_value_audit.py
  python tools/character_value_audit.py --no-fetch   # 取り直さない (テスト用)
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 判定は migration と同じ物を使う (二重に書くと片方だけ直って食い違う)
MIG = ROOT / "migrations" / "2026-09-18_pokemon_character_ebay_spelling.py"


def _load_rules():
    spec = importlib.util.spec_from_file_location("_char_rules", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def refetch() -> None:
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_ebay_aspects.py")],
                           capture_output=True, text=True, timeout=300)
        print("一覧を取り直しました" if r.returncode == 0
              else f"⚠️ 取り直しに失敗 (rc={r.returncode})。保存済みの最新で見ます")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠️ 取り直しに失敗 ({e})。保存済みの最新で見ます")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    if not args.no_fetch:
        refetch()

    rules = _load_rules()
    # 取得日が古くても audit は止めない (migration は止まる)。古さを出して続ける。
    rules.MAX_AGE_DAYS = 3650
    allowed = rules.load_allowed()
    rows = rules.plan(api._connect(), allowed)

    kind = Counter()
    for _, cat, old, new, form, _ in rows:
        sec = "§C3 キャラでない" if new is None else ("§C2 形の違い" if form else "§C1 綴りのゆれ")
        kind[(sec, cat)] += 1

    print(f"\n=== C:Character 綴り監査 ({date.today()}) ===")
    if not kind:
        print("§C1 / §C2 / §C3 いずれも 0件 ✅")
    for (sec, cat), n in sorted(kind.items()):
        print(f"{sec:16} {cat:15} {n:6}行")
        for _, c, old, new, form, _ in rows:
            if c == cat and (("§C3" in sec) == (new is None)) and (bool(form) == ("§C2" in sec)):
                print(f"    例: {old!r} → {new!r}")
                break
    total = sum(kind.values())
    print(f"合計 {total}行"
          + ("" if total == 0 else
             "  → `python migrations/2026-09-18_pokemon_character_ebay_spelling.py --commit` で直る"))
    # 可視化のみ。gate にしない (0 でも出し続ける)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
