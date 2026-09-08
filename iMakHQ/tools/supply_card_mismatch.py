#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入元が **別のカード** になっている出品を見つける (2026-09-08)。

■ なぜ要るか
2026-09-08、バイヤーの問い合わせで発覚した: 出品 820026248229 (ブラッキー SV8a-092) の
補URL に **別カードの安い出品** が入り、その値段が「今の最安 ¥10,900」としてシートに載って、
価格が cost-plus で決まる仕組みのまま **$155.98** で出ていた (正しくは $405.98)。
**見た目では分からない**。人が気づいたのは買い手に聞かれたからで、それ以外に検知は無かった。

■ 見つけ方 (2段)
  ① 値段の形で絞る  … 仕入値が「番号一致で見つかっている供給の最安」より大幅に安い行。
                     別カードが混ざると必ずこの形になる (安いから混ざったと気づかない)。
  ② 商品名で確かめる … ①の行の仕入元URLを開き、**商品名のカード番号が KEY と合うか**。
                     ここまでやらないと「本当に安かっただけ」と区別できない。

■ 実測 (2026-09-08 の初回)
  照合できた出品 316件 → ① で 14件 → ② で **別カードの混入は0件**。
  代わりに KEY の取り違えを1件見つけた (820065007711: 仕入元 OP07-033 が正で KEY=P-033 が誤り)。
  → ①だけでは判定できない。**②まで通した件数を出す**こと。

使い方:
  python supply_card_mismatch.py                 # ①だけ (無料・数秒)
  python supply_card_mismatch.py --verify        # ②まで (ブラウザで商品名を読む・数分)
  python supply_card_mismatch.py --verify --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ★import した時に stdout を差し替えない (pytest の捕捉が壊れる)。実行時だけ整える。
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                         # noqa: BLE001
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import psa_hoju_fill as hf                                    # noqa: E402

# 「安すぎる」の線。0.6 = 番号一致の最安の6割未満。2026-09-08 の実測でこの線で 316→14件。
CHEAP_RATIO = 0.6
CAT_COL, PSA_CATEGORY = 17, "TCG"      # R列 = 商材。PSA の行はここが TCG
OUT_PATH = os.path.join(HERE, "..", "review_logs", "supply_card_mismatch.json")


def _cell(row, i):
    return (row[i] if len(row) > i else "") or ""


def _num(s):
    d = re.sub(r"[^0-9]", "", str(s or ""))
    return int(d) if d else None


def known_prices(entry):
    """その出品の **番号一致で見つかった供給** の値段一覧 (純関数)。

    キャッシュに入るのはカード番号で検索して当たったものだけなので、
    ここに並ぶ値段は「そのカードの相場」と見てよい。
    """
    out = []
    m = (entry or {}).get("mercari") or {}
    for key in ("cands", "all_cands"):
        for row in (m.get(key) or []):
            if row and isinstance(row[0], (int, float)):
                out.append(float(row[0]))
    for lst in ((entry or {}).get("snkrdunk") or {}).get("psa10_listings") or []:
        try:
            out.append(float(lst.get("price")))
        except (TypeError, ValueError):
            pass
    return [p for p in out if p]


def find_suspects(vals, cache, ratio=CHEAP_RATIO):
    """① 値段の形で絞る (純関数)。戻り: (suspects, 内訳dict)。

    ★内訳を返すのは、**見ていない分を隠さない**ため。比べる相手 (同じカードの相場) が
      無い出品は素通りになる。「503件中339件しか見ていない」と言えないと、
      残り164件に同じ事故が隠れていても「全部見た」と誤解する (2026-09-08 ユーザー指摘)。
    """
    suspects = []
    stat = {"listed": 0, "compared": 0, "no_cost": 0, "no_market": 0}
    for r in vals[1:]:
        iid, cert = _cell(r, hf.B).strip(), _cell(r, hf.CERT).strip()
        if not iid or not cert or _cell(r, 3).strip():        # 出品中のみ / 売切は除く
            continue
        # ★PSA (R列='TCG') だけ (2026-09-08 ユーザー指示)。この検査は「同じカードの相場」を
        #   カード番号の検索で作るので、カード以外は比べる土俵に乗らない。実際バッグの行が
        #   3件 紛れていた (cert 欄に商品名が入っており「cert 有り」を満たしてしまう)。
        if _cell(r, CAT_COL).strip() != PSA_CATEGORY:
            continue
        stat["listed"] += 1
        cost = _num(_cell(r, 13)) or _num(_cell(r, 12)) or _num(_cell(r, 5))
        prices = known_prices(cache.get(iid))
        if not cost:
            stat["no_cost"] += 1
            continue
        if not prices:
            stat["no_market"] += 1
            continue
        stat["compared"] += 1
        cheapest = min(prices)
        if cost < cheapest * ratio:
            suspects.append({
                "itemID": iid, "cert": cert, "key": _cell(r, hf.KEY),
                "cost": cost, "cheapest": cheapest,
                "ratio": round(cost / cheapest, 3),
                "title": _cell(r, 2)[:60],
                "urls": [u for u in ([_cell(r, 0)]
                                     + [_cell(r, hf.AUX0 + k) for k in range(hf.AUXN)]) if u],
            })
    suspects.sort(key=lambda s: s["ratio"])
    return suspects, stat


