#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎日使う入力が新しくなっているかの点検 (2026-10-17)。

ユーザー「不具合が出て気づくまでの期間が長いね」。10/17 に見つかった物:
  - トラフィックレポート: 10/06 から 11日 保存されず、棚の判断が古い表示回数のままだった
  - CPaSS の送料: 10/15 朝から ログイン切れで読めていなかった
  - オファーの送信: 朝の2回が 送った0件 で終わっていた
どれも「失敗」と表に出ず、古い物を使い続けていた。入力ごとに「何時間以内に新しくなっているはず」を持ち、
過ぎた物を神風の状態の1行と毎朝のメールに赤で出す。読むのはファイルの時刻と控えだけ (eBay・シートは叩かない)。

    python input_freshness.py        # 点検の結果を出す
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os

DL = os.path.join(os.path.expanduser("~"), "Downloads")
REPORTS = r"C:/dev/iMak_data/seller_hub/reports"
HQ_DATA = r"C:/dev/iMak_data/hq"
HERE = os.path.dirname(os.path.abspath(__file__))


def _newest_mtime(patterns):
    fs = []
    for p in patterns:
        fs += glob.glob(p, recursive=True)
    return max((os.path.getmtime(f) for f in fs), default=None)


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _iso(s):
    try:
        return dt.datetime.fromisoformat(str(s)[:19]).timestamp()
    except (TypeError, ValueError):
        return None


def judge(name, ts, max_h, now, why_stale=""):
    """1項目の判定 (純関数)。ts=最後に新しくなった時刻 (秒)。戻り dict。"""
    if ts is None:
        return {"name": name, "stale": True, "age_h": None, "max_h": max_h, "note": why_stale or "見つからない"}
    age = (now - ts) / 3600.0
    return {"name": name, "stale": age > max_h, "age_h": round(age, 1), "max_h": max_h,
            "note": (why_stale or "%d時間前" % age) if age > max_h else ""}


CREDIT_WORDS = ("credit balanc", "insufficient_quota", "billing_error")   # ログでは文が途中で切れていることがある (10/17 のハント)
LOG_DIRS = [os.path.join(HERE, "..", "run_logs"), os.path.join(HERE, "..", "review_logs"),
            os.path.join(HERE, "..", "review_logs", "job_queue")]


def credit_check(now, dirs=None, hours=24):
    """直近 hours 時間に書かれたログに、有料 API の残高切れの文があるか (I/O)。"""
    hits = []
    for d in (dirs or LOG_DIRS):
        for f in glob.glob(os.path.join(d, "*.log")):
            try:
                if now - os.path.getmtime(f) > hours * 3600:
                    continue
                with open(f, encoding="utf-8", errors="replace") as fh:
                    t = fh.read()
            except OSError:
                continue
            if any(w in t for w in CREDIT_WORDS):
                hits.append(os.path.basename(f))
    return {"name": "有料 API の残高", "stale": bool(hits), "age_h": None, "max_h": None,
            "note": ("残高切れの記録: %s" % ", ".join(hits[:3])) if hits else ""}


def check(now=None):
    """全項目の点検 (I/O・ファイルの時刻と控えを読むだけ)。戻り [dict]。"""
    now = (now or dt.datetime.now()).timestamp()
    out = []
    rep = lambda n: [os.path.join(REPORTS, "**", n), os.path.join(DL, n)]   # noqa: E731
    out.append(judge("トラフィックレポート", _newest_mtime(rep("eBay-ListingsTrafficReport-*.csv")), 36, now))
    out.append(judge("出品中レポート", _newest_mtime(rep("eBay-all-active-listings-report-*.csv")), 36, now))
    out.append(judge("ファネル", _newest_mtime([os.path.join(HERE, "..", "funnel_output", "funnel_*.csv")]), 36, now))
    st = _load(os.path.join(HQ_DATA, "job_queue_state.json"), {}) or {}
    for key, label in (("psa_cache_warm", "夜の PSA 情報取り"), ("night_bundle", "夜の補URL探し")):
        out.append(judge(label, _iso((st.get(key) or {}).get("last_ok")), 30, now))
    live = _load(os.path.join(HQ_DATA, "live_listings_cache.json"), {}) or {}
    out.append(judge("出品中の一覧の控え", _iso(live.get("generated_at")), 24, now))
    # SpeedPAK の送料: 読みに行った最後の回がログイン画面等で止まっていたら赤 (空の行が無い日は読みに行かないので時刻では見ない)
    cp = _load(os.path.join(HQ_DATA, "cpass_fees.json"), {}) or {}
    stage = (cp.get("debug") or {}).get("stage") if isinstance(cp.get("debug"), dict) else None
    out.append({"name": "SpeedPAK の送料", "stale": bool(stage), "age_h": None, "max_h": None,
                "note": ("読めていない: %s" % stage) if stage else ""})
    # ★2026-10-18 有料 API の残高切れ: 10/17 22:18 から Anthropic の残高が尽き、トレハンの写真読み 1,955件が全部失敗した
    #   (7時間半 空回り)。直近24時間のログに残高切れの文があれば赤
    out.append(credit_check(now))
    # オファー: 送る予定のまま3時間以上送れていない物があれば赤 (拡張が動いていない)
    try:
        import sys
        sys.path.insert(0, HERE)
        import shelf_offer as SO
        led = SO.load_json(SO.OFFERS_PATH, {})
        stuck = [v for v in led.values() if SO.offer_state(v, dt.datetime.fromtimestamp(now)) == "waiting"
                 and (_iso(v.get("planned")) or now) < now - 3 * 3600]
        out.append({"name": "オファーの送信", "stale": bool(stuck), "age_h": None, "max_h": None,
                    "note": ("送れないまま %d件" % len(stuck)) if stuck else ""})
    except Exception as e:                                     # noqa: BLE001 点検できない時は黙らない
        out.append({"name": "オファーの送信", "stale": True, "age_h": None, "max_h": None,
                    "note": "点検できない: %s" % type(e).__name__})
    return out


def summary_line(items):
    """1行の要約 (純関数)。"""
    bad = [i for i in items if i["stale"]]
    if not bad:
        return "🩺 入力の鮮度: 全部新しい (%d項目)" % len(items)
    return "🩺 入力の鮮度: ⚠️ 古い %d件 — " % len(bad) + " / ".join(
        "%s (%s)" % (i["name"], i["note"]) for i in bad)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    r = check()
    print(summary_line(r))
    for i in r:
        print("  %s %s %s" % ("❌" if i["stale"] else "✅", i["name"], i["note"] or ("%s時間前" % i["age_h"] if i["age_h"] is not None else "")))
