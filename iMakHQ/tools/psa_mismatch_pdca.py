# -*- coding: utf-8 -*-
"""PSA再仕入れ 不一致 PDCA — 確認ゲートで OFF にした「①現物 vs ②catalog 不一致」を
台帳に蓄積し、原因別に振り分け、前回比トレンド/再発/解決を検知する。

Check止まりにしない(pdca_spiral_up_expectation): 検出 → 台帳 → 原因別ルーティング →
再発/解決トレンド、まで回す。I/O は持たず純関数。ledger 行は dict(列名キー)。

ルーティング(原因→対処先):
  catalog  : ②catalog が別カード(KEY誤解決/画像不備) → Catalog修正依頼
  cert     : ①現物が別カード(商品管理シートI列 cert# 誤) → シートI列是正
  listing  : ①②一致だが売った物と違う(出品時の誤同定) → eBay出品revision
  unknown  : 判断不能 → 要調査
"""

LEDGER_HEADER = ["初出日", "最終検知日", "status", "再発回数", "原因", "振り分け先",
                 "itemID", "cert#", "KEY", "card_no", "title",
                 "現物PSA_URL", "catalog_URL", "ebay_url"]

ROUTE_LABEL = {
    "catalog": "Catalog修正依頼",
    "cert": "商品管理シートI列cert是正",
    "listing": "eBay出品revision",
    "unknown": "要調査",
}


def classify_route(reason):
    """UI の原因コード → 振り分けキー。未知は unknown。"""
    r = (reason or "").strip().lower()
    return r if r in ("catalog", "cert", "listing") else "unknown"


def ledger_from_rows(rows2d):
    """台帳タブ 2d(header含む) → [dict(列名→値)]。空/ヘッダ不一致は []。"""
    if not rows2d or rows2d[0][:3] != LEDGER_HEADER[:3]:
        return []
    hdr = rows2d[0]
    out = []
    for r in rows2d[1:]:
        if not any(r):
            continue
        out.append({hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))})
    return out


def reconcile(prev, rejects, confirmed_itemids, today):
    """前回台帳 + 今回(不一致 rejects / 一致 confirmed) を突合 → (新台帳rows, stats)。

    Args:
        prev: [dict] 前回台帳
        rejects: [{itemID,cert,key,card_no,title,reason,psa_image,catalog_image,ebay_url}]
        confirmed_itemids: set 今回 一致(=確定)した itemID
        today: 'YYYY-MM-DD'
    Returns:
        (ledger:[dict], stats:{new,recurring,resolved,reopened,open,by_route:{}})
    """
    by_id = {r.get("itemID"): dict(r) for r in prev if r.get("itemID")}
    stats = {"new": 0, "recurring": 0, "resolved": 0, "reopened": 0, "by_route": {}}

    for rj in rejects:
        iid = rj.get("itemID") or ""
        route = classify_route(rj.get("reason"))
        stats["by_route"][route] = stats["by_route"].get(route, 0) + 1
        cur = by_id.get(iid)
        if cur is None:                                  # 新規不一致
            cur = {"初出日": today, "再発回数": "1"}
            stats["new"] += 1
        else:                                            # 既出
            was_resolved = str(cur.get("status")) == "解決"
            cur["再発回数"] = str(int(cur.get("再発回数") or 0) + 1)
            if was_resolved:
                stats["reopened"] += 1                    # 解決→再発(直らず再出)
            else:
                stats["recurring"] += 1
            cur.setdefault("初出日", today)
        cur.update({
            "最終検知日": today, "status": "未対処",
            "原因": rj.get("reason") or "", "振り分け先": ROUTE_LABEL.get(route, route),
            "itemID": iid, "cert#": rj.get("cert", ""), "KEY": rj.get("key", ""),
            "card_no": rj.get("card_no", ""), "title": rj.get("title", ""),
            "現物PSA_URL": rj.get("psa_image", ""), "catalog_URL": rj.get("catalog_image", ""),
            "ebay_url": rj.get("ebay_url", ""),
        })
        by_id[iid] = cur

    for iid in confirmed_itemids:
        cur = by_id.get(iid)
        if cur is not None and str(cur.get("status")) != "解決":
            cur["status"] = "解決"
            cur["最終検知日"] = today
            stats["resolved"] += 1

    ledger = list(by_id.values())
    stats["open"] = sum(1 for r in ledger if str(r.get("status")) != "解決")
    return ledger, stats


def to_tab_rows(ledger):
    """[dict] → タブ書込用 2d。未対処を上に、再発回数 desc、最終検知日 desc でソート。"""
    def _key(r):
        return (str(r.get("status")) == "解決",
                -int(r.get("再発回数") or 0),
                r.get("最終検知日") or "")
    rows = [LEDGER_HEADER]
    for r in sorted(ledger, key=_key):
        rows.append([r.get(c, "") for c in LEDGER_HEADER])
    return rows


def route_buckets(ledger):
    """未対処のみ 振り分けキー別に集約 → {route: [dict,...]}。Act(対処)で使う。"""
    out = {}
    for r in ledger:
        if str(r.get("status")) == "解決":
            continue
        route = classify_route(r.get("原因"))
        out.setdefault(route, []).append(r)
    return out


def build_catalog_request_md(rows, today, requester="HQ"):
    """catalog誤 行 → Catalog worktree への修正依頼書 markdown 本文。"""
    lines = [
        f"# PSA再仕入れ 不一致(catalog側)修正依頼 — {today}",
        "",
        f"- 依頼日: {today}",
        f"- 依頼者: {requester}",
        "- 緊急度: 中(誤仕入れは確認ゲートで阻止済。SSOT是正が目的)",
        "- フェーズ: 調査+修正",
        "",
        "## 事象",
        "PSA再仕入れの目視確認ゲートで ②catalog を特定できなかった行。次のどちらか:",
        "  (A) 未収録: その card番号/カードが catalog に無い(②候補ゼロ) → **catalog追加**を願う",
        "      (例: プロモ/alt art/番号体系が標準外で product_id が無い、対象外シリーズ等)",
        "  (B) 変種違い: catalog に在るが ①現物(出品PSA)と別変種/画像違い → ①に合わせ**是正**を願う",
        "①現物=出品に使った実PSA画像が正。card_no/KEY が空の行は (A) 未収録の可能性が高い。",
        "",
        "## 対象",
        "| itemID | card_no | KEY | 現物PSA画像 | catalog画像 | title |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.get('itemID','')} | {r.get('card_no','')} | {r.get('KEY','')} | "
            f"{r.get('現物PSA_URL','')} | {r.get('catalog_URL','')} | {r.get('title','')} |")
    lines += ["", "## 期待アクション",
              "- (A)未収録: catalog に product_id 追加(or 別名/番号体系を登録)。対象外シリーズなら明記",
              "- (B)変種違い: KEY誤解決なら商品管理シートAI列のKEY是正 / catalog画像を①現物と同変種に差替",
              "- 対応後、本依頼を `_processed.md` 化"]
    return "\n".join(lines) + "\n"