COST_LEDGER = os.path.join(HERE, "..", "review_logs", "supply_cost_history.json")
DROP_RATIO = 0.6      # 前回の6割未満に下がったら「今日 大きく下がった」


def load_cost_ledger(path=None):
    p = path or COST_LEDGER
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                         # noqa: BLE001
        return {}


def find_cost_drops(vals, ledger, ratio=DROP_RATIO):
    """**今日 仕入値が大きく下がった** 出品を見つける (純関数)。戻り: (drops, 新しい台帳)。

    ★「今いくら安いか」では門にならない。2026-09-08 実測で、取得時の半値未満は 57件 あり、
      その多くは **正常な値下がり** (安い仕入元を見つけたら価格を下げるのは狙ってやっている)。
      事故は「**別カードの安い供給が入った瞬間**に値段が飛ぶ」ことなので、
      標準の状態ではなく **変化** を見る。変化なら1日数件で、人が見られる量になる。
    """
    drops, new = [], {}
    for r in vals[1:]:
        iid = _cell(r, hf.B).strip()
        if not iid or _cell(r, CAT_COL).strip() != PSA_CATEGORY:
            continue
        cost = _num(_cell(r, 13)) or _num(_cell(r, 12))
        if not cost:
            continue
        new[iid] = cost
        prev = (ledger or {}).get(iid)
        if prev and cost < prev * ratio:
            drops.append({"itemID": iid, "prev": prev, "now": cost,
                          "ratio": round(cost / prev, 3), "key": _cell(r, hf.KEY),
                          "title": _cell(r, 2)[:60]})
    drops.sort(key=lambda d: d["ratio"])
    return drops, new


def number_matches(key, card_no):
    """KEY と 商品名から取れた番号が同じカードか (純関数)。

    ポケモンは商品名が `090/071` のような通し番号で、KEY は `SV2P-090`。
    ここを見ないと **一致しているものを不一致と読む** (2026-09-08 に4件 誤判定した)。
    """
    if not card_no:
        return None                                           # 番号が読めない = 判定しない
    base = (key or "").split(":")[-1].split("_")[0].upper()
    no = card_no.upper()
    if no == base:
        return True
    m = re.match(r"^(\d{1,3})/\d{1,3}$", no)                  # 090/071 → 末尾 090
    if m and base.endswith("-" + m.group(1)):
        return True
    return False


def verify(suspects, limit=0, verbose=True):
    """② 仕入元の商品名を読んで、カード番号が KEY と合うか確かめる (I/O)。"""
    import time
    import mercari_psa_resource as mp
    import newcand_confirm as nc
    todo = suspects[:limit] if limit else suspects
    try:
        drv = mp.new_scrape_driver()
    except Exception as e:                                    # noqa: BLE001
        print(f"⚠ ブラウザを起こせない ({type(e).__name__}) → ②は skip")
        return suspects
    try:
        for s in todo:
            s["checked"] = []
            for u in s["urls"]:
                if "snkrdunk" in u:
                    s["checked"].append({"url": u, "verdict": "skip(スニダンは構造が別)"})
                    continue
                try:
                    drv.get(u)
                    time.sleep(2.5)
                    t = re.search(r"<title>(.*?)</title>", drv.page_source, re.S)
                    title = re.sub(r"\s*-\s*メルカリ.*$", "", (t.group(1) if t else "")).strip()
                except Exception as e:                        # noqa: BLE001
                    s["checked"].append({"url": u, "verdict": f"開けず({type(e).__name__})"})
                    continue
                no = nc.extract_card_no(title) or ""
                ok = number_matches(s["key"], no)
                s["checked"].append({"url": u, "title": title[:60], "no": no,
                                     "verdict": {True: "一致", False: "★不一致",
                                                 None: "番号なし"}[ok]})
            s["mismatch"] = sum(1 for c in s["checked"] if c["verdict"] == "★不一致")
            if verbose:
                mark = "★別カードの疑い" if s["mismatch"] else "シロ"
                print(f"  {s['itemID']}  {mark}  仕入¥{s['cost']:,.0f} / 最安¥{s['cheapest']:,.0f}"
                      f"  {s['title'][:30]}")
                for c in s["checked"]:
                    if c["verdict"] == "★不一致":
                        print(f"      {c['url'][-16:]} 番号={c['no']} ≠ KEY={s['key']}"
                              f"  {c.get('title','')[:36]}")
    finally:
        try:
            drv.quit()
        except Exception:                                     # noqa: BLE001
            pass
    return suspects


