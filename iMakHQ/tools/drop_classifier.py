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
import csv
import io
import re

# ============================================================================
# 構造的 drop 検出 (2026-08-01) — 「毎回どこかで件数不一致が出る」の根本対策
#
# 旧方式は **drop の種類ごとに正規表現を1本ずつ足す** 方式だった。新しい落ち方
# (selfcheck不合格・PSA取得失敗 等) が出るたび分類漏れ → 「⚠️件数不一致」だけが出て
# 中身が分からない、を繰り返していた (足し忘れが構造的に起きる = モグラ叩き)。
#
# 根本対策: drop の **集合を差分で決める**。
#     落ち = 処理した cert 全体(universe) − CSV に載った cert(成功)
# 正規表現は「集合の決定」から降格して **理由の説明** だけを担う。理由が付かなければ
# 「未分類(要調査)」として cert 付きで必ず表に出す。
# → 新種の落ち方が増えても、件数は定義上必ず合い、silent drop は原理的に発生しない。
# ============================================================================

# 処理対象 cert (universe): psa_to_csv.py:2842/2866 の "取得中(確認用): #<cert>..." / "取得中: #<cert>..."
_CERT_LINE = re.compile(r"取得中(?:\(確認用\))?\s*[:：]\s*#(\d{6,})")
# 生成 CSV の CustomLabel = "PSA10-<cert>" (= 成功して CSV に載った cert)
_CSV_CERT = re.compile(r"PSA10-(\d{6,})")
_CSV_PATH = re.compile(r"完了[!！]\s*出力\s*[:：]\s*(.+?\.csv)")


def processed_certs(log):
    """処理した cert の全集合 = universe (順序保持・純関数)。"""
    out, seen = [], set()
    for m in _CERT_LINE.finditer(log or ""):
        c = m.group(1)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def built_certs(csv_text):
    """CSV に載った cert (= 成功)。

    2026-08-09: CustomLabel は常に "PSA10-<cert>" ではない。仕入元が持つ ID
    (mercari の m36456934512 等) がそのまま入る行があり、その行を「成功」に数えられず
    **CSV に載っているのに落ちとして報告**していた (件数照合も 4→3 とズレたまま ✅OK と
    表示していた)。CustomLabel の形に頼らず **cert 列から拾う**のを主にする。
    """
    certs = set(_CSV_CERT.findall(csv_text or ""))
    if not csv_text:
        return certs
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text)))
    except Exception:
        return certs
    for row in rows:
        for key, val in (row or {}).items():
            if not key or "Certification Number" not in key:
                continue
            v = str(val or "").strip()
            if v.isdigit() and len(v) >= 6:
                certs.add(v)
    return certs


def csv_path_from_log(log):
    """生成ログ末尾の「完了！出力: <path>」から CSV パスを取る (無ければ空)。"""
    m = _CSV_PATH.search(log or "")
    return m.group(1).strip() if m else ""


def drop_reason(log, cert):
    """cert 1件が CSV に載らなかった理由をログから引く (純関数)。

    ここに該当が無くても **drop の集合からは外れない**。「未分類(要調査)」として出る。
    """
    c = re.escape(cert)

    # ⓪ PSA 取得失敗 ("取得中(確認用): #cert... 失敗")。
    #    取得できなかった cert は目視一覧にも「未確定」で載るため、①より先に判定しないと
    #    「catalog欠」に化けて **catalog に無駄な調査を積む** (2026-08-09 #143318406)。
    #    失敗時は PSA ページの内容が数十行 dump されてから「失敗」が出るので、
    #    **次の「取得中」までの範囲**で探す (直後 1 行だけ見ると取りこぼす)。
    if re.search(r"取得中(?:\(確認用\))?\s*[:：]\s*#%s(?:(?!取得中)[\s\S])*?失敗" % c, log):
        return {"class": "PSA取得失敗",
                "cause": "PSA サイトから cert データを取得できなかった(通信/Cloudflare/存在しない)",
                "act": "再走で回復するか確認。恒常的なら scrape 側を調査"}

    # ①-a catalog に実在するのに viewer が確定できなかった (= ②側の食い違い)。
    #     catalog 欠と混ぜると「カタログが直してくれない」に見えて原因を取り違える。
    if re.search(r"Skip missing_models \(catalog実在→viewer食い違い\)\D*?%s" % c, log):
        return {"class": "viewer食い違い(catalogに実在)",
                "cause": "catalog に該当カードが在るのに viewer 側で確定できなかった",
                "act": "②を修正 — viewer/adapter の同定経路を生成器と揃える"}

    # ①-b 画像が無くて目視できなかった (catalog 行は在るが images が空)。
    if re.search(r"画像が無く目視できない[^\n]*%s" % c, log):
        return {"class": "画像欠(catalogに実在)",
                "cause": "catalog に行は在るが画像が無く、viewer で現物と照合できない",
                "act": "catalog に画像追加を依頼 (自動で missing_models に流れる)"}

    # ① 目視未確定 (viewer で OK/CHOSEN が付かなかった) — psa_to_csv.py:2860
    if re.search(r"目視未確定\D*?%s" % c, log):
        return {"class": "該当なし(catalog欠)",
                "cause": "viewer候補は出たが正カードがcatalogに無い(該当なし)",
                "act": "catalog拡充: 該当カードを追加(NONE→自動宿題化される運用)"}

    # ② catalog未登録で入稿しない (fail-closed) — psa_to_csv.py:2897
    m = re.search(r"Skip \(catalog未登録[^)]*\)\D*?%s[^(]*\(([^)]*)\)" % c, log)
    if m:
        return {"class": "catalog未登録(入稿せず)",
                "cause": f"catalog に公式データが無く fail-closed で除外 ({m.group(1)})",
                "act": "catalog拡充依頼 (該当カードを追加)"}

    # ③ セルフチェック不合格 — psa_to_csv.py:2878 / listing_validator
    #    直前に「❌ セルフチェック失敗 (#cert):」+ 明細行が出るので明細まで拾う。
    m = re.search(r"セルフチェック失敗\s*\(#%s\)\s*[:：]?\s*\n\s*[^\n]*?❌\s*([^\n]+)" % c, log)
    if m or re.search(r"Skipping\s*#%s\b[^\n]*selfcheck" % c, log):
        detail = m.group(1).strip() if m else "selfcheck failed in build_row"
        return {"class": "セルフチェック不合格",
                "cause": f"出力直前の整合チェックで弾いた: {detail}",
                "act": "1丁目1番地で判定 — ①catalog値が正なら②(照合ルール/タイトル生成)を修正"}

    # ④ (PSA 取得失敗は ⓪ に移動 = 目視未確定より先に判定する)

    # ⑤ 理由不明 — **握り潰さない**。cert 付きで表に出して次の分類ルールの起点にする。
    return {"class": "未分類(要調査)",
            "cause": "CSVに載らなかったが、ログから落ちた理由を特定できなかった",
            "act": f"生成ログで #{cert} を検索し、原因行を drop_reason() に分類ルール追加"}


