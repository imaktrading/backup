# -*- coding: utf-8 -*-
"""PSA再仕入れ 待ち台帳 — 再仕入れ不能(End候補)を消さず毎回再チェックする。

再仕入れ不能 = 今この瞬間 Mercari/SNKRDUNK に PSA10出品が無いだけ。供給は動的なので、
後で出品が出れば RESTOCK できる。ファネルの需要が減って絞り込みから外れると見失う
("もったいない")ため、End候補を台帳に蓄積し、ファネルとは別に毎回再チェックする。
目視確定済(KEY付与済)なので再目視は不要。

状態同期の安全原則(fail-OPENを許さない)に沿い、待ち行は供給が戻る/明示retireまで消さない。
I/O は持たず純関数。ledger 行は dict(列名キー)。
"""

LEDGER_HEADER = ["初出日", "最終確認日", "status", "再チェック回数",
                 "itemID", "KEY", "card_no", "title", "ebay_url"]

ST_WAIT = "待ち(供給なし)"
ST_REVIVED = "復活可(供給あり→RESTOCK)"
# ★2026-07-24: 取得失敗(メルカリtimeout等)=在庫不明。End候補(供給なし確定)と区別して蓄積し
# 毎回再取得する。台帳から漏れて追跡が切れる「孤児」を防ぐ(ユーザー指摘: 世代でリセットするな)。
ST_UNKNOWN = "在庫不明(取得失敗・要再取得)"


def ledger_from_rows(rows2d):
    """台帳タブ 2d(header含む) → [dict]。空/ヘッダ不一致は []。"""
    if not rows2d or rows2d[0][:4] != LEDGER_HEADER[:4]:
        return []
    hdr = rows2d[0]
    out = []
    for r in rows2d[1:]:
        if not any(r):
            continue
        out.append({hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))})
    return out


def reconcile(prev, end_candidates, resourceable_itemids, today, held_candidates=None):
    """前回台帳 + 今回(End候補 / 再仕入れ可 / 在庫不明) を突合 → (新台帳rows, stats)。

    Args:
        prev: [dict] 前回台帳
        end_candidates: [{itemID,key,card_no,title,ebay_url}] 今回 再仕入れ不能(End候補=供給なし確定)
        resourceable_itemids: set 今回 再仕入れ可になった itemID
        today: 'YYYY-MM-DD'
        held_candidates: [{...}] 今回 取得失敗=在庫不明(End候補に倒さず蓄積・毎回再取得)
    Returns:
        (ledger:[dict], stats:{new,still_waiting,revived,unknown,total_wait})
    """
    by_id = {r.get("itemID"): dict(r) for r in prev if r.get("itemID")}
    stats = {"new": 0, "still_waiting": 0, "revived": 0, "unknown": 0}

    for ec in end_candidates:
        iid = ec.get("itemID") or ""
        if not iid:
            continue
        cur = by_id.get(iid)
        if cur is None:
            cur = {"初出日": today, "再チェック回数": "1"}
            stats["new"] += 1
        else:
            cur["再チェック回数"] = str(int(cur.get("再チェック回数") or 0) + 1)
            cur.setdefault("初出日", today)
            stats["still_waiting"] += 1
        cur.update({
            "最終確認日": today, "status": ST_WAIT, "itemID": iid,
            "KEY": ec.get("key", "") or cur.get("KEY", ""),
            "card_no": ec.get("card_no", "") or cur.get("card_no", ""),
            "title": ec.get("title", "") or cur.get("title", ""),
            "ebay_url": ec.get("ebay_url", "") or cur.get("ebay_url", ""),
        })
        by_id[iid] = cur

    # 在庫不明(取得失敗)= 台帳に無ければ ST_UNKNOWN で新規蓄積(=孤児防止)、在れば recheck++で
    # 既存 status を維持(WAIT/REVIVED を downgrade しない=前回の確定情報を捨てない)。
    for hc in (held_candidates or []):
        iid = hc.get("itemID") or ""
        if not iid:
            continue
        cur = by_id.get(iid)
        if cur is None:
            by_id[iid] = {
                "初出日": today, "最終確認日": today, "status": ST_UNKNOWN,
                "再チェック回数": "1", "itemID": iid, "KEY": hc.get("key", ""),
                "card_no": hc.get("card_no", ""), "title": hc.get("title", ""),
                "ebay_url": hc.get("ebay_url", ""),
            }
            stats["unknown"] += 1
        else:
            cur["再チェック回数"] = str(int(cur.get("再チェック回数") or 0) + 1)
            cur["最終確認日"] = today   # status は維持(downgrade しない)

    # 供給が戻った(再仕入れ可)= 待ち/在庫不明→復活可。台帳に在る itemID のみ対象。
    for iid in resourceable_itemids:
        cur = by_id.get(iid)
        if cur is not None and cur.get("status") != ST_REVIVED:
            cur["status"] = ST_REVIVED
            cur["最終確認日"] = today
            stats["revived"] += 1

    ledger = list(by_id.values())
    stats["total_wait"] = sum(1 for r in ledger if r.get("status") in (ST_WAIT, ST_UNKNOWN))
    return ledger, stats


def recheck_targets(ledger):
    """status=待ち の行 → 次回 再チェックすべき対象 [{itemID,key,card_no,title,ebay_url}]。

    復活可(供給あり)は RESTOCK 待ちなので再探索不要。retire(台帳から削除)も対象外。
    """
    out = []
    for r in ledger:
        if r.get("status") not in (ST_WAIT, ST_UNKNOWN):   # 在庫不明も毎回再取得対象
            continue
        out.append({"itemID": r.get("itemID", ""), "key": r.get("KEY", ""),
                    "card_no": r.get("card_no", ""), "title": r.get("title", ""),
                    "ebay_url": r.get("ebay_url", "")})
    return out


def to_tab_rows(ledger):
    """[dict] → タブ書込用 2d。復活可を上(要対応)、次に再チェック回数 desc。"""
    def _key(r):
        return (r.get("status") != ST_REVIVED,            # 復活可を先頭
                -int(r.get("再チェック回数") or 0),
                r.get("最終確認日") or "")
    rows = [LEDGER_HEADER]
    for r in sorted(ledger, key=_key):
        rows.append([r.get(c, "") for c in LEDGER_HEADER])
    return rows
