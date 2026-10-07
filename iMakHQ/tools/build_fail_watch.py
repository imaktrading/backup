# -*- coding: utf-8 -*-
"""新規の目視で OK したのに、出品の手前で落ちた cert を理由付きで覚え、繰り返したら残務に回す (2026-10-07)。

ユーザー「目視に見せるのはいいんだけど、理由わからず手当せずに何回も出てくるものを防ぎたい。
その手立てとしてカウンターは？といっただけ」。

    目視で OK → 出品の手前 (刷りの確認 / セルフチェック / カタログ未登録 …) で落ちる
    → 次の自動でまた目視に出る → また OK → また落ちる …
    122484177 は5回、84299672 は2回。理由は走行ログに1行出るだけで、誰も拾っていなかった。

やること (自動の締め・家で):
    1. 走行ログから cert ごとの落ちた理由を拾う (parse_fail_reasons)
    2. 台帳 build_fail_reasons.json に積む (落ちた回数・最後の理由)。出品できた cert は台帳から外す
    3. 目視で OK 済みの cert が **2回** 落ちたら、残務に1件足す (同じ cert は1回だけ)
    4. 目視の画面 (post_psa_review) は台帳を読み、カードに「前回はこの理由で落ちた / 残務 №」を出す

台帳は iMak_data/dedupe に置く = KAGOYA のボタンにも送られ、目視の画面が読める。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

LEDGER = r"C:/dev/iMak_data/dedupe/build_fail_reasons.json"
VERIFIED = r"C:/dev/iMak_data/dedupe/verified_certs.json"
BACKLOG_AFTER = 2          # OK 済みの cert がこの回数落ちたら残務に回す

_SKIP_RE = re.compile(r"Skip \((?P<why>[^)]*(?:\([^)]*\)[^)]*)*)\): #(?P<cert>\d+)\s*(?P<rest>.*)")
_SELF_RE = re.compile(r"セルフチェック失敗 \(#(?P<cert>\d+)\)")
_SELF2_RE = re.compile(r"Skipping #(?P<cert>\d+): selfcheck failed")
_OK_RE = re.compile(r"^\s*#(?P<cert>\d+): \$\d")
_FAIL_LIST_RE = re.compile(r"^失敗: (?P<list>[\d, ]+)$")


def parse_fail_reasons(log_text):
    """走行ログ → ({cert: 落ちた理由}, {出品の値段まで行った cert})。純関数。

    1枚ごとの区切りは「 → #番号 名前 ✓」の行。その後に出た「Skip (…)」「❌ …」を覚えておき、
    「Skipping #cert: selfcheck failed」が来たらその cert の理由にする (build_row の中の Skip は cert を書かない)。
    """
    reasons, ok = {}, set()
    pending = []
    lines = str(log_text or "").splitlines()
    for ln in lines:
        s = ln.strip()
        if s.endswith("✓") and ("→ #" in s or s.startswith("取得中")):
            pending = []
            continue
        m = _SKIP_RE.search(ln)
        if m:
            rest = m.group("rest").strip(" —-")
            reasons[m.group("cert")] = (m.group("why") + (" — " + rest if rest else "")).strip()[:200]
            pending = []
            continue
        m = _SELF_RE.search(ln) or _SELF2_RE.search(ln)
        if m:
            cert = m.group("cert")
            if _SELF_RE.search(ln):
                pending = ["セルフチェック:"]
                continue
            why = " ".join(pending).strip() or "セルフチェック失敗"
            reasons.setdefault(cert, why[:200])
            pending = []
            continue
        if s.startswith(("❌", "🚫")) or "Skip (" in s:
            pending.append(s.lstrip("❌🚫⚠️ ").replace("**", "").strip())
            continue
        m = _OK_RE.search(ln)
        if m:
            ok.add(m.group("cert"))
            continue
        m = _FAIL_LIST_RE.search(s)
        if m:
            for c in m.group("list").replace(" ", "").split(","):
                if c:
                    reasons.setdefault(c, "失敗 (理由がログに無い)")
    for c in ok:
        reasons.pop(c, None)
    return reasons, ok


def update_ledger(ledger, reasons, ok, verified, now):
    """台帳を更新して (新しい台帳, 残務に回す [(cert, rec)]) を返す。純関数。

    - 落ちた cert: fails を1つ増やし、最後の理由を書き換える
    - 出品の値段まで行った cert: 台帳から外す
    - 目視で OK/CHOSEN 済み かつ fails >= BACKLOG_AFTER かつ まだ残務に回していない → 残務に回す
    """
    out = {k: dict(v) for k, v in (ledger or {}).items() if k not in ok}
    to_backlog = []
    for cert, why in (reasons or {}).items():
        rec = out.get(cert) or {"first_at": now, "fails": 0}
        rec["fails"] = int(rec.get("fails") or 0) + 1
        rec["reason"] = why
        rec["last_at"] = now
        v = (verified or {}).get(cert) or {}
        if v.get("choice") in ("OK", "CHOSEN"):
            rec["answered"] = int(v.get("times") or 1)
            rec["product_id"] = v.get("product_id") or ""
        out[cert] = rec
        if rec.get("answered") and rec["fails"] >= BACKLOG_AFTER and not rec.get("backlog"):
            to_backlog.append((cert, rec))
    return out, to_backlog


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_ledger(path=LEDGER):
    return _load(path)


def run(log_text, append_log, ledger_path=LEDGER, verified_path=VERIFIED, add_backlog=None):
    """自動の締めで呼ぶ (I/O)。走行ログ1本ぶん。0件でも必ず1行出す。"""
    reasons, ok = parse_fail_reasons(log_text)
    now = datetime.now().isoformat(timespec="seconds")
    ledger, to_backlog = update_ledger(_load(ledger_path), reasons, ok, _load(verified_path), now)
    added = []
    if to_backlog:
        if add_backlog is None:
            import claim as _claim
            add_backlog = _claim_add(_claim)
        for cert, rec in to_backlog:
            try:
                rec["backlog"] = add_backlog(cert, rec)
                added.append(cert)
            except Exception as e:                              # noqa: BLE001
                append_log("  ⚠️ 残務に足せなかった: %s %s: %s\n" % (cert, type(e).__name__, e))
    tmp = ledger_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ledger_path)
    answered = [c for c in reasons if (ledger.get(c) or {}).get("answered")]
    append_log("🩹 目視 OK 済みなのに出品の手前で落ちた: %d件 (落ちた cert 全体 %d件) / 残務に足した: %d件%s\n" % (
        len(answered), len(reasons), len(added),
        "".join("\n    #%s (%d回目): %s" % (c, ledger[c]["fails"], ledger[c]["reason"][:90]) for c in answered[:10])))
    return ledger, added


def _claim_add(claim_mod):
    def _add(cert, rec):
        p = claim_mod.add_backlog(
            "新規の目視で OK 済みなのに出品の手前で落ちる: cert %s (%d回)" % (cert, rec["fails"]),
            priority=2,
            detail=("目視の答え: %s (%d回 OK)\n落ちた理由 (最後): %s\n"
                    "台帳: %s\n直すまで毎回目視に出る。原因 (生成側) を直したらこの件を閉じる"
                    % (rec.get("product_id") or "?", rec.get("answered") or 0, rec.get("reason"), LEDGER)),
            who="出品くん(自動)")
        item = "backlog:" + os.path.splitext(os.path.basename(str(p)))[0]
        try:
            return "№%d" % claim_mod.number_of(item)
        except Exception:                                       # noqa: BLE001
            return item
    return _add
