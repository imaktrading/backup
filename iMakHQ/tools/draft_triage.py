"""下書きの仕分け — 「窓口必須」と「定型」を **規則で** 分ける (判断はしない).

なぜ必要か (2026-07-30 ユーザー「任すわ」で採用した案3):
    事務員 (clerk) は 3時間ごとに滞留を報告していたが、2026-07-30 は
    **6:58 / 9:05 / 12:05 / 15:05 / 18:05 の5回連続で同じ30件を上げ、1件も処理されなかった**。
    仕組みの不備ではなく、窓口が「30件」の塊を見て着手できなかったのが原因。
    実際に裁定したら 12件中 8件は窓口判断が不要な定型だった。

    → **塊を割る**。窓口は「必須」だけ見れば済む状態にする。
      分類は LLM に任せない (事務員は判断しない原則)。**規則ベース + 根拠を必ず表示**。

★安全側の既定は「窓口必須」:
    どの規則にも当たらないものは **必須** に落とす。定型に落とすのは
    「定型シグナルが当たり、かつ 必須シグナルが1つも当たらない」時だけ
    (fail-closed。迷ったら窓口へ回す方が、勝手に流すより害が小さい)。

使い方:
    python draft_triage.py            # 全 worktree
    python draft_triage.py catalog    # 単一 worktree
    python draft_triage.py --record   # 集計を triage_metrics.jsonl に1行追記 (事務員が使う)

★--record は「様子見」を放置にしないための計測 (2026-07-30 ユーザー「とりあえず様子見したら？」)。
  現体制 (dispatch + 事務員 + 窓口) を続けるか、定型を窓口も通さない案1へ進むかを
  **勘ではなく推移で**決めるため、必須/定型の件数と滞留日数を毎巡回で残す。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worktree_board as wb  # noqa: E402

# ---------------------------------------------------------------- 必須シグナル
# 不可逆 / 外向き / 事業判断 / 選択肢提示 = 窓口 (or ユーザー) が持つべき判断。
MUST_PATTERNS: list[tuple[str, str]] = [
    (r"不可逆|取り返しがつかない", "不可逆な操作"),
    (r"rm\s+-rf|--force|force-push|git\s+reset\s+--hard|DROP\s+TABLE|truncate", "破壊的コマンド"),
    (r"\bdeny\b|permission|settings\.json", "権限・設定の変更"),
    (r"一括削除|全削除|一括取下げ|一括revise|一括更新", "一括操作"),
    (r"事業判断|新規参入|参入するか|新カテゴリ|新規カテゴリ", "事業判断"),
    (r"値上げ|値下げ|価格変更|price[_ ]change", "価格の変更 (外向き)"),
    (r"ユーザー判断|ユーザー裁定|ユーザーに確認", "ユーザー判断が要る"),
    (r"A案|B案|案1|案2|どちらを|いずれを選", "選択肢の提示"),
]
# ★`worktree` / `分離ルール` は必須シグナルに**入れない**。ほぼ全ての依頼書が規約として
#   引用しているため、入れると全件が「必須」に落ちて仕分けの意味が消える
#   (2026-07-30 初版で実際にそうなった)。分離違反の検出は本文語では無理なので、
#   **既定が必須**であることに任せる。

# ---------------------------------------------------------------- 定型シグナル
ROUTINE_PREFIXES = (
    "auto_catalog_add_", "pdca_catalog_queue_", "audit_catalog_fix_", "psa_mismatch_catalog",
)
STALE_DAYS = 30

METRICS = Path(r"C:\dev\iMak_data\clerk\triage_metrics.jsonl")
# 案1 (定型を窓口も通さない) へ進む判断ライン。ここに触れたら窓口へ提案を上げる。
MUST_ALERT = 5          # 必須が連続してこの数を超えるなら窓口が捌けていない
STAGNANT_ALERT_DAYS = 3  # 必須が3日動いていないなら同じく捌けていない


def _body(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def _topic(stem: str) -> str:
    """先頭の日付を落とした topic 名 (後発版の検出用)."""
    return _DATE_RE.sub("", stem)


def _date_prefix(stem: str) -> str:
    m = _DATE_RE.match(stem)
    return m.group(1) if m else ""


def _base_stem(stem: str) -> str:
    low = stem.lower()
    for suf in wb.DRAFT_SUFFIXES:
        if low.endswith(suf):
            return stem[: -len(suf)].rstrip("_")
    return stem


def classify(path: Path, siblings: list[Path]) -> tuple[str, str, str]:
    """(区分, 根拠, 定型時の既定処理) を返す。区分 = '必須' | '定型'."""
    body = _body(path)
    for pat, why in MUST_PATTERNS:
        if re.search(pat, body, re.I):
            return "必須", why, ""

    stem = _base_stem(path.stem)
    topic = _topic(stem)
    age_days = (time.time() - path.stat().st_mtime) / 86400

    # 同 topic の **別日付の後発版** がある = 置き換わっている。
    # ★同日の親依頼 (`{date}_{topic}.md`) を後発版と誤認しないよう、**日付が違う**ことを条件にする
    #   (auto 生成では draft が親より先に書かれることがあり、mtime だけでは判別できない)。
    my_date = _date_prefix(stem)
    for s in siblings:
        if s == path:
            continue
        s_base = _base_stem(s.stem)
        if (_topic(s_base) == topic
                and _date_prefix(s_base) != my_date
                and s.stat().st_mtime > path.stat().st_mtime):
            return "定型", f"別日付の後発版あり ({s.name})", "closed (後発版に吸収)"

    if age_days >= STALE_DAYS:
        return "定型", f"{int(age_days)}日 動いていない", "凍結 or closed (再浮上条件を明記)"

    if topic.startswith(ROUTINE_PREFIXES):
        return "定型", "定期 auto 生成物", "既定方針で流す"

    if re.search(r"推奨\s*[:：]?\s*GO|推奨\s*GO", body):
        return "定型", "draft 自身が GO 推奨 (不可逆シグナルなし)", "GO"

    return "必須", "定型規則に当たらない (安全側で必須)", ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # ★フラグを worktree 名として拾わないこと。`--record` を only に入れて
    #   全 worktree を skip し「0件」と誤報した (2026-07-30)。
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    only = positional[0] if positional else None

    must: list[tuple[str, Path, str]] = []
    routine: list[tuple[str, Path, str, str]] = []
    for wt, label in wb.WORKTREES:
        if only and wt != only:
            continue
        _mine, _theirs, drafts = wb.pending_for(wt)
        if not drafts:
            continue
        siblings = list((wb.DATA_ROOT / wt / "requests").glob("*.md"))
        for p in drafts:
            kind, why, default = classify(p, siblings)
            if kind == "必須":
                must.append((label, p, why))
            else:
                routine.append((label, p, why, default))

    print("# 下書きの仕分け (規則ベース / 既定は窓口必須)\n")
    print(f"## 🔴 窓口必須 {len(must)}件  ← ここだけ見れば足りる")
    if not must:
        print("- なし")
    for label, p, why in must:
        print(f"- **[{label}]** {p.name}\n  - 理由: {why}")
    print(f"\n## ⚪ 定型 {len(routine)}件  (既定処理で流せる / 窓口は流し読みでよい)")
    if not routine:
        print("- なし")
    for label, p, why, default in routine:
        print(f"- [{label}] {p.name}\n  - {why} → 既定: {default}")
    # ---- 滞留日数 (必須の最古) と 体制判断ライン ----
    oldest = max((time.time() - p.stat().st_mtime) / 86400 for _l, p, _w in must) if must else 0.0
    flags = []
    if len(must) > MUST_ALERT:
        flags.append(f"必須が{len(must)}件 (>{MUST_ALERT}) = 窓口が捌けていない")
    if oldest >= STAGNANT_ALERT_DAYS:
        flags.append(f"必須の最古が{oldest:.1f}日 (>={STAGNANT_ALERT_DAYS}) = 滞留している")
    if flags:
        print("\n## 🚩 体制の見直しライン に触れた")
        for f in flags:
            print(f"- {f}")
        print("- → 窓口へ: 「定型を窓口も通さない (案1)」へ進めるか判断を上げること")

    if "--record" in sys.argv:
        METRICS.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
               "must": len(must), "routine": len(routine),
               "oldest_must_days": round(oldest, 2),
               "flags": flags}
        with METRICS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 直近の推移 (様子見の判断材料。窓口が覚えておかなくて済むように出す)
        try:
            hist = [json.loads(ln) for ln in
                    METRICS.read_text(encoding="utf-8").splitlines() if ln.strip()][-6:]
            if len(hist) > 1:
                print("\n## 推移 (直近)")
                for h in hist:
                    print(f"- {h['ts']}  必須{h['must']} / 定型{h['routine']}"
                          f" / 最古{h['oldest_must_days']}日")
        except (OSError, ValueError):
            pass

    print(f"\nSUMMARY: 窓口必須{len(must)}件 / 定型{len(routine)}件 / 必須最古{oldest:.1f}日")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
