# -*- coding: utf-8 -*-
"""毎朝の PDCA メール (2026-10-11 ユーザーと合意した1枚)。

上から: 目標の進捗 → 大見出し ①新規出品 / ②在庫メンテ と中見出し → 昨日の動き → Claude の一言。
見本: https://claude.ai/artifact/3s5G5QMQNrS7BCdcK6mGyJ ・ 記憶: pdca_daily_report_design.md

■ 数字の決まり (ユーザー「正確じゃないと意味ない」)
- 利益は販売実績シート。**キャンセルの行は除く・▲は負** (shelf_roi.money)
- 確定 = 仕入済・仕入原価・送料 (実費) がそろった行。そろっていない行は「まだ動く」で名指し
- 出品の動きは Seller Hub のレポート (毎日落としている最新)。1日遅れ

■ 費用
- Claude の一言だけ有料 (1回 数円)。額はメールの一番下に小さく出す。--no-ai で書かない

使い方:
    python pdca_daily_mail.py              # 作って送る
    python pdca_daily_mail.py --dry-run    # 送らず HTML を書くだけ (一言も書かない)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PLAN_PATH = r"C:/dev/iMak_data/hq/pdca_plan.json"
REPORT_DIR = r"C:/dev/iMak_data/seller_hub/reports"
OUT_HTML = r"C:/dev/iMak_data/hq/pdca_daily_last.html"
SEND_MAIL = r"C:/dev/iMak_data/tools/send_mail.py"
COL = {"item": 1, "title": 2, "date": 4, "price": 6, "cost": 12, "ship": 14,
       "profit": 15, "bought": 21, "state": 25}


# ── 利益 (販売実績シート) ─────────────────────────────────────────
def _parse_date(s):
    for f in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((s or "").strip(), f).date()
        except ValueError:
            pass
    return None


def sales_rows(rows2d):
    """販売実績の行 → [{date, title, price, profit, confirmed, missing}] (純関数)。キャンセルは除く。"""
    import shelf_roi as R
    out = []
    for r in rows2d[1:]:
        g = lambda i: (r[i] if len(r) > i else "").strip()  # noqa: E731
        if not g(COL["item"]):
            continue
        d = _parse_date(g(COL["date"]))
        if not d or "キャンセル" in g(COL["state"]):
            continue
        missing = []
        if g(COL["bought"]).upper() != "TRUE":
            missing.append("仕入れが済んでいない")
        if not g(COL["cost"]):
            missing.append("仕入原価が空")
        if not g(COL["ship"]):
            missing.append("送料が空")
        out.append({"date": d, "title": g(COL["title"]), "price": R.money(g(COL["price"])),
                    "profit": R.money(g(COL["profit"])), "missing": missing,
                    "confirmed": not missing})
    return out


def month_summary(sales, today, goal):
    """今月の進捗 (純関数)。today = メールを作る日 (前日までを数える)。"""
    last = today - dt.timedelta(days=1)
    m0 = last.replace(day=1)
    days_in = (m0.replace(month=m0.month % 12 + 1, year=m0.year + (m0.month == 12)) - m0).days
    elapsed = (last - m0).days + 1
    cur = [s for s in sales if m0 <= s["date"] <= last]
    pm0 = (m0 - dt.timedelta(days=1)).replace(day=1)
    prev_same = [s for s in sales if pm0 <= s["date"] <= pm0 + dt.timedelta(days=elapsed - 1)]
    prev_all = [s for s in sales if pm0 <= s["date"] < m0]
    # 直近3か月 (今月を含まない) の1日平均と利益単価
    b0 = m0
    for _ in range(3):
        b0 = (b0 - dt.timedelta(days=1)).replace(day=1)
    base = [s for s in sales if b0 <= s["date"] < m0]
    base_days = (m0 - b0).days or 1
    daily_avg = sum(s["profit"] for s in base) / base_days
    unit_avg = (sum(s["profit"] for s in base) / len(base)) if base else 0
    profit = sum(s["profit"] for s in cur)
    fixed = sum(s["profit"] for s in cur if s["confirmed"])
    remain = days_in - elapsed
    need_day = max(0.0, (goal - profit) / remain) if remain else 0.0
    return {
        "month": m0, "last": last, "elapsed": elapsed, "days_in": days_in, "remain": remain,
        "profit": profit, "fixed": fixed, "tmp": profit - fixed,
        "n": len(cur), "n_fixed": sum(1 for s in cur if s["confirmed"]),
        "unit": (profit / len(cur)) if cur else 0,
        "prev_same_n": len(prev_same), "prev_same_profit": sum(s["profit"] for s in prev_same),
        "prev_profit": sum(s["profit"] for s in prev_all),
        "prev_unit": (sum(s["profit"] for s in prev_all) / len(prev_all)) if prev_all else 0,
        "daily_avg": daily_avg, "projection": profit + remain * daily_avg,
        "need_day": need_day, "need_units_day": (need_day / unit_avg) if unit_avg else 0,
        "pace_units_day": len(cur) / elapsed if elapsed else 0,
        "pending": [s for s in cur if not s["confirmed"]],
        "negative": [s for s in cur if s["profit"] < 0],
        "yesterday": [s for s in cur if s["date"] == last],
    }


# ── 出品の動き (Seller Hub のレポート) ───────────────────────────
def _pdate(s):
    try:
        return dt.datetime.strptime((s or "").strip()[:18].strip(), "%b-%d-%y %H:%M:%S").date()
    except Exception:
        return None


def latest_reports(base=REPORT_DIR):
    """一番新しい 出品中 / 終了 のレポートと、その日付 (I/O)。"""
    def pick(pat):
        c = [p for p in glob.glob(os.path.join(base, "*", pat)) if "(1)" not in p]
        return max(c, key=lambda p: re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1)) if c else None
    a, i = pick("eBay-all-active-listings-report-*.csv"), pick("eBay-inactive-listings-report-*.csv")
    d = None
    if a:
        d = dt.date.fromisoformat(re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(a)).group(1))
    return a, i, d


def listing_moves(active, inactive, day):
    """day の 新規・取下げ と、その月の新規・取下げ・1日平均 (純関数)。US だけ数える (ミラーは親に付いてくる)。"""
    m0 = day.replace(day=1)
    seen, new_day, new_month, new_cat = set(), 0, 0, {}
    for r in active + inactive:
        if (r.get("Listing site") or "US") != "US":
            continue
        iid = r.get("Item number")
        if iid in seen:
            continue
        seen.add(iid)
        d = _pdate(r.get("Start date"))
        if not d or not (m0 <= d <= day):
            continue
        new_month += 1
        if d == day:
            new_day += 1
            t = (r.get("Title") or "").upper()
            k = "PSA10" if "PSA" in t else "他"
            new_cat[k] = new_cat.get(k, 0) + 1
    end_day = end_month = 0
    for r in inactive:
        if r.get("Listing site") != "US":
            continue
        d = _pdate(r.get("End date"))
        if d and m0 <= d <= day:
            end_month += 1
            end_day += d == day
    # ★バリエーション出品 (Tシャツ等) はサイズごとに1行ずつ出るので、itemID でまとめて数える。
    #   行で数えると 1,390 と出た (正しくは 891 出品)。売り切れたサイズの行も混ざる
    qty = {}
    for r in active:
        if r.get("Listing site") == "US":
            try:
                n = int(r.get("Available quantity") or 0)
            except ValueError:
                n = 0
            qty[r.get("Item number")] = qty.get(r.get("Item number"), 0) + n
    live = sum(1 for n in qty.values() if n > 0)
    days = (day - m0).days + 1
    return {"day": day, "new": new_day, "new_cat": new_cat, "ended": end_day,
            "net": new_day - end_day, "live": live, "new_month": new_month,
            "ended_month": end_month, "net_month": new_month - end_month,
            "new_per_day": new_month / days if days else 0}


# ── トレハン・キャラを回す時期 ──────────────────────────────────
HARVEST_DAYS = 7      # 出品の待ちが「1日の新規 × この日数」を切ったら回す (2026-10-11 ユーザー確定)


def harvest_timing(listable, per_day, treasure_left, chara_left, days=HARVEST_DAYS):
    """トレハン・キャラを次にいつ回すか (純関数)。

    ★2026-10-11 ユーザー「たくさんとっても、出品が追い付かず売り切れたら API コストの無駄使い」:
      出品の待ち (PSA 新規に今出せる物) が1週間分を切ったら回す。中間スプシに在庫が残っている探し方は先にそれを足す。
    """
    per_day = per_day or 0
    line = round(per_day * days)
    left_days = (listable / per_day) if per_day else None
    run = listable < line
    if not run:
        what = "まだ回さない"
    elif chara_left > 0 and treasure_left == 0:
        what = "トレハンを回す (キャラハンは中間スプシの在庫から先に HIGH へ足す)"
    elif treasure_left == 0 and chara_left == 0:
        what = "トレハンとキャラハンを回す"
    else:
        what = "中間スプシの在庫から先に HIGH へ足す"
    return {"listable": listable, "line": line, "left_days": left_days, "run": run, "what": what,
            "treasure_left": treasure_left, "chara_left": chara_left}


def _intermediate_left():
    """中間スプシの B列が空の行 (= HIGH に足せる候補) の数 (I/O)。"""
    import sheet_io as S
    import treasure_fill_key as T
    out = {}
    for k, tab in (("treasure", "mercari_psa10_treasure"), ("chara", "mercari_psa10_chara")):
        rows = S.read_tab(tab, sheet_id=T.SHEET_ID)[1:]
        out[k] = sum(1 for r in rows if r and r[0].strip() and not (r[1].strip() if len(r) > 1 else ""))
    return out


# ── Claude の一言 (有料・1回 数円) ────────────────────────────────
def ai_comment(facts):
    """今日の数字から1〜2文。失敗しても止めない (理由を返す)。戻り: (文, 円, 理由)。"""
    try:
        import anthropic
        import buyer_messages as BM
        client = anthropic.Anthropic(api_key=BM._api_key())
        system = ("あなたは eBay の無在庫販売の店 (iMak Trading Japan) の毎朝のレポートに、一言コメントを書く。"
                  "店の柱は ①新規出品 (棚に並べる数を増やす) と ②在庫メンテ (並べた物を売れる状態で保つ)。"
                  "値段は仕入値から決まる cost-plus なので、値下げは手にしない。"
                  "与えた数字だけを使い、日本語で1〜2文、120字以内。専門用語を使わない。"
                  "一番効く次の一手を1つだけ言う。前置き・挨拶は書かない。")
        r = client.messages.create(
            model=BM.AI_MODEL, max_tokens=1500, output_config={"effort": "low"}, system=system,
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=str)}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        u = r.usage
        yen = (u.input_tokens * 4 + u.output_tokens * 20) / 1e6 * 158
        return text, yen, ""
    except Exception as e:                                      # noqa: BLE001
        return "", 0.0, f"{type(e).__name__}: {str(e)[:120]}"


# ── HTML ────────────────────────────────────────────────────────
CSS = """
body{margin:0;background:#e9edf0;color:#1d2a33;font-family:"Hiragino Sans","Yu Gothic","Meiryo",sans-serif;padding:16px}
.mail{max-width:580px;margin:0 auto;background:#fff;border:1px solid #dbe2e7}
.top{background:#17324a;color:#fff;padding:14px 18px}
.top h1{margin:0;font-size:17px}
.top span{font-size:11px;opacity:.8}
.plan{padding:16px 20px 14px}
.lab{font-size:11px;letter-spacing:.1em;color:#5d6b75}
.num{font-family:Consolas,"Courier New",monospace}
.gnum{font-size:26px;color:#17324a}
.gof{font-size:13px;color:#5d6b75}
.gpct{font-size:26px;float:right}
.bar{position:relative;height:6px;background:#e6ebef;margin:8px 0 4px}
.bar i{position:absolute;top:0;bottom:0;display:block}
.small{font-size:11px;color:#5d6b75}
.trio td{padding:6px 14px 2px 0;vertical-align:top}
.trio b{font-family:Consolas,monospace;font-size:18px;color:#17324a;font-weight:normal}
.warn{background:#fbf3e2;border-left:3px solid #b07a10;padding:6px 10px;font-size:11.5px;line-height:1.6;margin:8px 0}
.warn b{color:#8a5a00}
.warn ul{margin:2px 0 0;padding-left:1.2em}
.o{border-top:1px solid #dbe2e7;margin-top:14px;padding-top:12px}
.oh{font-size:17px;font-weight:bold;color:#17324a}
.on{display:inline-block;width:26px;height:26px;line-height:26px;border-radius:13px;background:#17324a;color:#fff;text-align:center;font-size:14px;margin-right:8px}
.od{font-size:12px;color:#5d6b75;margin:2px 0 6px 34px}
.k{margin:0 0 8px 34px;padding-left:12px;border-left:2px solid #d6e0e8}
.kt{font-size:14px}
.st{font-size:11px;float:right}
.kd{font-size:12px;color:#5d6b75;line-height:1.6}
.sec{padding:12px 20px;border-top:1px solid #dbe2e7}
.sech{font-size:14px;font-weight:bold;color:#17324a;margin-bottom:6px}
.sech span{font-size:11px;font-weight:normal;color:#5d6b75}
.moves td{padding:2px 12px 2px 0;vertical-align:top;width:20%}
.mk{font-size:11px;color:#5d6b75}
.mv{font-family:Consolas,monospace;font-size:20px}
.ai{background:#f7f9fb}
.ait{margin:0;font-size:13px;line-height:1.8;border-left:3px solid #2f6f9f;padding-left:10px}
.foot{padding:8px 20px 12px;font-size:11px;color:#5d6b75;border-top:1px solid #dbe2e7}
.up{color:#1f7a4d}.down{color:#b4442f}.amber{color:#b07a10}
"""


def yen(x):
    return ("▲" if x < 0 else "") + "¥{:,.0f}".format(abs(x))


def render(plan, ms, mv, ai_text, ai_yen, ai_err, today, hv=None):
    e = html.escape
    goal = plan["goal_profit_jpy"]
    pct = ms["profit"] / goal * 100 if goal else 0
    pace = ms["elapsed"] / ms["days_in"] * 100
    on_pace = ms["projection"] >= goal
    fix_w, tmp_w = max(0, min(100, ms["fixed"] / goal * 100)), max(0, min(100, ms["tmp"] / goal * 100))
    wd = "月火水木金土日"[today.weekday()]
    out = [f'<div class="mail"><div class="top"><h1>{today.month}/{today.day} ({wd}) の PDCA</h1>'
           f'<span>毎朝 iMak Trading Japan</span></div><div class="plan">']
    out.append(f'<div class="lab">今月の利益 ({ms["month"].month}/1〜{ms["last"].month}/{ms["last"].day} ・ キャンセルは除く)</div>'
               f'<div><span class="gpct num {"up" if on_pace else "amber"}">{pct:.0f}%</span>'
               f'<span class="gnum num">{yen(ms["profit"])}</span> <span class="gof">／ 目標 {yen(goal)}</span></div>'
               f'<div class="bar"><i style="left:0;width:{fix_w:.1f}%;background:#17324a"></i>'
               f'<i style="left:{fix_w:.1f}%;width:{tmp_w:.1f}%;background:#8aa6bd"></i>'
               f'<i style="left:{pace:.1f}%;width:2px;top:-4px;bottom:-4px;background:#b07a10"></i></div>'
               f'<div class="small">■ 確定 {yen(ms["fixed"])} ({ms["n_fixed"]}件)　■ まだ動く {yen(ms["tmp"])} ({ms["n"] - ms["n_fixed"]}件)　| 今日までに届いていたい所 {pace:.0f}%</div>')
    out.append('<table class="trio"><tr>'
               f'<td><span class="small">売れた件数</span><br><b>{ms["n"]}</b> 件<br><span class="small">先月同期 {ms["prev_same_n"]}件 ({yen(ms["prev_same_profit"])})</span></td>'
               f'<td><span class="small">利益単価</span><br><b>{yen(ms["unit"])}</b><br><span class="small">先月 {yen(ms["prev_unit"])}</span></td>'
               f'<td><span class="small">1日あたり 必要な件数</span><br><b>{ms["need_units_day"]:.1f}</b> 件<br><span class="small">今 {ms["pace_units_day"]:.1f}件</span></td>'
               '</tr></table>')
    if ms["pending"] or ms["negative"]:
        items = []
        for s in ms["pending"]:
            items.append(f'<li>{s["date"].month}/{s["date"].day} {e(s["title"][:40])} (${s["price"]:.0f}) ・ {"・".join(s["missing"])} ・ 利益 {yen(s["profit"])} は仮</li>')
        for s in ms["negative"]:
            if s in ms["pending"]:
                continue
            items.append(f'<li>{s["date"].month}/{s["date"].day} {e(s["title"][:40])} ・ 赤字 {yen(s["profit"])}</li>')
        out.append('<div class="warn"><b>入力待ち・未確定 (利益はまだ動く)</b><ul>' + "".join(items) + '</ul></div>')
    out.append(f'<div class="small">月末の見込み {yen(ms["projection"])} で '
               f'<span class="{"up" if on_pace else "down"}">{"届くペース" if on_pace else "届かないペース"}</span>'
               f' (今月の分 + 残り{ms["remain"]}日 × 直近3か月の1日平均 {yen(ms["daily_avg"])}) ・ 1日 {yen(ms["need_day"])} 必要'
               f' ・ 先月 {yen(ms["prev_profit"])} ・ 次の目標 月 {yen(plan["next_goal_profit_jpy"])}</div>')
    for p in plan["pillars"]:
        out.append(f'<div class="o"><div class="oh"><span class="on">{p["no"]}</span>{e(p["name"])}</div>'
                   f'<div class="od">{e(p["desc"])}</div>')
        for m in p["mids"]:
            stc = {"未着手": "down", "進行中": "amber", "動いている": "up"}.get(m["status"], "")
            now = e(m.get("now", ""))
            if m.get("metric") == "new_per_day" and mv:
                now = f'新規 <b class="num">{mv["new_per_day"]:.0f}</b> / {plan["new_per_day_goal"]} 件/日 ({mv["day"].month}月の平均)'
            if m.get("metric") == "net_month" and mv:
                c = "down" if mv["net_month"] < 0 else "up"
                now = (f'<b class="num {c}">{mv["net_month"]:+d}</b> {"純減" if mv["net_month"] < 0 else "純増"}'
                       f' ({mv["day"].month}/1〜{mv["day"].day} 新規 {mv["new_month"]} − 取下げ {mv["ended_month"]})')
            if m.get("metric") == "harvest" and hv:
                c = "down" if hv["run"] else "up"
                d = f'約{hv["left_days"]:.0f}日分' if hv["left_days"] is not None else "日数不明"
                now = (f'出品の待ち (PSA 新規に今出せる物) <b class="num">{hv["listable"]}</b>件 ({d}) ・ '
                       f'{hv["line"]}件 (1週間分) を切ったら回す → <b class="{c}">{e(hv["what"])}</b><br>'
                       f'中間スプシの在庫: トレハン {hv["treasure_left"]:,} ・ キャラハン {hv["chara_left"]:,}')
            # ★2026-10-11 ユーザー「メールで送る日報に書いておいて」: 中見出しごとの決めたことを日付つきで出す
            dec = "".join(f'<br><span class="small">決めたこと: {e(x)}</span>' for x in (m.get("decided") or []))
            out.append(f'<div class="k"><div class="kt">{e(m["name"])}<span class="st {stc}">● {e(m["status"])}</span></div>'
                       f'<div class="kd">{e(m["desc"])}<br>{now}{dec}</div></div>')
        out.append('</div>')
    out.append('</div>')
    y = ms["yesterday"]
    if mv:
        nc = " ・ ".join(f"{k} {v}" for k, v in mv["new_cat"].items()) or "なし"
        out.append(f'<div class="sec"><div class="sech">昨日の動き <span>出品は {mv["day"].month}/{mv["day"].day} (レポートの最新) ・ 売れたのは {ms["last"].month}/{ms["last"].day}</span></div>'
                   '<table class="moves"><tr>'
                   f'<td><span class="mk">新規</span><br><span class="mv">{mv["new"]}</span>件<br><span class="small">{nc}</span></td>'
                   f'<td><span class="mk">取下げ</span><br><span class="mv">{mv["ended"]}</span>件<br><span class="small">理由別は未取得</span></td>'
                   f'<td><span class="mk">純増</span><br><span class="mv {"down" if mv["net"] < 0 else "up"}">{mv["net"]:+d}</span>件<br><span class="small">出品中 {mv["live"]:,}</span></td>'
                   f'<td><span class="mk">売れた件数</span><br><span class="mv">{len(y)}</span>件<br><span class="small">今月 {ms["n"]}件</span></td>'
                   f'<td><span class="mk">利益</span><br><span class="mv">{yen(sum(s["profit"] for s in y))}</span><br><span class="small">{"仮を含む" if any(not s["confirmed"] for s in y) else "確定"}</span></td>'
                   '</tr></table></div>')
    else:
        out.append('<div class="sec"><div class="sech">昨日の動き</div><div class="small down">Seller Hub のレポートが見つからない (データ欠け)</div></div>')
    if ai_text:
        out.append(f'<div class="sec ai"><div class="sech">Claude の一言</div><p class="ait">{e(ai_text)}</p></div>')
    elif ai_err:
        out.append(f'<div class="sec ai"><div class="sech">Claude の一言</div><p class="small">書けなかった: {e(ai_err)}</p></div>')
    cost = f" ・ 一言の費用 約{ai_yen:.1f}円" if ai_text else ""
    out.append(f'<div class="foot">出どころ: 販売実績シート ({ms["last"].month}/{ms["last"].day} まで) ・ '
               f'Seller Hub のレポート ({(str(mv["day"].month) + "/" + str(mv["day"].day)) if mv else "なし"}){cost}</div></div>')
    return f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(out)}</body></html>"


# ── main ───────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="送らず HTML を書くだけ (一言も書かない)")
    ap.add_argument("--no-ai", action="store_true", help="Claude の一言を書かない")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    today = dt.date.today()
    plan = json.load(open(PLAN_PATH, encoding="utf-8"))

    import shelf_roi as R
    import listing_funnel as LF
    import gspread
    from google.oauth2.service_account import Credentials
    gc = gspread.authorize(Credentials.from_service_account_file(
        LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    rows = gc.open_by_key(R.SALES_SHEET_ID).get_worksheet_by_id(R.SALES_GID).get_all_values()
    ms = month_summary(sales_rows(rows), today, plan["goal_profit_jpy"])

    mv = None
    act_p, ina_p, rday = latest_reports()
    if act_p and ina_p and rday:
        rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")))  # noqa: E731
        mv = listing_moves(rd(act_p), rd(ina_p), rday)

    hv = None
    try:
        import psa_new_count as PN
        left = _intermediate_left()
        hv = harvest_timing(PN.count_workload().get("n", 0), mv["new_per_day"] if mv else 0,
                            left["treasure"], left["chara"])
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ トレハンの時期を出せず: {type(e).__name__}: {str(e)[:80]}")

    ai_text, ai_yen, ai_err = "", 0.0, ""
    if not (a.dry_run or a.no_ai):
        facts = {k: v for k, v in ms.items() if k not in ("pending", "negative", "yesterday")}
        facts["pending_count"] = len(ms["pending"])
        facts["biggest_sale"] = max((s["profit"] for s in sales_rows(rows)
                                     if ms["month"] <= s["date"] <= ms["last"]), default=0)
        facts["goal"] = plan["goal_profit_jpy"]
        facts["listing"] = mv
        facts["mids"] = [(m["name"], m["status"]) for p in plan["pillars"] for m in p["mids"]]
        facts["harvest_timing"] = hv
        ai_text, ai_yen, ai_err = ai_comment(facts)

    body = render(plan, ms, mv, ai_text, ai_yen, ai_err, today, hv)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(body)
    subject = (f"PDCA {today.month}/{today.day} 利益 {yen(ms['profit'])} ({ms['profit'] / plan['goal_profit_jpy'] * 100:.0f}%)"
               f" 純増 {mv['net']:+d}" if mv else "")
    sent = "送らない (--dry-run)"
    if not a.dry_run:
        r = subprocess.run([sys.executable, SEND_MAIL, "--subject", subject, "--body-file", OUT_HTML, "--html"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        sent = "送った" if r.returncode == 0 else f"送れなかった (exit {r.returncode}) {r.stderr[-200:]}"
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    print(f"📧 PDCA メール: {sent} / 今月の利益 {yen(ms['profit'])} ({ms['n']}件・まだ動く {len(ms['pending'])}件)"
          f" / 出品の動き {mv['day'] if mv else 'データ欠け'} / 一言 {'約%.1f円' % ai_yen if ai_text else ('なし' if not ai_err else '失敗: ' + ai_err)}")
    return 0 if (a.dry_run or sent == "送った") else 1


if __name__ == "__main__":
    sys.exit(main())
