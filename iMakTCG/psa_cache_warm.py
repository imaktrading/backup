#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜間に PSA データを少しずつ貯める (前段の判定を効かせるため・2026-08-18)。

なぜ必要か:
    出品くんは枠を選ぶ前に「参入しないゲーム / catalog未収録 / 画像なし / 既に出品中」を
    落とす前段を持っている。ところが判定には PSA データが要るのに、**PSA を取りに行くのは
    枠を選んだ後**。だから新しいカードは判定できず、「判定不能は落とさない」規則どおり
    残って、枠を1つ使ってから後段で消える。
    実測 2026-08-18: 出品候補 912件のうち PSA データがあるのは 235件 (25%)。
      前段は候補の 3/4 を判定できていない。この日は 20枠のうち 6枠が
      「既に出品中のカード」で消え、しかも **人が目視で確認した後**に消えた。
    → 先に貯めておけば、前段の4つの判定がそのまま効く。出品くん本体は触らない。

守っていること (PSA を叩く上での制約。全部 iMakTCG の既存実装をそのまま使う):
    - **専用 chrome profile は1プロセス排他**。出品くんが動いている間は起動できない
      (= 起動失敗したら黙って終わる。奪い合わない)
    - **cert 間 15秒**。get_psa_data がそのまま持っているので、ここで速くしない
    - **Cloudflare に当たったら即やめる**。夜間は人が突破できないので、
      3回 retry して駄目なら「次の晩にまわす」。叩き続けない (= BAN が一番高くつく)
    - 1回の上限は既定 40件。1日12件しか触っていなかった所を一気に上げない

使い方:
    python psa_cache_warm.py              # 既定 40件
    python psa_cache_warm.py --limit 10   # 件数指定
    python psa_cache_warm.py --dry-run    # 対象を数えるだけ (ブラウザを起動しない)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

RESULT_PATH = r"C:\dev\iMak\iMakHQ\review_logs\psa_cache_warm_last.json"
DEFAULT_LIMIT = 40


def pending_certs(all_certs, is_cached):
    """まだ PSA データが無い cert (順序は入力のまま = 再現可能)。純関数・test 可."""
    seen, out = set(), []
    for c in all_certs:
        c = str(c or "").strip()
        if not c or c in seen or is_cached(c):
            continue
        seen.add(c)
        out.append(c)
    return out


def _record(payload):
    """走った証跡を残す (画面にしか出ないと、止まっていても誰も気づけない)。"""
    try:
        os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
        payload["at"] = datetime.now().isoformat(timespec="seconds")
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:                                          # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import psa_api
    import psa_to_csv as P

    certs, _cost, _url, _title = P.load_targets_from_sheet_psa()
    todo = pending_certs(certs, lambda c: psa_api.get_cached(c) is not None)
    print(f"=== PSA データの先貯め ===")
    print(f"出品候補 {len(certs)}件 / データ有 {len(certs) - len(todo)}件 "
          f"/ 無 {len(todo)}件 → 今回 {min(a.limit, len(todo))}件")
    if a.dry_run or not todo:
        _record({"mode": "dry-run" if a.dry_run else "empty",
                 "candidates": len(certs), "pending": len(todo), "fetched": 0})
        return 0

    import undetected_chromedriver as uc
    from chrome_util import detect_chrome_major

    os.makedirs(P._PSA_PROFILE_DIR, exist_ok=True)
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument(f"--user-data-dir={P._PSA_PROFILE_DIR}")
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    try:
        driver = uc.Chrome(options=options, version_main=detect_chrome_major())
    except Exception as e:                                     # noqa: BLE001
        # profile は1プロセス排他。出品くんが使っている = 今夜は見送る (奪い合わない)
        print(f"⚠️ ブラウザを起動できず終了 ({type(e).__name__}) "
              f"— 出品くんが動いている可能性。今回は何もしない")
        _record({"mode": "skip-profile-busy", "candidates": len(certs),
                 "pending": len(todo), "fetched": 0, "error": type(e).__name__})
        return 0

    got = fail = 0
    stopped = ""
    try:
        for i, cert in enumerate(todo[:a.limit], 1):
            data = P.get_psa_data(driver, cert)
            if data and data.get("Subject"):
                got += 1
                print(f"  [{i}] {cert} ✓ {str(data.get('Subject'))[:40]}")
            else:
                fail += 1
                print(f"  [{i}] {cert} ✗ 取れず")
                # get_psa_data は Cloudflare を3回 retry して None を返す。
                # 夜間は人が突破できないので、そこで**やめる**。叩き続けない。
                if data is None:
                    stopped = "cloudflare"
                    print("  🛡️ Cloudflare を抜けられない → 今夜はここで終了 (次の晩に続きから)")
                    break
    finally:
        try:
            driver.quit()
        except Exception:                                      # noqa: BLE001
            pass

    print(f"=== 取得 {got}件 / 失敗 {fail}件"
          + (f" / {stopped} で中断" if stopped else "") + " ===")
    _record({"mode": "run", "candidates": len(certs), "pending": len(todo),
             "fetched": got, "failed": fail, "stopped": stopped,
             "remaining": len(todo) - got})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
