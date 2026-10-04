#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""値段が大きく **上がった** 出品を「補優先」の先頭に入れる (2026-10-05 ユーザー指示・ADV 依頼)。

ユーザー「価格変動 大きいものは、優先的に補を探しに行かないとだめだよ」。
    実例: 358853881132 コイキング $224.98 → $736.98 (3.3倍)。スニダンに ¥17,000 前後が5件出ていた。
    値段は仕入値から決まる (cost-plus) ので、**跳ねた = 安い仕入元が切れて高い1本しか残っていない合図**。
ユーザー「下がった方は優先しなくていいよ。優先ばかり増えると、優先の意味が薄れる」→ **上がった分だけ**。

どこから取るか: リバイスくんが毎朝出す C:/dev/iMak_data/revise/price_moves_high.json
    (item_id / old_usd / new_usd / ratio …)。**ratio >= MIN_RATIO (1.5)** だけ (10/5 朝: 269件中9件)。
    1.5 は仮の線。毎朝10件前後に収まるよう数日見て動かす。**緩めない方向で** (ユーザーの意図は優先を増やしすぎない)。
入れた物は JUMP_PATH に3日残す (その間に補探索が回る)。棚② の補優先 (shelf2_hoju_priority.json) とは
ファイルを分ける = どちらから来たかで効き目を数えられる。
"""
from __future__ import annotations

import datetime
import json
import os

MOVES_PATH = r"C:/dev/iMak_data/revise/price_moves_high.json"
JUMP_PATH = r"C:/dev/iMak_data/hq/price_jump_priority.json"
MIN_RATIO = 1.5
KEEP_DAYS = 3


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def pick_jumps(items, day, min_ratio=MIN_RATIO):
    """リバイスくんの値動き → 上がった物 [{iid, from, to, ratio, date}] (純関数・倍率の大きい順)。"""
    out = []
    for x in items or []:
        try:
            ratio = float(x.get("ratio") or 0)
        except (TypeError, ValueError):
            continue
        if ratio >= min_ratio and x.get("item_id"):
            out.append({"iid": str(x["item_id"]), "from": x.get("old_usd"), "to": x.get("new_usd"),
                        "ratio": ratio, "date": day, "title": x.get("title") or ""})
    out.sort(key=lambda j: -j["ratio"])
    return out


def merge(old_items, jumps, today, keep_days=KEEP_DAYS):
    """今日の分を先頭に、KEEP_DAYS 日以内の前の分を後ろに (純関数・同じ出品は1回)。"""
    new_ids = {j["iid"] for j in jumps}
    kept = []
    for x in old_items or []:
        try:
            age = (today - datetime.date.fromisoformat(x["date"])).days
        except (KeyError, ValueError, TypeError):
            continue
        if age < keep_days and x.get("iid") not in new_ids:
            kept.append(x)
    return jumps + kept


def refresh(now=None):
    """リバイスくんの値動きが新しくなっていれば JUMP_PATH を作り直す (I/O・何度呼んでも同じ)。無ければ何もしない。"""
    moves = _load(MOVES_PATH, None)
    if not moves or not moves.get("at"):
        return None
    cur = _load(JUMP_PATH, {"items": []})
    if cur.get("source_at") == moves["at"]:
        return cur
    now = now or datetime.datetime.now()
    day = str(moves["at"])[:10]
    data = {"at": now.isoformat(timespec="seconds"), "source_at": moves["at"], "min_ratio": MIN_RATIO,
            "items": merge(cur.get("items"), pick_jumps(moves.get("items"), day), now.date())}
    _save(JUMP_PATH, data)
    return data


def load_jump_priority():
    """補優先に入れる itemID (倍率の大きい順)。まずリバイスくんの値動きから作り直してから読む。"""
    try:
        refresh()
    except Exception:                                          # noqa: BLE001
        pass
    return [x["iid"] for x in _load(JUMP_PATH, {"items": []}).get("items") or [] if x.get("iid")]


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    d = refresh() or _load(JUMP_PATH, {"items": []})
    for x in d.get("items") or []:
        print(f"{x['date']} {x['iid']} ×{x['ratio']:.2f} ${x['from']} → ${x['to']} {x.get('title', '')[:30]}")
    print(f"補優先 (値段が上がった) {len(d.get('items') or [])}件 → {JUMP_PATH}")
