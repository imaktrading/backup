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
import importlib.util
import re
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


# ---------------------------------------------------------------------------
# catalog 実在 pre-check (2026-08-08)
#
# なぜ: `post_psa_review._route_none_to_catalog` にだけ pre-check があり (18b36a2)、
#   **こちらの watcher が素通ししていた**ため、既に catalog にあるカードの追加依頼が
#   毎日 catalog に届いていた。ここは書き手を問わない最終防衛線
#   (psa_to_csv / psa_restock_csv / 将来の writer のどれから来ても引っかかる)。
#
# 依頼書: C:/dev/iMak_data/hq/requests/2026-08-08_auto_catalog_add_needs_same_precheck.md
#
# ★判定の定義は post_psa_review に SSOT。ここでは **再実装しない** (2箇所に書くと必ずズレる)。

# `_route_none_to_catalog` が書く既知トークン `(auto候補<PID>=` の逆処理。
# 名前検索でも曖昧一致でもなく、SSOT 側が埋めた literal を抜くだけ。
_AUTO_CANDIDATE_RE = re.compile(r"\(auto候補([^=]+)=")


def _extract_expected_pid(model: str) -> str | None:
    """model 文字列から canonical PID を抜く。抜けなければ None (= 判定不能)。

    missing_models.csv の model には2形式ある:
      1. post_psa_review 由来 … `cert154233090 ONE PIECE … (auto候補OP07-118=該当なし 要調査)`
         → `(auto候補<PID>=` に canonical PID が埋まっている
      2. psa_to_csv 由来 … `ONE PIECE JAPANESE 3RD ANNIVERSARY SET-118`
         → **canonical PID ではない**ので None を返し、従来通り依頼を出す (fail-closed)
    """
    if not model:
        return None
    m = _AUTO_CANDIDATE_RE.search(model)
    if not m:
        return None
    return m.group(1).strip() or None


def _load_catalog_probe():
    """post_psa_review から `_catalog_has_pid` と log path を借りる (再実装しない)。

    取れなければ (None, None) を返し、呼出側は **全件を従来通り依頼**に回す (fail-closed)。
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "post_psa_review_probe", str(Path(__file__).parent / "post_psa_review.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._catalog_has_pid, mod._VIEWER_DISAGREEMENT_LOG_PATH
    except Exception as e:      # noqa: BLE001  取れないこと自体は握りつぶさず表示する
        print(f"[warn] catalog実在 pre-check を読み込めない ({e}) → 全件を従来通り依頼")
        return None, None


def _filter_catalog_present(new_by_cat: dict[str, list[dict]],
                            unique: dict[tuple[str, str], dict] | None = None,
                            db_path=None) -> int:
    """catalog に実在する (category, model) を new_by_cat から取り除き、件数を返す。

    fail-closed 契約 (18b36a2 準拠):
      - `_catalog_has_pid` が **True の時だけ**除外する
      - False (未収録) / None (pid 空・DB 不在・抽出不能) は従来通り依頼を出す
      - 名前検索フォールバック禁止 (canonical KEY 完全一致のみ)
      - 除外した件は理由付きで viewer_disagreement.log へ (18b36a2 と同じ log)

    ★`unique` を渡すと missing_models.csv 側からも落とす。
      落とさないと **毎日同じ行を再判定して log に同じ行を積む**ため
      (「毎回検出して毎回捨てる」= 動いているのか壊れているのか読めなくなる)。
      processed sentinel には入れない ので、catalog から消えれば次の検出でまた載る。
    """
    has_pid, vd_path = _load_catalog_probe()
    if has_pid is None:
        return 0

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    removed = 0
    for category, rows in list(new_by_cat.items()):
        kept: list[dict] = []
        for r in rows:
            pid = _extract_expected_pid(r["model"])
            exists = has_pid(category, pid, db_path) if pid else None
            if exists is not True:
                kept.append(r)
                continue
            # viewer/adapter 側の食い違い → catalog に依頼を出さない
            try:
                vd_path.parent.mkdir(parents=True, exist_ok=True)
                with vd_path.open("a", encoding="utf-8") as vf:
                    vf.write(f"{ts}\t[auto_catalog_add_watcher]\t{category}\t{pid}"
                             f"\tmodel={r['model']}\n")
            except OSError:
                pass
            if unique is not None:
                unique.pop((category, r["model"]), None)
            print(f"    ⏭️ Skip auto_catalog_add (catalog実在): {category}:{pid}")
            removed += 1
        if kept:
            new_by_cat[category] = kept
        else:
            del new_by_cat[category]
    return removed


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

    # 2b. catalog 実在 pre-check (18b36a2 と同じ fail-closed 契約, 2026-08-08)
    skipped_present = _filter_catalog_present(new_by_cat, unique)
    if skipped_present:
        print(f"[skip] catalog実在 pre-check で {skipped_present} 件除外 "
              f"→ viewer_disagreement.log")

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