def build_mail(payload):
    """検査結果 → (件名, 本文) (純関数)。

    ★「有無」と「次に何をするか」だけ書く。一覧は長くしない (読む側のトークンも時間も食う)。
      0件の時も **必ず送る**。届かないと「動いていない」のか「異常なし」なのか分からない。
    """
    sus = payload.get("suspects") or []
    drops = payload.get("drops") or []
    verified = payload.get("verified")
    bad = [s for s in sus if s.get("mismatch")]
    checked = payload.get("checked", 0)
    if drops:
        # ★値下がりは「今日 起きた変化」なので、標準の一覧より先に出す。
        #   事故はいつも「別カードの安い供給が入った瞬間」に起きる。
        lines = [f"★今日、仕入値が大きく下がった出品が {len(drops)}件 あります。",
                 "  値段は仕入値から自動で決まるので、**そのぶん安く売りに出ます**。",
                 "  安い仕入元が本当に同じカードか、先に確かめてください。", ""]
        for d in drops[:10]:
            lines.append(f"  {d['itemID']}  {d['prev']:,.0f}円 → {d['now']:,.0f}円"
                         f" ({d['ratio']*100:.0f}%)  {d['title'][:26]}")
        if len(drops) > 10:
            lines.append(f"  … 他 {len(drops)-10}件")
        lines += ["", "-" * 40, ""]
        head_drop = f"値下がり {len(drops)}件 / "
    else:
        lines, head_drop = [], ""
    if verified:
        head = f"安く出しすぎ {len(bad)}件" if bad else "安く出しすぎ なし (確認済)"
    else:
        head = f"安く出しすぎの疑い {len(sus)}件" if sus else "異常なし"
    subject = f"[仕入元チェック] {head_drop}{head} / 出品 {checked}件を確認"

    # ★「見た件数」と「見ていない件数」を必ず一緒に出す。比べる相手 (同じカードの相場) が
    #   無い出品は素通りになるので、これを隠すと「全部見た」と誤解される (2026-09-08 指摘)。
    st = payload.get("stat") or {}
    scope = f"PSAの出品 {st.get('listed', checked)}件のうち {checked}件を確認"
    if st.get("no_market"):
        scope += f" (残り {st['no_market']}件は比べる相場がまだ無く、見ていません)"

    if not sus:
        lines += [scope + "。",
                  "1段目の一覧 (相場より安すぎる出品) は0件です。" if drops
                  else "おかしな値段の出品はありませんでした。対応は不要です。"]
        return subject, "\n".join(lines)

    lines += [
        scope + "。",
        "",
        "■ 何を見つけたか",
        f"  同じカードの相場よりずっと安い値段で仕入れたことになっている出品が {len(sus)}件。",
        "  出品価格は仕入値から自動で決まるので、**その分だけ安く売りに出ている**",
        "  可能性があります。",
        "",
        "  よくある原因: 仕入元のURLに **別のカード** が入っている。",
        "  実例 (2026-09-08): ブラッキーの出品に別カードの安い仕入元が入り、",
        "  $155.98 で出ていた (正しくは $405.98)。バイヤーに聞かれて初めて分かった。",
        "",
        "■ 該当した出品",
        "  (うちの仕入値 / 同じカードの相場・最安)",
        "",
    ]
    for s in sus[:15]:
        lines.append(f"  {s['itemID']}  {s['cost']:,.0f}円 / 相場 {s['cheapest']:,.0f}円"
                     f"  → 相場の{s['ratio']*100:.0f}%  {s['title'][:26]}")
    if len(sus) > 15:
        lines.append(f"  … 他 {len(sus)-15}件")
    lines += [
        "",
        "■ ただし、これだけでは『不具合』とは言えません",
        "  安いのが本物のこともよくあります (特価・ケース傷あり など)。",
        "  実際 2026-09-08 の初回は、この14件を全部調べて **本当の間違いは0件** でした。",
        "  この一覧は『どれから見るか』の順番です。",
    ]
    if verified:
        lines += ["", f"■ 仕入元の中身まで確認しました → 本当に別カードだったもの: {len(bad)}件"]
        for s in bad:
            lines.append(f"  ★ {s['itemID']} (出品しているカード: {s['key']})")
            for c in s.get("checked") or []:
                if c.get("verdict") == "★不一致":
                    lines.append(f"      仕入元は別のカード ({c.get('no')}): "
                                 f"{c.get('title','')[:40]}")
                    lines.append(f"      {c['url']}")
    else:
        lines += [
            "",
            "■ 次にやること",
            "  仕入元のページを開いて、本当に同じカードか確かめます (数分):",
            "",
            "    python C:/dev/iMak/iMakHQ/tools/supply_card_mismatch.py --verify --limit 10",
            "",
            "  別カードだった時の直し方は、Claude に『supply-card-mismatch』と言えば手順が出ます。",
        ]
    return subject, "\n".join(lines)


