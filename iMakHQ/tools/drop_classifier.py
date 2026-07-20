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


def rescued_subjects(log):
    """reject 直後に fallback で救済された PSA subject を集める (純関数)。

    救済ログは fallback の種類ごとに**行の形が違う**:
      promo  : "iMakCatalog hit (promo fallback): OP01-013_p1 サンジ (Subject='SANJI' ... と一致 ...)"
      reprint: "iMakCatalog hit (reprint fallback): OP10-030_OP13_p2 Smoker (PSA set=OP13 の再録版、1件中)"
    reprint 側は Subject を持たないため subject 名では突合できない。両者に共通するのは
    **reject の直後行に fallback hit が出る**構造(生成器が reject→即 fallback 試行するため)。
    → 文言 ('promo') ではなく構造で救済判定する。'promo fallback' だけを見ていたため
      reprint fallback 救済品を drop に二重計上した 2026-07-17 の再発を構造的に防ぐ
      (= 新種の fallback が増えても文言追従なしで拾える)。

    fail-closed: 隣接していなければ救済とみなさない。取りこぼしは件数不一致=警告で surface
    されるだけだが、誤って救済扱いにすると本物の drop が消えて silent drop になる(より危険)。
    """
    rescued = set()
    lines = (log or "").splitlines()
    for i, ln in enumerate(lines):
        m = re.search(r"ID hit\s+(\S+).*?Subject\s+'([^']+)'.*?不一致", ln)
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if re.search(r"iMakCatalog hit \([^)]*fallback\)", nxt):
            rescued.add(m.group(2))
    return rescued


def classify_drops(log, *, set_exists, card_exists=None):
    """生成ログ → [{item, class, cause, act}] (純関数, catalog照会は注入)。

    set_exists(prefix)->bool: そのセット接頭辞のカードが catalog に1件でも在るか。
    card_exists(card_id)->bool: その個別IDが在るか(任意)。
    """
    out = []
    seen = set()
    # fallback で救済された subject(= ID不一致 reject の後に別variantで build 成功)は
    # drop に数えない(二重計上=件数照合のノイズ・オオカミ少年化を防ぐ。2026-07-10 promo / 2026-07-17 reprint)。
    rescued = rescued_subjects(log)
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
                out.append({"item": cid, "class": "収録漏れ", "cert": None,
                            "cause": f"収録漏れ(セット {setp} は対象内だが {cid} が欠番)",
                            "act": f"catalog拡充依頼: {cid} を追加"})
            else:
                out.append({"item": cid, "class": "scope外", "cert": None,
                            "cause": f"scope外(セット {setp} 自体が catalog 未収録)",
                            "act": f"判断: {setp} を新規収録するか / 再試行停止(scope-out)"})
            continue

        # ② 名前不一致 reject: "ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject"
        m = re.search(r"ID hit\s+(\S+).*?Subject\s+'([^']+)'.*?不一致", s)
        if m:
            cid, subj = m.group(1), m.group(2)
            if subj in rescued:
                continue   # reject後に fallback で救済=build成功 → dropではない(二重計上回避)
            key = f"{cid}|{subj}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"item": cid, "class": "promo衝突", "cert": None,
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
            out.append({"item": cid, "class": "該当なし(catalog欠)", "cert": m.group(1),
                        "cause": "viewer候補は出たが正カードがcatalogに無い(該当なし)",
                        "act": "catalog拡充: 該当カードを追加(NONE→自動宿題化される運用)"})
            continue

        # ④ 既出品/目視済 除外(件数行)= 正常
        m = re.search(r"(既出品|目視済)[^\n]*?除外[:：]\s*(\d+)\s*件", s)
        if m:
            out.append({"item": f"{m.group(1)} {m.group(2)}件", "class": "正常",
                        "cause": f"{m.group(1)}のため除外(出品済/cooldown)", "act": "対応不要(正常)"})
            continue

        # ⑤ 番号なし DON!! skip: "reason=no_card_number_don ... (cert 154458065, subject='DON!! CARD')"
        #    DON!! は標準番号を持たないが set_code+treatment(rarity)で一意に識別可能。
        #    番号必須の fail-closed が誤除外し、しかも silent drop になっていた(2026-07-10 見過ごし発覚)。
        #    → 「識別可・要catalog対応」として明示し問題提起へ(silent drop 禁止)。
        m = re.search(r"no_card_number_don.*?cert\s+(\d+).*?subject='([^']+)'", s)
        if m:
            cid = "#" + m.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"item": cid, "class": "DON!!識別可(要catalog)", "cert": m.group(1),
                        "cause": f"DON!!カード('{m.group(2)}')=番号なしだが set+処理(rarity)で識別可・catalog未対応で誤除外",
                        "act": "catalog に DON!! を set_code+treatment(rarity)で登録 → 出品可(cert cache に set/rarity 有り)"})
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

    # 落ちは **cert 単位** で数える(2026-07-20)。
    # 同じ1枚が「未登録: CP4-075」(card_id経路) と「目視未確定: #156576106」(cert経路) の
    # 二本のログ行で拾われ、seen が別キーのため二重計上されていた（実ログで CP4-075 = cert
    # 156576106 と確定）。cert を持つ finding が drop の実体で、card_id だけの finding
    # (収録漏れ/scope外/promo衝突) は **その drop の理由説明** なので計上しない。
    # cert 情報が一切無いログ(旧形式)では従来どおり件数で数える(後方互換・取りこぼし防止)。
    actionable = [d for d in drops if d.get("class") != "正常"]
    cert_drops = {d.get("cert") for d in actionable if d.get("cert")}
    if cert_drops:
        n_drop = len(cert_drops)
    else:
        n_drop = len(actionable)
    accounted = success + n_drop
    if processed == accounted:
        return f"✅ 件数照合OK: 処理{processed} = 成功{success} + 落ち{n_drop}"
    return (f"⚠️ 件数不一致(silent drop余地): 処理{processed} ≠ 成功{success}+落ち{n_drop} "
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
