"""Pokemon `set_name_official` re-derivation — image-folder-single-fetch (Phase 1).

依頼: `2026-08-02_pokemon_set_name_official_316_setcode_fetch_response.md` §A/C
判定: ① 誤 / ② 正 → ①だけ直す (草案 & 窓口確定)

## 群キー = image folder (= 公式画像 `/large/{folder}/` の folder 部分)

窓口初案の `product_id.split("-")[0]` は BW1/BW3/BW5/BW6/BW8/XY1/XY5/XY8/XY11/L1 の
「二種同時発売パック」を 1 群に潰す (約1,200行を別商品名で塗る事故)。image folder では
既に分離されているので事故は起きない (BW1-Bb / BW1-Bw が別 folder)。

## Phase 1 対象 = 305 folder / 約13,700 rows

- single-value folder: 153 (folder 内に既に1種類だけの set_name_official がある)
- all-NULL folder (deck 5 除く): 152 (SD/SVD/SVM/SMH/SGG は 1枚ごとに商品違い→ Phase 2)
- 除外: 13 multi-value folder / 2,600 行 (SMP/SI/XYP/SV-P/BWP/DP4/DP5/DP1/ENE/DPtP/SMI/SMM/'')
- 除外: 5 deck folder / 593 行 (SD/SVD/SVM/SMH/SGG)

## 手順

1. **cache 削除必須** (`iMakCatalog/db/cache/pokemon_tcg/detail_{cardID}.json`)。
   忘れると 4/28 以前の古いパース結果 (旧 regex 5本) が返り、UPDATE が空回りする。
2. 各 folder から 1 枚選び、`get_detail(cid)` で fetch → 新パーサ (SubSection) の
   `set_name_official` を採る。
3. 取れた値を **そのカラム単独で** UPDATE (specs JSON は絶対に触らない ← invariant 保護)。
4. before/after を JSON で残す。
5. 取れなかった folder は **触らない** (公式が返さない = 現状維持)。

## CLI

    py pokemon_set_name_official_folder_fetch.py --plan                 # 対象folder一覧のみ
    py pokemon_set_name_official_folder_fetch.py --smoke                # 5件fetch, DB書込なし
    py pokemon_set_name_official_folder_fetch.py --phase1 --confirm    # 本実行 (窓口GO後)

## 注意

- **`--confirm` 無しでは phase1 実行しない** (誤操作防止)
- fetch は既存 scraper (`pokemon_tcg._get` / `get_detail`) を再利用 (polite backoff 込み)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog import api as _api  # noqa: E402
from iMakCatalog.scrapers import pokemon_tcg as _pk  # noqa: E402


# ============================================================================
# 定数
# ============================================================================
CATEGORY = "pokemon_tcg"
CACHE_DIR = _pk.CACHE_DIR
FOLDER_RE = re.compile(r"/large/([^/]*)/")

# デッキ系 (Finding 3): 1枚ごとに商品が違うので folder 単位 update 禁止 (Phase 2 で per-card)
DECK_FOLDERS = frozenset({"SD", "SVD", "SVM", "SMH", "SGG"})

# smoke test 5件 (窓口回答書 §C の指定そのまま。省略不可)
SMOKE_TARGETS = [
    "SV1a-001",     # 単値 folder / a接尾辞 (拡張パック「トリプレットビート」想定)
    "SD-001",       # deck / all NULL (Vスタートデッキ 草 フシギバナ 想定)
    "S8a-001",      # multi-product folder の base pack (拡張パック「25th ANNIVERSARY COLLECTION」)
    "S8a-G-001",    # multi-product folder の別商品 (25th ANNIVERSARY GOLDEN BOX)
    "BW1-Bb-001",   # dual-release pack の片方 (拡張パック「ブラックコレクション」想定)
]

SOURCE_TAG = "official_setcode_fetch_20260802"


# ============================================================================
# folder 抽出 helpers
# ============================================================================
def _folder_of_image(images_json: str | None) -> str:
    """`images` (JSON string) の先頭 URL から image folder を抽出.

    Returns:
        folder (例 'SV1a', 'S8a-G', 'BW1-Bb') / 抽出不能なら空文字列.
    """
    if not images_json:
        return ""
    try:
        imgs = json.loads(images_json)
    except Exception:
        return ""
    for u in imgs or []:
        m = FOLDER_RE.search(u or "")
        if m:
            return m.group(1)
    return ""


def _cardid_of_image(images_json: str | None) -> str:
    """`images` 先頭 URL から公式 cardID (= 5桁ゼロパディング) を抽出."""
    if not images_json:
        return ""
    try:
        imgs = json.loads(images_json)
    except Exception:
        return ""
    for u in imgs or []:
        m = re.search(r"/large/[^/]*/([0-9]+)_", u or "")
        if m:
            return m.group(1)
    return ""


def build_folder_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """DB 全 pokemon_tcg 行から folder 索引を作る.

    Returns:
        {folder: {"rows": [(product_id, cardID, current_set_name_official), ...],
                  "distinct_values": set(current values, 空文字列/NULL 除く)}}
    """
    idx: dict[str, dict] = defaultdict(lambda: {"rows": [], "distinct_values": set()})
    cur = conn.execute(
        "SELECT product_id, images, set_name_official "
        "FROM products WHERE category=?",
        (CATEGORY,),
    )
    for pid, img, sno in cur:
        folder = _folder_of_image(img)
        cid = _cardid_of_image(img)
        idx[folder]["rows"].append((pid, cid, sno))
        if sno is not None and sno != "":
            idx[folder]["distinct_values"].add(sno)
    return dict(idx)


def classify_folders(idx: dict[str, dict]) -> dict[str, list[str]]:
    """folder を single / all_null / multi / no_folder に分類."""
    out: dict[str, list[str]] = {
        "single": [], "all_null": [], "multi": [], "no_folder": [],
    }
    for folder, info in idx.items():
        if folder == "":
            out["no_folder"].append(folder)
            continue
        nv = len(info["distinct_values"])
        if nv == 0:
            out["all_null"].append(folder)
        elif nv == 1:
            out["single"].append(folder)
        else:
            out["multi"].append(folder)
    for k in out:
        out[k].sort()
    return out


def phase1_target_folders(idx: dict[str, dict]) -> list[str]:
    """Phase 1 対象 folder list = single + (all_null - 5 deck).

    順序: 短い名 → 長い名 (安定順、レポートの見やすさ用).
    """
    cls = classify_folders(idx)
    target = list(cls["single"]) + [f for f in cls["all_null"] if f not in DECK_FOLDERS]
    return sorted(target, key=lambda x: (len(x), x))


def pick_representative_cardid(idx: dict[str, dict], folder: str) -> str | None:
    """folder から 1枚 の公式 cardID を返す (最も小さい product_id 順)."""
    rows = idx.get(folder, {}).get("rows", [])
    candidates = [(pid, cid) for pid, cid, _sno in rows if cid]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def delete_cache(card_id: str) -> bool:
    """cache file を削除. 削除できたら True, なければ False."""
    path = CACHE_DIR / f"detail_{card_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ============================================================================
# fetch (cache 削除必須)
# ============================================================================
def fetch_set_name_official(card_id: str) -> tuple[str | None, dict | None]:
    """cardID の cache を必ず先に削除してから detail を fetch し set_name_official を返す.

    Returns:
        (set_name_official, detail_dict) — 取れなかったら (None, detail_dict or None).
    """
    delete_cache(card_id)
    detail = _pk.get_detail(card_id)
    if not detail:
        return None, None
    return detail.get("set_name_official"), detail


# ============================================================================
# smoke test (DB 書込なし)
# ============================================================================
def run_smoke(conn: sqlite3.Connection) -> list[dict]:
    """5 件を fetch → 結果を dict list で返す (DB 書込なし)."""
    out: list[dict] = []
    for pid in SMOKE_TARGETS:
        row = conn.execute(
            "SELECT product_id, images, set_name_official, name "
            "FROM products WHERE category=? AND product_id=?",
            (CATEGORY, pid),
        ).fetchone()
        if not row:
            out.append({
                "product_id": pid, "status": "not_in_db",
                "folder": None, "cardID": None,
                "before": None, "after": None, "name": None,
            })
            continue
        _pid, img, before, name = row
        folder = _folder_of_image(img)
        cid = _cardid_of_image(img)
        if not cid:
            out.append({
                "product_id": pid, "status": "no_cardID",
                "folder": folder, "cardID": None,
                "before": before, "after": None, "name": name,
            })
            continue
        after, _detail = fetch_set_name_official(cid)
        out.append({
            "product_id": pid,
            "status": "ok" if after else "fetch_returned_none",
            "folder": folder, "cardID": cid,
            "before": before, "after": after, "name": name,
        })
    return out


# ============================================================================
# plan (対象一覧のみ、fetch なし)
# ============================================================================
def build_plan(conn: sqlite3.Connection) -> dict:
    idx = build_folder_index(conn)
    cls = classify_folders(idx)
    target = phase1_target_folders(idx)
    def _rows(folders):
        return sum(len(idx[f]["rows"]) for f in folders)
    return {
        "total_rows": sum(len(info["rows"]) for info in idx.values()),
        "total_folders": len(idx),
        "phase1_target_folders": len(target),
        "phase1_target_rows": _rows(target),
        "phase2_excluded": {
            "multi_folders": len(cls["multi"]),
            "multi_rows": _rows(cls["multi"]),
            "deck_folders": sorted(DECK_FOLDERS),
            "deck_rows": _rows([f for f in DECK_FOLDERS if f in idx]),
            "no_folder_rows": _rows(cls["no_folder"]),
        },
        "breakdown": {
            "single_folders": len(cls["single"]),
            "all_null_folders": len(cls["all_null"]),
            "all_null_non_deck_folders": len(
                [f for f in cls["all_null"] if f not in DECK_FOLDERS]
            ),
        },
        "target_folders_sample": target[:20],
    }


# ============================================================================
# Phase 1 実行 (要 --confirm)
# ============================================================================
def run_phase1(conn: sqlite3.Connection, out_dir: Path) -> dict:
    """305 folder × 1 fetch → 各 folder の全行を UPDATE (set_name_official 単独カラム).

    before/after は JSON で out_dir に保存 (巻き戻しできる形).
    """
    started = datetime.now().isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)

    idx = build_folder_index(conn)
    targets = phase1_target_folders(idx)

    fetched: dict[str, dict] = {}   # folder → {"cardID", "value", "status"}
    before_after: list[dict] = []
    n_updated_rows = 0
    n_folders_updated = 0
    n_folders_no_value = 0

    for i, folder in enumerate(targets, 1):
        cid = pick_representative_cardid(idx, folder)
        if not cid:
            fetched[folder] = {"cardID": None, "value": None,
                               "status": "no_cardID_in_folder"}
            n_folders_no_value += 1
            continue
        try:
            val, _detail = fetch_set_name_official(cid)
        except Exception as e:
            fetched[folder] = {"cardID": cid, "value": None,
                               "status": f"fetch_error: {e}"}
            n_folders_no_value += 1
            continue

        if not val:
            fetched[folder] = {"cardID": cid, "value": None,
                               "status": "fetch_returned_none"}
            n_folders_no_value += 1
            continue

        fetched[folder] = {"cardID": cid, "value": val, "status": "ok"}

        rows = idx[folder]["rows"]
        for pid, _cid, before in rows:
            before_after.append({
                "folder": folder, "product_id": pid,
                "before": before, "after": val,
                "cardID_used_for_fetch": cid,
            })
            conn.execute(
                "UPDATE products SET set_name_official=?, updated_at=? "
                "WHERE category=? AND product_id=?",
                (val, datetime.now().isoformat(timespec="seconds"),
                 CATEGORY, pid),
            )
            n_updated_rows += 1
        n_folders_updated += 1
        conn.commit()

        if i % 20 == 0:
            print(f"  ... {i}/{len(targets)} folders processed "
                  f"(updated={n_folders_updated} no_value={n_folders_no_value})",
                  flush=True)

    finished = datetime.now().isoformat(timespec="seconds")
    stem = f"phase1_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    (out_dir / f"{stem}_before_after.json").write_text(
        json.dumps(before_after, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (out_dir / f"{stem}_folder_values.json").write_text(
        json.dumps(fetched, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return {
        "started_at": started, "finished_at": finished,
        "target_folders": len(targets),
        "folders_updated": n_folders_updated,
        "folders_no_value": n_folders_no_value,
        "rows_updated": n_updated_rows,
        "before_after_path": str(out_dir / f"{stem}_before_after.json"),
        "folder_values_path": str(out_dir / f"{stem}_folder_values.json"),
        "source_tag": SOURCE_TAG,
    }


# ============================================================================
# CLI
# ============================================================================
def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--plan", action="store_true",
                     help="対象 folder 一覧 (fetch なし / DB 書込なし)")
    grp.add_argument("--smoke", action="store_true",
                     help="smoke test 5件 fetch (DB 書込なし)")
    grp.add_argument("--phase1", action="store_true",
                     help="Phase 1 本実行 (要 --confirm)")
    ap.add_argument("--confirm", action="store_true",
                    help="--phase1 実行時の safety switch")
    ap.add_argument("--out-dir",
                    default="C:/dev/iMak_data/catalog/set_name_official_backfill",
                    help="before/after JSON 出力先")
    args = ap.parse_args()

    conn = _api._connect()

    if args.plan:
        print(json.dumps(build_plan(conn), ensure_ascii=False, indent=2))
        return

    if args.smoke:
        results = run_smoke(conn)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if args.phase1:
        if not args.confirm:
            print("ERROR: --phase1 は --confirm と同時指定必須 (誤操作防止)",
                  file=sys.stderr)
            sys.exit(2)
        report = run_phase1(conn, Path(args.out_dir))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
