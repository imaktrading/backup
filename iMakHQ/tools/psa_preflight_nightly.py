#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品待ちの PSA を夜のうちにカタログで引き、引けない物だけカタログに頼む (2026-10-16)。

ユーザー「いざ出品の時に、カタログにないとかも致命的」「今後、出品数も増やしていくから、夜のうちに
やっといて欲しい」「神風業務は、目視がメインやから」。
10/16 実測: 出品待ちのうち PSA 情報のある 98行で、引けたのは 39行・引けない 25行 (表に無いセット /
cardID- の行 / 行が無い)。目視の画面が「期待値特定不能」だらけになり、1回の走行で出せた数が減った。

夜の PSA 先取り (run_psa_cache_warm.bat) の直後に動く:
  1. 出品待ちの行 (psa_new_count と同じ条件 = PSA 新規が選ぶ行) の鑑定番号を集める
  2. 出品と同じ引き方 (psa_preflight.classify) で判定する
  3. INDEX-FAILURE / REVIEW / GAP / AMBIGUOUS のうち **まだ頼んでいない鑑定番号** だけを、
     カタログ宛の依頼1本 (YYYY-MM-DD_psa_preflight_nightly.md) にしてブラボーに呼び鈴
  4. 走行ログに必ず1行 (0件でも)

    python psa_preflight_nightly.py            # 本番
    python psa_preflight_nightly.py --dry-run  # 依頼を書かずに数えるだけ
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI")))

REQ_DIR = r"C:/dev/iMak_data/catalog/requests"
LEDGER = r"C:/dev/iMak_data/hq/psa_preflight_requested.json"   # {cert: 頼んだ日}
ASK = ("INDEX-FAILURE", "REVIEW", "GAP", "AMBIGUOUS")


def waiting_certs():
    """PSA 新規が選ぶ行の鑑定番号 (psa_new_count と同じ条件)。"""
    import sheet_io as S
    import dup_guard as D
    import psa_new_count as N
    from listing_common import pick_cost_jpy
    rows = S._product_ws().get_all_values()
    listed = S.listed_certs(rows) | S.live_listed_certs()
    ok = []
    N.count_rows(rows, listed, S.listed_key_forms(rows), D.live_supply_urls(rows),
                 S.already_listed_reason, D.norm_url, pick_cost_jpy, key_col=S.PRODUCT_COL_KEY, ok_certs=ok)
    return list(dict.fromkeys(str(c) for c in ok))


def mirror_reasons(results, pick=None):
    """引けた物の刷りを PSA ラベルと照らし、ミラー (REVERSE HOLO 等) の行が無くて落ちる物を拾う。

    ★2026-10-17 ユーザー「せっかく夜の仕込みをしているわけだから、30/30を目指したい」: リバースホロ・マスターボールの
      行が無い物は、出品の時に落ちてから (build_fail_watch) カタログに頼んでいた (10/17 2回目で2件落ちた)。
      出品と同じ照合 (psa_variant_gate.pick) を夜に当て、落ちる理由の文を出品と同じ形で作る → mirror_requests が拾う。
    戻り: {cert: 落ちる理由の文}
    """
    if pick is None:
        import psa_variant_gate as _PVG
        pick = _PVG.pick
    out = {}
    for r in results:
        pid = r.get("product_id")
        if r.get("status") != "RESOLVED" or not pid:
            continue
        try:
            new, why = pick(r.get("category"), r.get("brand", ""), r.get("subject", ""), pid)
        except Exception:                                      # noqa: BLE001 照合できない物は夜には頼まない (出品の時に今まで通り)
            continue
        if not new and why:
            out[str(r["cert"])] = "刷りがPSAラベルと合わない — %s — %s" % (str(pid).split(":", 1)[-1], why)
    return out


def pick_new(results, ledger):
    """頼む物 (純関数): 引けない判定で、まだ頼んでいない鑑定番号だけ。"""
    return [r for r in results if r.get("status") in ASK and str(r.get("cert")) not in ledger]


def line_of(r):
    extra = r.get("recovered") or (",".join(r.get("candidates", [])[:6]) if r.get("candidates") else "")
    return (f"- cert {r['cert']} [{r.get('category')}] {r.get('brand', '')} / {r.get('subject', '')} #{r.get('num', '')}"
            f" — {r['status']}" + (f" → 実在 {extra}" if extra else "") + (f" | {r['reason']}" if r.get("reason") else ""))


