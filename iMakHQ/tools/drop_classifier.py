#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成ログの「CSVにならなかった分」を 原因 + 対策案 に自動分類 = 問題提起 (2026-06-30)。

ユーザー方針: Act(実際の修正)は人が判断・指示する。**問題提起(原因+対策案の提示)を自動化**する
ことが重要(pdca_spiral_up: Check止まり禁止、原因→対策まで提起して初めてPDCA)。

drop 行を catalog 照会で分類:
  - catalog未登録 (SET-NUM): セットが catalog に在る→「収録漏れ→拡充依頼」/ 無い→「scope外→収録判断/再試行停止」
  - 名前不一致 reject:        promo番号衝突(同番号別キャラ)→「catalog variant追加 + subject lookup」
  - 目視未確定:               viewer候補なし/曖昧 →「cooldown再浮上 / catalog候補確認」
  - 既出品/目視済 除外:        正常(対応不要)

catalog 照会(set_exists/card_exists)は注入可=テスト可。
"""
import re


def classify_drops(log, *, set_exists, card_exists=None):
    """生成ログ → [{item, class, cause, act}] (純関数, catalog照会は注入)。

    set_exists(prefix)->bool: そのセット接頭辞のカードが catalog に1件でも在るか。
    card_exists(card_id)->bool: その個別IDが在るか(任意)。
    """
    out = []
    seen = set()
    for ln in (log or "").splitlines():
        s = ln.strip()
        if not s:
            continue

        # ① catalog未登録: "未登録: SM9a-067 → Skip"
        m = re.search(r"未登録[:：]\s*([A-Za-z0-9]+-\w+)", s)
        if m:
            cid = m.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            setp = cid.split("-")[0]
            if set_exists(setp):
                out.append({"item": cid, "class": "収録漏れ",
                            "cause": f"収録漏れ(セット {setp} は対象内だが {cid} が欠番)",
                            "act": f"catalog拡充依頼: {cid} を追加"})
            else:
                out.append({"item": cid, "class": "scope外",
                            "cause": f"scope外(セット {setp} 自体が catalog 未収録)",
                            "act": f"判断: {setp} を新規収録するか / 再試行停止(scope-out)"})
            continue

        # ② 名前不一致 reject: "ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject"
        m = re.search(r"ID hit\s+(\S+).*?Subject\s+'([^']+)'.*?不一致", s)
        if m:
            cid, subj = m.group(1), m.group(2)
            key = f"{cid}|{subj}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"item": cid, "class": "promo衝突",
                        "cause": f"promo番号衝突({cid} は catalog と別キャラ・PSA='{subj}')",
                        "act": f"catalog に {cid} の '{subj}' variant 追加 + 番号+subject で lookup"})
            continue

        # ③ 目視未確定: "スキップ(目視未確定): #139291730" (区切り記号を跨いで cert番号を拾う)
        m = re.search(r"目視未確定\D*?(\d{6,})", s)
        if m:
            cid = "#" + m.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"item": cid, "class": "該当なし(catalog欠)",
                        "cause": "viewer候補は出たが正カードがcatalogに無い(該当なし)",
                        "act": "catalog拡充: 該当カードを追加(NONE→自動宿題化される運用)"})
            continue

        # ④ 既出品/目視済 除外(件数行)= 正常
        m = re.search(r"(既出品|目視済)[^\n]*?除外[:：]\s*(\d+)\s*件", s)
        if m:
            out.append({"item": f"{m.group(1)} {m.group(2)}件", "class": "正常",
                        "cause": f"{m.group(1)}のため除外(出品済/cooldown)", "act": "対応不要(正常)"})
            continue
    return out


def render_problem_report(drops):
    """分類済み drop → 問題提起テキスト(原因+対策案)。class順にまとめる。"""
    if not drops:
        return ""
    actionable = [d for d in drops if d["class"] != "正常"]
    lines = ["📋 問題提起: CSVにならなかった分 — 原因と対策案(判断は人)"]
    from collections import Counter
    cnt = Counter(d["class"] for d in drops)
    lines.append("  内訳: " + " / ".join(f"{k}{v}" for k, v in cnt.items()))
    for d in actionable[:20]:
        lines.append(f"  ・[{d['class']}] {d['item']}")
        lines.append(f"      原因: {d['cause']}")
        lines.append(f"      対策案: {d['act']}")
    return "\n".join(lines)


def reconcile_counts(log, drops):
    """処理N件 vs (成功 + actionable落ち) を照合し silent drop 余地を検出 (純関数, test可)。

    ユーザー方針(2026-06-30): 「入力N = CSV X + 落ち Y」が合わなければ、拾えてない drop=silent drop
    がある証拠。合わない時はそれ自体を問題提起する(=取りこぼしゼロ保証)。
    """
    import re

    def _n(pat):
        m = re.search(pat, log or "")
        return int(m.group(1)) if m else None
    processed = _n(r"(\d+)\s*件を処理")
    if processed is None:
        return ""
    success = _n(r"成功[:：]\s*(\d+)\s*件") or 0
    actionable = sum(1 for d in drops if d.get("class") != "正常")
    accounted = success + actionable
    if processed == accounted:
        return f"✅ 件数照合OK: 処理{processed} = 成功{success} + 落ち{actionable}"
    return (f"⚠️ 件数不一致(silent drop余地): 処理{processed} ≠ 成功{success}+落ち{actionable} "
            f"(差{processed - accounted}件) → 拾えてない drop の可能性・要確認")


def make_catalog_lookups(catalog_db_path):
    """本番用: catalog sqlite から set_exists/card_exists を作る (I/O)。"""
    import sqlite3
    con = sqlite3.connect(catalog_db_path)

    def set_exists(prefix):
        try:
            row = con.execute("SELECT 1 FROM products WHERE product_id LIKE ? LIMIT 1",
                              (prefix + "-%",)).fetchone()
            return row is not None
        except Exception:
            return True   # 照会失敗時は fail-safe(scope外と誤判定して捨てない)

    def card_exists(card_id):
        try:
            return con.execute("SELECT 1 FROM products WHERE product_id=? LIMIT 1",
                               (card_id,)).fetchone() is not None
        except Exception:
            return False
    return set_exists, card_exists