def structural_drops(log, csv_text):
    """universe − CSV = 落ちの実体 (cert単位)。理由を付けて返す。"""
    universe = processed_certs(log)
    if not universe or csv_text is None:
        return []
    ok = built_certs(csv_text)
    out = []
    for cert in universe:
        if cert in ok:
            continue
        d = dict(drop_reason(log, cert))
        d["item"] = "#" + cert
        d["cert"] = cert
        out.append(d)
    return out


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
        # 2026-08-09: `fallback)` と閉じ括弧直結を要求していたため、
        # "(promo fallback, edition一致の同点 2 件…)" のように括弧内に続きがある行に
        # マッチせず、**救済済みの品を落ちとして報告**していた (P-051 Boa Hancock)。
        if re.search(r"iMakCatalog hit \([^)]*fallback[^)]*\)", nxt):
            rescued.add(m.group(2))
    return rescued


def classify_drops(log, *, set_exists, card_exists=None, csv_text=None):
    """生成ログ → [{item, class, cause, act}] (純関数, catalog照会は注入)。

    set_exists(prefix)->bool: そのセット接頭辞のカードが catalog に1件でも在るか。
    card_exists(card_id)->bool: その個別IDが在るか(任意)。
    csv_text: 生成された CSV 本文。渡すと **universe − CSV の差分で drop 集合を確定**する
              (= 分類ルールの足し忘れで silent drop にならない)。未指定なら旧来のパターン方式。
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
        #    2026-08-09: ここが「該当なし(catalog欠)」を決め打ちしていたため、
        #    PSA取得失敗 / catalog実在なのに viewer が確定できなかった / 画像欠 が
        #    **全部「カタログ欠」に化けて**いた。理由の判定は drop_reason に一本化する
        #    (決め打ちすると catalog に無駄な調査を積み、原因も取り違える)。
        m = re.search(r"目視未確定\D*?(\d{6,})", s)
        if m:
            cid = "#" + m.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            d = dict(drop_reason(log, m.group(1)))
            d["item"] = cid
            d["cert"] = m.group(1)
            out.append(d)
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

    # ★ 構造的補完: CSV が渡されていれば「universe − CSV」で落ちの実体を確定する。
    #    上のパターン群で既に cert 付きで拾えているものは重複させない。
    #    パターン側だけに在って universe に無い finding (収録漏れ/scope外/promo衝突 = card_id 単位)
    #    は **その drop の理由説明** として残す (件数は cert 側で数えるので二重計上しない)。
    already = {d.get("cert") for d in out if d.get("cert")}
    for d in structural_drops(log, csv_text):
        if d["cert"] not in already:
            out.append(d)
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


def reconcile_counts(log, drops, csv_text=None):
    """処理N件 vs (成功 + actionable落ち) を照合し silent drop 余地を検出 (純関数, test可)。

    ユーザー方針(2026-06-30): 「入力N = CSV X + 落ち Y」が合わなければ、拾えてない drop=silent drop
    がある証拠。合わない時はそれ自体を問題提起する(=取りこぼしゼロ保証)。

    2026-08-01 根本対策: csv_text があれば **cert 突合** で照合する。落ちは差集合で決まるため
    件数は定義上必ず合い、「⚠️不一致」は分類漏れでは鳴らなくなる。残った警告は
    「ログ自体が欠けている(宣言件数 ≠ 取得中行数)」という別種の実害だけを指す。
    """
    import re

    def _n(pat):
        m = re.search(pat, log or "")
        return int(m.group(1)) if m else None
    processed = _n(r"(\d+)\s*件を処理")
    if processed is None:
        return ""

    # ---- cert 突合 (csv_text がある時。分類ルールの網羅性に依存しない) ----
    universe = processed_certs(log)
    if universe and csv_text is not None:
        ok = built_certs(csv_text)
        n_ok = len([c for c in universe if c in ok])
        n_dr = len(universe) - n_ok
        if processed != len(universe):
            return (f"⚠️ ログ欠落の疑い: 宣言{processed}件 ≠ 取得中行{len(universe)}件 "
                    f"(差{processed - len(universe)}件) → 途中でログが切れた/取得行が出ていない")
        unknown = [d for d in drops if d.get("class") == "未分類(要調査)"]
        line = f"✅ 件数照合OK(cert突合): 処理{len(universe)} = CSV{n_ok} + 落ち{n_dr}"
        if unknown:
            line += f" ※うち理由未特定 {len(unknown)}件 (要分類ルール追加)"
        return line

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
