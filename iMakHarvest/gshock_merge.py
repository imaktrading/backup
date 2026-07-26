"""gshock_merge - 複数仕入元(Amazon/ヨドバシ)を型番キーで 1行(主/補URL)にマージする純関数.

2026-07-26 POC (HQ 依頼 `..._multisource_merge_feasibility`)。
PSA の `hoju_url_from_dupes.compute_additions`(同KEY 2枚目URLを補URL枠に冪等追記)の
中間スプシ/LOW 版。 思想は同一: **既存保持・空枠のみ・満杯skip・冪等**。

分界 (HQ 確定):
  - Harvest = 補URL(データ)の AC-AG 冪等追記まで (= この関数が算出、 書込は runner)。
  - Inventory = D=○ 復活 / M=min(在庫あり 主+補) の **状態書換** (この関数は状態に触れない)。

この関数は **純関数** (I/O なし)。 在庫状態 (D 列) は一切変更しない。 補URL データの
追加計画と、 LOW 未収載の新規候補を返すだけ。
"""
from __future__ import annotations

from typing import Optional

MAX_SUPP_SLOTS = 5  # AC-AG = 補URL 5 枠


def _norm(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/").lower()


def compute_merge(
    existing_by_key: dict,
    new_items: list[dict],
    max_supp: int = MAX_SUPP_SLOTS,
) -> dict:
    """型番キーで 新規抽出 URL を既存 LOW 行の 補URL枠に冪等マージする計画を算出.

    Args:
        existing_by_key: {
            "<型番(大文字)>": {
                "primary_url": str,          # A 列 (主仕入元 URL)
                "supp_urls": list[str],      # AC-AG の既存補URL (空要素除く)
            }, ...
        }
        new_items: [{"model": str, "url": str, "source": str}, ...]
            (Amazon/ヨドバシ抽出の型番→URL。 source は "amazon"/"yodobashi" 等ラベル)
        max_supp: 補URL 枠数 (default 5 = AC-AG)

    Returns: {
        "supp_additions": {"<型番>": ["追加する補URL", ...]},  # 空枠のみ・冪等・満杯skip
        "new_candidates": [{"model","url","source"}, ...],     # LOW 未収載 (別出し)
        "skipped_dup": int,     # 既に主/補にある (冪等 skip)
        "skipped_full": int,    # 補枠満杯で入らなかった
    }
    在庫状態 (D 列) は touch しない (= Inventory 責務)。
    """
    supp_additions: dict[str, list[str]] = {}
    new_candidates: list[dict] = []
    skipped_dup = 0
    skipped_full = 0

    # 既存行の「使用済み URL 集合」を型番毎に構築 (主 + 既存補 + 本 batch で追加予定)
    used: dict[str, set[str]] = {}
    slots_left: dict[str, int] = {}
    for key, row in existing_by_key.items():
        k = key.upper()
        u = {_norm(row.get("primary_url"))}
        u |= {_norm(s) for s in (row.get("supp_urls") or []) if _norm(s)}
        u.discard("")
        used[k] = u
        slots_left[k] = max_supp - len([s for s in (row.get("supp_urls") or []) if _norm(s)])

    seen_new: set[tuple] = set()
    for it in new_items:
        model = (it.get("model") or "").strip().upper()
        url = (it.get("url") or "").strip()
        if not model or not url:
            continue
        nu = _norm(url)
        # batch 内重複 (同型番×同URL) は 1 回だけ扱う
        if (model, nu) in seen_new:
            continue
        seen_new.add((model, nu))

        if model not in used:
            new_candidates.append({"model": model, "url": url,
                                    "source": it.get("source", "")})
            continue
        if nu in used[model]:
            skipped_dup += 1              # 既に主/補にある → 冪等 skip
            continue
        if slots_left[model] <= 0:
            skipped_full += 1            # 補枠満杯 → skip (既存保持)
            continue
        supp_additions.setdefault(model, []).append(url)
        used[model].add(nu)
        slots_left[model] -= 1

    return {
        "supp_additions": supp_additions,
        "new_candidates": new_candidates,
        "skipped_dup": skipped_dup,
        "skipped_full": skipped_full,
    }
