"""auto_catalog_add_request.py — missing_models.csv watcher.

C:/dev/iMak_data/catalog/missing_models.csv の新規 model を検知して、
Catalog Claude 向け追加依頼書を C:/dev/iMak_data/catalog/requests/ に自動生成する。

- Claude を使わず純 Python (= 過去並列 session 事故 type と無縁)
- 既処理 sentinel: missing_models_processed.csv (= (category, model) key で保持)
- 依頼書 filename: YYYY-MM-DD_auto_catalog_add_<category>.md
- 同日同 category 既存ファイルは skip (= 翌日 chance、 重複投入回避)
- 議論要件 (= ranking logic / 既存修正 / specs 拡充) は本仕組み対象外、
  HQ から個別依頼書

ユーザー合意 2026-05-25: 「カタログ追加は確認なしに依頼するようにしてほしい」
"""
from __future__ import annotations

import csv
import datetime
import sys
from collections import defaultdict
from pathlib import Path

DATA_ROOT = Path("C:/dev/iMak_data/catalog")
MISSING_CSV = DATA_ROOT / "missing_models.csv"
PROCESSED_CSV = DATA_ROOT / "missing_models_processed.csv"
REQUESTS_DIR = DATA_ROOT / "requests"

CATEGORY_LABELS: dict[str, str] = {
    "gshock":         "G-SHOCK 腕時計",
    "pokemon_tcg":    "Pokemon TCG",
    "one_piece_tcg":  "One Piece TCG",
    "dragonball_scg": "Dragonball SCG",
    "gundam_tcg":     "Gundam TCG",
    "montbell":       "montbell",
    "uniqlo_ut":      "UNIQLO UT",
    "workman":        "Workman",
}


def _load_processed() -> set[tuple[str, str]]:
    if not PROCESSED_CSV.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with PROCESSED_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            keys.add((r["category"], r["model"]))
    return keys


def _append_processed(rows: list[dict]) -> None:
    is_new = not PROCESSED_CSV.exists() or PROCESSED_CSV.stat().st_size == 0
    with PROCESSED_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["category", "model", "detected_at"])
        for r in rows:
            w.writerow([r["category"], r["model"], r["detected_at"]])


def _prune_old_missing(unique: dict[tuple[str, str], dict], max_age_days: int = 30,
                       today: str = "") -> int:
    """detected_at が max_age_days より古い行を unique から in-place 削除 (純関数寄り, test可)。
    戻り: 間引いた件数。today 未指定なら本日。ISO 日付の辞書順比較。"""
    if not today:
        today = datetime.date.today().strftime("%Y-%m-%d")
    try:
        cutoff = (datetime.date.fromisoformat(today[:10])
                  - datetime.timedelta(days=max_age_days)).isoformat()
    except Exception:
        return 0
    drop = [k for k, r in unique.items()
            if len((r.get("detected_at") or "")[:10]) == 10
            and r["detected_at"][:10] < cutoff]
    for k in drop:
        del unique[k]
    return len(drop)


def _rewrite_missing(unique: dict[tuple[str, str], dict]) -> None:
    """missing_models.csv を dedup 後の内容で書き戻す (= 容量管理)."""
    with MISSING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "model", "detected_at"])
        for r in sorted(unique.values(), key=lambda x: (x["category"], x["model"])):
            w.writerow([r["category"], r["model"], r["detected_at"]])


def _write_request(out_path: Path, category: str, rows: list[dict]) -> None:
    today = datetime.date.today().strftime("%Y-%m-%d")
    label = CATEGORY_LABELS.get(category, category)
    rows_sorted = sorted(rows, key=lambda r: r["model"])
    table_body = "".join(
        f"| `{r['model']}` | {r['detected_at']} |\n" for r in rows_sorted
    )
    out_path.write_text(
        f"# 自動依頼: {label} カタログ追加 (auto-generated)\n\n"
        f"- **依頼日**: {today}\n"
        f"- **依頼者**: HQ Claude `auto_catalog_add_request.py`\n"
        f"- **緊急度**: 低 (= バッチ追加、 即時 NG)\n"
        f"- **フェーズ**: 本実装 (= 公式 ID 確定済の単純追加、 議論不要)\n"
        f"- **生成元**: `C:/dev/iMak_data/catalog/missing_models.csv` 新規行\n"
        f"- **判定**: **ユーザー判断スキップ済** "
        f"(= 「カタログ追加は確認なしに依頼」 合意 2026-05-25)\n\n"
        f"---\n\n"
        f"## 追加対象 ({len(rows_sorted)} models)\n\n"
        f"| model | detected_at |\n"
        f"|---|---|\n"
        f"{table_body}\n"
        f"---\n\n"
        f"## 依頼内容\n\n"
        f"上記 model を `{category}` カテゴリの Catalog DB に追加してください。\n\n"
        f"- 公式情報元のみ採用 (= Bandai TCG+ API / カシオ公式 / 各 supplier 公式)\n"
        f"- ID 完全一致 lookup で名称取得、 推測禁止 (= fail-closed 原則)\n"
        f"- 既存登録あれば「投入不要」 と報告 (= adapter 抽出 bug 等の構造問題を別途調査)\n"
        f"- 完了後 本依頼書を `_processed.md` rename + 短いレポート追加\n\n"
        f"## 自動運用注意\n\n"
        f"- 本依頼書は `auto_catalog_add_request.py` が自動生成 (= 純 Python、 Claude 未使用)\n"
        f"- 同日同 category の追加 detect は **本ファイル既存なら skip** (= 翌日新規 file)\n"
        f"- 議論要件 (= ranking logic / 既存修正 / specs 拡充) は本仕組み対象外、 "
        f"HQ から個別依頼書\n",
        encoding="utf-8",
    )


def main() -> int:
    if not MISSING_CSV.exists():
        print(f"no missing_models.csv at {MISSING_CSV}")
        return 0

    # 1. missing_models 全行読込 + (cat, model) dedup
    unique: dict[tuple[str, str], dict] = {}
    with MISSING_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["category"], r["model"])
            if k not in unique or r["detected_at"] > unique[k]["detected_at"]:
                unique[k] = r

    # 1b. 長期滞留(detected_at > 30日)を間引き(K1・容量管理 + 再import停止)。
    # 30日経っても catalog 未追加 = 依頼済の構造案件(pdca 側で stale 退役済)。再 import で
    # seen_count を永遠に増やし続けるのを止める。新規検出が来れば detected_at 新でまた載る。
    pruned_old = _prune_old_missing(unique)
    if pruned_old:
        print(f"[prune] missing_models 古い行(>30日)を {pruned_old} 件間引き")

    # 2. 既処理と差分
    processed = _load_processed()
    new_by_cat: dict[str, list[dict]] = defaultdict(list)
    for k, r in unique.items():
        if k not in processed:
            new_by_cat[r["category"]].append(r)

    # 3. category 別に依頼書投入
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    processed_now: list[dict] = []

    for category, rows in sorted(new_by_cat.items()):
        out_path = REQUESTS_DIR / f"{today}_auto_catalog_add_{category}.md"
        if out_path.exists():
            print(f"[skip] {out_path.name} 既存 (= 翌日新規 file 待ち)")
            continue
        _write_request(out_path, category, rows)
        processed_now.extend(rows)
        print(f"[create] {out_path.name} ({len(rows)} models)")

    if processed_now:
        _append_processed(processed_now)

    # 4. missing_models.csv を dedup 後の内容で rewrite (= 容量管理)
    _rewrite_missing(unique)

    if not new_by_cat:
        print("no new missing models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