def request_text(today, new, n_wait, n_data, counts):
    """依頼書の本文 (純関数)。"""
    body = "\n".join(line_of(r) for r in new)
    return (f"# 出品待ちの PSA でカタログに引けない物 ({today}・夜の先回り・{len(new)}件)\n\n"
            f"- 依頼日: {today} / 依頼者: psa_preflight_nightly (夜の PSA 先取りの後に自動) / 緊急度: 中 (翌日の目視の前に埋めたい) / フェーズ: 本実装\n"
            "- 判定: **① カタログ側** (出品と同じ引き方 `catalog integrations psa_to_csv.lookup_*` で引けない)。"
            "② の入力は PSA ラベルの Brand / Subject / CardNumber だけ\n"
            "- ユーザー (2026-10-16):「今後、出品数も増やしていくから、夜のうちにやっといて欲しい」「神風業務は、目視がメインやから」\n\n"
            "## 既に判明していること (再調査するな)\n\n"
            f"- 出品待ち {n_wait}行のうち PSA 情報あり {n_data}行を `psa_preflight.classify` で判定: "
            + " / ".join(f"{k} {v}" for k, v in counts.items()) + "\n"
            "- 下は **引けなかった物のうち、まだ頼んでいない鑑定番号** だけ (前の晩に頼んだ物は載せない)\n"
            "- 状態の意味: INDEX-FAILURE = 行は在るが引き方で外れる / REVIEW = 同じ名前の行が在るが番号・セット記号で引けない /"
            " GAP = 行が見つからない / AMBIGUOUS = 複数に当たる\n\n"
            f"{body}\n\n"
            "## 聞きたいこと (未回答のみ)\n\n"
            "1. 上の各件が、翌日の出品の時に引けるようにしてほしい (表 `psa_brand_set_code.yaml`・行の ID・行の追加のどれで直すかはカタログの判断)\n"
            "2. 公式に無い・扱わない物は、その理由を回答に書いてほしい (翌晩から頼まない)\n")


def ring(path, n):
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "bell.py"), "bravo", "--from", "psa_preflight_nightly",
                        "--file", "catalog/requests/" + os.path.basename(path),
                        "--text", f"出品待ちの PSA でカタログに引けない {n}件 (夜の先回り)。翌日の目視の前に埋めたい"],
                       timeout=600, check=False)
    except Exception as e:                                     # noqa: BLE001 呼び鈴が鳴らなくても依頼は置いてある
        print(f"  ⚠️ 呼び鈴を鳴らせなかった: {type(e).__name__}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    import psa_preflight as PF
    PF._ensure_catalog()
    certs = waiting_certs()
    metas = _load(PF, certs)
    con = sqlite3.connect(PF.CATALOG_DB)
    results = [PF.classify(c, m, con) for c, m in metas]
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    try:
        ledger = json.load(open(LEDGER, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001 初回・壊れていても全件を頼む側に倒す
        ledger = {}
    new = pick_new(results, ledger)
    today = dt.date.today().isoformat()
    path = os.path.join(REQ_DIR, f"{today}_psa_preflight_nightly.md")
    if new and not a.dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write(request_text(today, new, len(certs), len(metas), counts))
        for r in new:
            ledger[str(r["cert"])] = today
        with open(LEDGER, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=1)
        ring(path, len(new))
    # ★2026-10-17 ミラーの行 (REVERSE HOLO 等) も夜のうちに頼む (カタログが毎時に作る・出品の時の頼み方と同じ入力)
    import build_fail_watch as _BFW
    mreq = _BFW.mirror_requests(mirror_reasons(results))
    mnew = 0 if a.dry_run else _BFW.write_mirror_input(mreq, dt.datetime.now().isoformat(timespec="seconds"))
    print(f"🪞 出品待ちの先回り: ミラーの行が無くて落ちる {len(mreq)}件 / カタログに新しく頼んだ {mnew}件"
          f"{' (試しなので頼んでいない)' if a.dry_run else ''}")
    n_ng = sum(v for k, v in counts.items() if k in ASK)
    print(f"📋 出品待ちの先回り: カタログで引けない {n_ng}件 (新しく頼んだ {0 if a.dry_run else len(new)}件"
          f"{' / 試しなので頼んでいない' if a.dry_run else ''}) / 引けた {counts.get('RESOLVED', 0)}件 / 対象外 {counts.get('OUT-OF-SCOPE', 0)}件"
          f" / 出品待ち {len(certs)}件のうち PSA 情報あり {len(metas)}件")
    return 0


def _load(PF, certs):
    out = []
    for c in certs:
        p = PF.PSA_CERTS_DIR / f"{c}.json"
        if p.exists():
            try:
                out.append((c, json.loads(p.read_text(encoding="utf-8"))))
            except Exception:                                  # noqa: BLE001
                pass
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