def send_mail(payload):
    """メールを送る (I/O)。★失敗を握り潰さない (届かないのに成功扱いが一番まずい)。"""
    import subprocess
    import tempfile
    subject, body = build_mail(payload)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        r = subprocess.run([sys.executable, r"C:\dev\iMak_data\tools\send_mail.py",
                            "--subject", subject, "--body-file", path],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        if r.returncode == 0:
            print(f"  ✉ メール送信: {subject}")
        else:
            print(f"  ⚠ メール送信 失敗 (exit {r.returncode}): {(r.stderr or r.stdout)[:200]}")
        return r.returncode == 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="仕入元の商品名まで読んで確かめる")
    ap.add_argument("--mail", action="store_true", help="結果をメールで送る (0件でも送る)")
    ap.add_argument("--limit", type=int, default=0, help="②で見る件数の上限")
    ap.add_argument("--ratio", type=float, default=CHEAP_RATIO)
    a = ap.parse_args()

    vals = hf._read_high()
    cache = {}
    if os.path.exists(hf.CACHE_PATH):
        with open(hf.CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    ledger = load_cost_ledger()
    drops, new_ledger = find_cost_drops(vals, ledger)
    suspects, stat = find_suspects(vals, cache, a.ratio)
    print(f"仕入元が別カードでないかの検査: 出品中 {stat['listed']}件 / "
          f"比べられた {stat['compared']}件 (相場の材料が無く見ていない {stat['no_market']}件) / "
          f"① 値段が安すぎる {len(suspects)}件 (相場の{a.ratio*100:.0f}%未満)")
    if not suspects:
        print("  ① で0件。②は不要。")
    for s in suspects[:20]:
        print(f"  {s['itemID']}  仕入¥{s['cost']:>8,.0f} / 番号一致の最安¥{s['cheapest']:>8,.0f}"
              f" ({s['ratio']*100:3.0f}%)  {s['title'][:34]}")
    if a.verify and suspects:
        print("\n② 仕入元の商品名を読んで確かめます (ブラウザ)")
        suspects = verify(suspects, a.limit)
        bad = [s for s in suspects if s.get("mismatch")]
        print(f"\n★別カードの疑い {len(bad)}件 / 見た {sum(1 for s in suspects if 'checked' in s)}件")
        if not bad:
            print("  ②まで通して0件 = 安いのは本物。①の件数だけで騒がないこと。")
    if drops:
        print(f"\n★今日 仕入値が大きく下がった出品: {len(drops)}件 "
              f"(前回の{DROP_RATIO*100:.0f}%未満)")
        for d in drops[:10]:
            print(f"  {d['itemID']}  ¥{d['prev']:,.0f} → ¥{d['now']:,.0f}"
                  f" ({d['ratio']*100:3.0f}%)  {d['title'][:32]}")
    elif ledger:
        print("\n今日 大きく下がった出品はありません。")
    else:
        print(f"\n(値下がりの見張りは今回が初回。次回から比べます / "
              f"{len(new_ledger)}件を記録)")
    os.makedirs(os.path.dirname(COST_LEDGER), exist_ok=True)
    with open(COST_LEDGER, "w", encoding="utf-8") as f:
        json.dump(new_ledger, f, ensure_ascii=False)

    payload = {"checked": stat["compared"], "stat": stat, "ratio": a.ratio,
               "verified": bool(a.verify), "suspects": suspects, "drops": drops}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n記録: {os.path.normpath(OUT_PATH)}")
    if a.mail:
        send_mail(payload)


if __name__ == "__main__":
    main()
