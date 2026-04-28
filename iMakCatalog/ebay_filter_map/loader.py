"""ebay_filter_map yaml → SQLite ロード.

各カテゴリの `{category}.yaml` を読み込み、`api.register_filter_map()` 経由で
products.sqlite の ebay_filter_map テーブルに upsert する。

yaml フォーマット:

```yaml
# ebay_filter_map/one_piece.yaml
category: one_piece_tcg

set:
  # source_value は scrapers が保存する set_name_official (公式原文) と完全一致させる
  - source: "BOOSTER PACK -ROMANCE DAWN- [OP-01]"
    ebay: "Romance Dawn"
    year: 2022      # eBay Item Specifics 'Year Manufactured' 用
  - source: "BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]"
    ebay: "Wings of the Captain"
    year: 2024

# set_code ベースのマップ (set_name_official に [OP-06] 等が含まれていれば抽出して引ける)
set_code:
  - source: "OP-01"
    ebay: "Romance Dawn"
    year: 2022

rarity:
  - source: "C"
    ebay: "Common"
  - source: "SR"
    ebay: "Super Rare"
```

CLI:
    python ebay_filter_map/loader.py one_piece           # one_piece.yaml をロード
    python ebay_filter_map/loader.py --all               # 全 yaml をロード
    python ebay_filter_map/loader.py --dump one_piece    # DB から該当カテゴリを yaml 形式で出力
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("⚠️ pyyaml が必要です。 `pip install pyyaml`", file=sys.stderr)
    raise

# api.py を import するため親ディレクトリを path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

YAML_DIR = Path(__file__).resolve().parent


# ============================================================================
# load
# ============================================================================
def load_yaml(yaml_path: Path) -> dict:
    """yaml ファイルを読み込んで dict を返す."""
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path} のトップレベルは mapping でなければならない")
    if "category" not in data:
        raise ValueError(f"{yaml_path} に 'category' フィールドが無い")
    return data


def register_from_data(data: dict, dry_run: bool = False) -> dict:
    """yaml から読み込んだ dict を ebay_filter_map に登録.

    Returns: {field: count, ...}
    """
    category = data["category"]
    counts: dict[str, int] = {}
    for field, entries in data.items():
        if field == "category":
            continue
        if not isinstance(entries, list):
            continue
        n = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_value = entry.get("source")
            ebay_value = entry.get("ebay")
            if not source_value or ebay_value is None:
                print(f"  ⚠️ skip incomplete entry in {field}: {entry!r}")
                continue
            note_parts = []
            if entry.get("year") is not None:
                note_parts.append(f"year={entry['year']}")
            if entry.get("note"):
                note_parts.append(str(entry["note"]))
            note = "; ".join(note_parts) if note_parts else None
            if dry_run:
                print(f"  [dry] {category}/{field}: {source_value!r} → {ebay_value!r}"
                      f"{(' (' + note + ')') if note else ''}")
            else:
                api.register_filter_map(
                    category=category,
                    field=field,
                    source_value=str(source_value),
                    ebay_value=str(ebay_value),
                    note=note,
                )
            n += 1
        counts[field] = n
    return counts


def load_file(yaml_path: Path, dry_run: bool = False) -> dict:
    print(f"loading {yaml_path.name} ...")
    data = load_yaml(yaml_path)
    counts = register_from_data(data, dry_run=dry_run)
    total = sum(counts.values())
    print(f"  {data['category']}: {counts} (total {total})")
    return counts


def load_all(dry_run: bool = False) -> None:
    yamls = sorted(YAML_DIR.glob("*.yaml"))
    if not yamls:
        print(f"no yaml files in {YAML_DIR}")
        return
    for yp in yamls:
        load_file(yp, dry_run=dry_run)


# ============================================================================
# dump (DB → yaml 雛形)
# ============================================================================
def dump_category(category: str) -> str:
    """DB の ebay_filter_map から該当カテゴリを yaml 形式で出力.

    既存マップの確認 / 編集前のバックアップ用.
    """
    conn = sqlite3.connect(api._DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT field, source_value, ebay_value, note FROM ebay_filter_map "
        "WHERE category = ? ORDER BY field, source_value",
        (category,),
    ).fetchall()
    conn.close()

    by_field: dict[str, list[dict]] = {}
    for r in rows:
        entry = {"source": r["source_value"], "ebay": r["ebay_value"]}
        if r["note"]:
            entry["note"] = r["note"]
        by_field.setdefault(r["field"], []).append(entry)

    out = {"category": category, **by_field}
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)


def dump_unique_set_names(category: str) -> list[str]:
    """products テーブルから該当カテゴリの set_name_official を全て unique で取り出す.

    --full 完走後に「yaml に書き起こすべき公式 set 名一覧」を得るためのヘルパー.
    """
    conn = sqlite3.connect(api._DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT set_name_official FROM products "
        "WHERE category = ? AND set_name_official IS NOT NULL "
        "ORDER BY set_name_official",
        (category,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ============================================================================
# CLI
# ============================================================================
def main():
    p = argparse.ArgumentParser(description="ebay_filter_map yaml ↔ DB 同期")
    p.add_argument("name", nargs="?", help="カテゴリ名 (例: one_piece) — 対応 yaml をロード")
    p.add_argument("--all", action="store_true", help="ebay_filter_map/*.yaml を全部ロード")
    p.add_argument("--dump", metavar="CATEGORY",
                   help="DB → yaml 形式で stdout 出力 (例: one_piece_tcg)")
    p.add_argument("--list-sets", metavar="CATEGORY",
                   help="products テーブルから該当カテゴリの unique set_name_official 一覧を出力")
    p.add_argument("--dry-run", action="store_true", help="DB に書かない")
    args = p.parse_args()

    if args.list_sets:
        names = dump_unique_set_names(args.list_sets)
        print(f"# {args.list_sets}: {len(names)} unique set_name_official\n")
        for n in names:
            print(f"  - {n!r}")
        return

    if args.dump:
        print(dump_category(args.dump))
        return

    if args.all:
        load_all(dry_run=args.dry_run)
        return

    if args.name:
        path = YAML_DIR / f"{args.name}.yaml"
        if not path.exists():
            print(f"⚠️ {path} not found", file=sys.stderr)
            sys.exit(1)
        load_file(path, dry_run=args.dry_run)
        return

    p.print_help()


if __name__ == "__main__":
    main()
