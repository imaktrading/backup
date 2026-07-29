"""担当が書いた `_done.md` (実装完了報告) を機械的に検査し、**異常だけ**を窓口に出す.

なぜ必要か (2026-07-30):
    dispatch を並列化して上流の処理量を上げた結果、**完了報告の検証が窓口(1人)に集中**した。
    しかも窓口は worktree 分離ルールにより他 worktree のコードを読めないため、
    「報告書を読む」以上のことができない = 精読しても確度は上がらない。
    → **証拠が揃っているかは機械で判定**し、窓口は **異常だけ**を見る。

判定するもの (共有領域だけを読む。worktree には触らない):
    - commit hash が書かれているか (40桁 or 7桁以上の hex)
    - テストの実行結果が書かれているか (`N passed` 等)
    - 失敗・未実装の申告が無いか (あれば窓口が読む)
    - 依頼書の追加要求に「できなかった」と書かれていないか

出力は「要確認」だけ。全部揃っていれば1行で OK と出す (静かに流す)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DATA_ROOT = Path(r"C:\dev\iMak_data")
WORKTREES = ("hq", "catalog", "dedupe", "inventory", "harvest", "revise")

# 証拠として最低限あるべきもの
RE_COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")
RE_TESTS = re.compile(r"(\d+)\s*(passed|pass|件 pass|tests? passed)", re.I)
# ★データ作業 (catalog の DB/yaml 投入等) にはテストが無い。その場合は
#   「実行したコマンドと出力」を証拠として認める (2026-07-30)。
#   テストを一律必須にすると、テストの書けない作業が永久に ⚠️ になり警告が形骸化する。
RE_VERIFY = re.compile(r"(検証|実行コマンド|実測|SELECT\s|python -c|pytest)", re.I)
# 窓口が必ず目を通すべき語 (黙って流さない)
ALERT_WORDS = (
    "実装できなかった", "未実装", "できていません", "失敗", "failed", "error",
    "TODO", "保留", "スキップした", "断念",
)


# ★2026-07-30: 誤検出を抑える。依頼文の**引用**や条件節に反応すると全報告が ⚠️ になり、
#   警告が意味を失って読まれなくなる (実測: dedupe/inventory とも中身は完璧なのに
#   「実装できなかった**部分があれば**明示」の引用で吊るされた)。**狼少年にしない**。
QUOTE_PREFIXES = (">", "|", "- >")
CONDITIONAL_MARKERS = ("があれば", "場合は", "なら", "こと。", "してください", "禁止")


def _is_quote_or_requirement(line: str) -> bool:
    s = line.strip()
    if s.startswith(QUOTE_PREFIXES):
        return True                       # 引用 = 依頼文の再掲であって申告ではない
    if s.startswith("#"):
        # ★見出しは除外。テンプレの章タイトル「## 実装できなかった部分の明示」に反応して
        #   中身が「なし」でも ⚠️ になっていた (2026-07-30 実測)。申告は本文にある。
        return True
    if "✅" in s or "test_" in s:
        # ★テスト名 (`test_check_corrupt_stamp_emits_warning` = 「失敗」を含む) や
        #   ✅ 付きの完了行に反応していた。これらは申告ではない (2026-07-30 実測)。
        return True
    return any(m in s for m in CONDITIONAL_MARKERS)   # 条件節 = 「〜があれば書く」の要求文


def check_one(path: Path) -> dict:
    """1件の `_done.md` を検査 → {ok, reasons[]}."""
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "reasons": [f"読めない: {type(e).__name__}"]}
    reasons = []
    if not RE_COMMIT.search(body):
        reasons.append("commit hash が無い (何を commit したか不明)")
    if not RE_TESTS.search(body) and not RE_VERIFY.search(body):
        reasons.append("テスト結果も検証の実行記録も無い (動いた証拠が無い)")
    # 要読解ワードは **申告行だけ**見る (引用・条件節は除く)
    hits = sorted({w for line in body.splitlines() if not _is_quote_or_requirement(line)
                   for w in ALERT_WORDS if w.lower() in line.lower()})
    if hits:
        reasons.append("要読解ワード: " + " / ".join(hits))
    return {"ok": not reasons, "reasons": reasons}


def scan(root: Path = DATA_ROOT, since_prefix: str = "") -> list:
    """全 worktree の `_done.md` を検査。since_prefix で日付前方一致に絞れる (例 '2026-07-30')."""
    out = []
    for wt in WORKTREES:
        d = root / wt / "requests"
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*_done.md")):
            if since_prefix and not p.name.startswith(since_prefix):
                continue
            r = check_one(p)
            out.append({"worktree": wt, "path": p, **r})
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    since = ""
    for a in sys.argv[1:]:
        if a.startswith("--since="):
            since = a.split("=", 1)[1]
    rows = scan(since_prefix=since)
    if not rows:
        print("完了報告なし" + (f" (--since={since})" if since else ""))
        return 0
    ng = [r for r in rows if not r["ok"]]
    ok = [r for r in rows if r["ok"]]
    print(f"# 完了報告チェック — {len(rows)}件 (証拠OK {len(ok)} / **要確認 {len(ng)}**)\n")
    for r in ng:
        print(f"## ⚠️ [{r['worktree']}] {r['path'].name}")
        for why in r["reasons"]:
            print(f"   - {why}")
        print()
    if ok:
        print("### 証拠が揃っているもの (窓口の精読は不要)")
        for r in ok:
            print(f"   ✅ [{r['worktree']}] {r['path'].name}")
    if ng:
        print("\n→ ⚠️ の分だけ窓口が中身を読むこと。**証拠の無い完了報告は完了とみなさない**。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
