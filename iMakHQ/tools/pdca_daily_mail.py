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
COL = {"item": 1, "title": 2, "date": 4, "country": 5, "price": 6, "cost": 12, "ship": 14,
       "profit": 15, "bought": 21, "state": 25}


# ── 利益 (販売実績シート) ─────────────────────────────────────────
def _parse_date(s):
    for f in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((s or "").strip(), f).date()
        except ValueError:
            pass
    return None


# ★2026-10-16 ユーザー「入力待ち・未確定の部分、PSA の US 以外は 1100円・US は 4000円で仮計上して。確定したら正式に計上」
#   シートの営業利益は、送料 (O列) が空の間は送料を引いていない = 利益が多く見えていた。送料が入れば実額 (仮は消える)
PROVISIONAL_SHIP_JPY = {"US": 4000, "OTHER": 1100}


def provisional_ship(title, country):
    """送料が未入力の PSA の仮の送料 (円・純関数)。PSA 以外は 0 (決めていないので引かない)。"""
    if "PSA" not in (title or "").upper():
        return 0
    us = (country or "").strip().lower() in ("united states", "us", "usa")
    return PROVISIONAL_SHIP_JPY["US" if us else "OTHER"]


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
        profit = R.money(g(COL["profit"]))
        prov = provisional_ship(g(COL["title"]), g(COL["country"])) if not g(COL["ship"]) else 0
        out.append({"date": d, "title": g(COL["title"]), "price": R.money(g(COL["price"])),
                    "profit": profit - prov, "ship_provisional": prov, "missing": missing,
                    "country": g(COL["country"]),
                    "confirmed": not missing})
    return out


LOSS_TAB = "損失"


def loss_rows(rows2d):
    """販売実績シートの「損失」タブ → [{date, what, amount}] (純関数)。読めない行は飛ばす。

    ★2026-10-13 ユーザー「これらも月利に入れないとあかんな」「こういうミスも含めよう」:
      間違って買った PSA7 (10/9 シャワーズex ¥4,830・キャンセル不可) が、どの注文にも載らず月の利益が多く見えていた。
      売れた件数には数えない。損失にした物が後で売れたら、その売り上げは仕入原価0円で入れる。
    """
    out = []
    for r in (rows2d or [])[1:]:
        r = list(r) + [""] * 5
        d = _parse_date(r[0])
        try:
            amt = float(str(r[2]).replace(",", "").replace("¥", "").replace("▲", "").strip() or 0)
        except ValueError:
            continue
        if d and amt:
            out.append({"date": d, "what": r[1].strip(), "amount": abs(amt)})
    return out


def month_summary(sales, today, goal, losses=None):
    """今月の進捗 (純関数)。today = メールを作る日 (前日までを数える)。losses = 損失タブ (利益から引く)。"""
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
    L = losses or []

    def lsum(a, b):
        return sum(x["amount"] for x in L if a <= x["date"] <= b)
    cur_loss = lsum(m0, last)
    daily_avg = (sum(s["profit"] for s in base) - lsum(b0, m0 - dt.timedelta(days=1))) / base_days
    unit_avg = (sum(s["profit"] for s in base) / len(base)) if base else 0
    sales_profit = sum(s["profit"] for s in cur)
    profit = sales_profit - cur_loss
    fixed = sum(s["profit"] for s in cur if s["confirmed"]) - cur_loss
    remain = days_in - elapsed
    need_day = max(0.0, (goal - profit) / remain) if remain else 0.0
    return {
        "month": m0, "last": last, "elapsed": elapsed, "days_in": days_in, "remain": remain,
        "profit": profit, "fixed": fixed, "tmp": profit - fixed,
        "n": len(cur), "n_fixed": sum(1 for s in cur if s["confirmed"]),
        "unit": (sales_profit / len(cur)) if cur else 0,
        "loss": cur_loss, "losses": [x for x in L if m0 <= x["date"] <= last],
        "prev_same_n": len(prev_same),
        "prev_same_profit": sum(s["profit"] for s in prev_same) - lsum(pm0, pm0 + dt.timedelta(days=elapsed - 1)),
        "prev_profit": sum(s["profit"] for s in prev_all) - lsum(pm0, m0 - dt.timedelta(days=1)),
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


# ── 出品の動き (eBay から・日本時間 0〜24時) ─────────────────────
# ★2026-10-15 ユーザー確定「日本時間の0時から24時を一日とする」: Seller Hub のレポートは1〜2日遅れで、
#   「昨日の動き」の新規・取下げだけ別の日 (10/15 のメールに 10/13 分) が出ていた。eBay に直接
#   「その日に始まった / 終わった出品」を聞く (GetSellerList・1日 数回)。US だけ数える (ミラーは親に付いてくる)。
JST = dt.timezone(dt.timedelta(hours=9))


def jst_window(d0, d1):
    """日本時間 d0 0:00 〜 d1 24:00 → eBay に渡す UTC の (from, to) (純関数)。"""
    a = dt.datetime.combine(d0, dt.time(), JST).astimezone(dt.timezone.utc)
    b = dt.datetime.combine(d1 + dt.timedelta(days=1), dt.time(), JST).astimezone(dt.timezone.utc)
    return a.strftime("%Y-%m-%dT%H:%M:%S.000Z"), b.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seller_list(kind, d0, d1, post):
    """kind = Start / End。その期間に始まった / 終わった出品 [{id, site, title, status}] (I/O)。"""
    a, b = jst_window(d0, d1)
    out, page = [], 1
    while True:
        inner = (f"<{kind}TimeFrom>{a}</{kind}TimeFrom><{kind}TimeTo>{b}</{kind}TimeTo>"
                 "<GranularityLevel>Coarse</GranularityLevel>"
                 f"<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
                 "<OutputSelector>ItemID</OutputSelector><OutputSelector>Site</OutputSelector>"
                 "<OutputSelector>Title</OutputSelector><OutputSelector>SellingStatus</OutputSelector>"
                 "<OutputSelector>PaginationResult</OutputSelector>")
        t = post("GetSellerList", inner)
        if "<Ack>Failure</Ack>" in (t or "") or not t:
            m = re.search(r"<LongMessage>(.*?)</LongMessage>", t or "")
            raise RuntimeError("GetSellerList 失敗: " + (m.group(1) if m else "応答なし"))
        for it in re.findall(r"<Item>(.*?)</Item>", t, re.S):
            g = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S) or [None, ""])[1]  # noqa: E731
            out.append({"id": g("ItemID"), "site": g("Site"), "title": html.unescape(g("Title")),
                        "status": g("ListingStatus")})
        pages = int((re.search(r"<TotalNumberOfPages>(\d+)", t) or [0, 1])[1])
        if page >= pages:
            return out
        page += 1


def ebay_moves(day, post, live=None):
    """day (日本時間の昨日) の新規・取下げと、その月の新規・取下げ (I/O)。listing_moves と同じ形で返す。"""
    m0 = day.replace(day=1)
    new_m = [x for x in _seller_list("Start", m0, day, post) if x["site"] == "US"]
    end_m = [x for x in _seller_list("End", m0, day, post) if x["site"] == "US" and x["status"] != "Active"]
    new_d = [x for x in _seller_list("Start", day, day, post) if x["site"] == "US"]
    end_d = [x for x in _seller_list("End", day, day, post) if x["site"] == "US" and x["status"] != "Active"]
    cat = {}
    for x in new_d:
        k = "PSA10" if "PSA" in x["title"].upper() else "他"
        cat[k] = cat.get(k, 0) + 1
    nm = len({x["id"] for x in new_m}); em = len({x["id"] for x in end_m})
    days = (day - m0).days + 1
    return {"day": day, "new": len({x["id"] for x in new_d}), "new_cat": cat, "ended": len({x["id"] for x in end_d}),
            "net": len({x["id"] for x in new_d}) - len({x["id"] for x in end_d}), "live": live,
            "new_month": nm, "ended_month": em, "net_month": nm - em, "new_per_day": nm / days if days else 0,
            "src": "ebay"}


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
        # ★2026-10-16 ユーザー「見たらわかることを書かれてもね。AI ならではの視点で、気付きとか注意とか」
        #   → メールに出ている数字の言い直しを禁止し、数字どうしの関係・変化の兆し・見落としを1つ言わせる。
        #   前の日の一言を渡し、同じことを繰り返させない
        system = ("あなたは eBay の無在庫販売の店 (iMak Trading Japan) の毎朝のレポートに、一言を書く相棒。"
                  "店の柱は ①新規出品 (棚に並べる数を増やす) と ②在庫メンテ (並べた物を売れる状態で保つ)。"
                  "値段は仕入値から決まる cost-plus なので、値下げは手にしない。無在庫なので在庫を抱える話はしない。"
                  "★レポートに既に書いてある数字 (利益・達成率・件数・目標まで) をそのまま言い直さない。読めば分かることは書かない。"
                  "代わりに、与えた数字どうしを突き合わせて初めて分かる **気付き か 注意** を1つだけ書く。"
                  "例: 変化の兆し (先週と比べて何が増えた・減った)、偏り (国・商品・曜日)、危ない所 (赤字・仕入元が1本の出品・"
                  "仮の送料で利益が変わる行)、人が見落としそうなつながり。根拠の数字を1つ添える。"
                  "与えた数字だけを使い、推測で数字を作らない。言える物が無ければ「目立った変化なし」と書く。"
                  "今夜 (日本時間の夕方) の出品の段取りに効く気付きがあれば、それを優先して言う: tonight_listing_plan は"
                  "「明日の曜日が直近90日で注文の多い曜日か」と「この先2日の祝日・行事・給料日」から出した材料 (夕方に出すと US の朝に並び、効くのは翌日の注文)。"
                  "push が true なら「今夜は出品を多めに」とその理由を言ってよい。行事・給料日の効き方は一般論で、うちの数字では測っていないと分かる言い方で。"
                  "recent_comments と同じことは書かない。日本語で2文まで・120字以内。専門用語を使わない。前置き・挨拶は書かない。")
        r = client.messages.create(
            model=BM.AI_MODEL, max_tokens=3000, output_config={"effort": "medium"}, system=system,
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=str)}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        u = r.usage
        yen = (u.input_tokens * 4 + u.output_tokens * 20) / 1e6 * 158
        return text, yen, ""
    except Exception as e:                                      # noqa: BLE001
        return "", 0.0, f"{type(e).__name__}: {str(e)[:120]}"


# ── 今夜の出品 (2026-10-16 ユーザー「今朝の日報に一言あると、夕方に出品を頑張る段取りが組める」) ──
# 夕方の出品 (日本時間 19〜20時) は US の同じ日の朝に公開され、効くのは翌日 (日本時間) の注文。
# だから「明日の曜日が、うちの直近90日で注文が多い曜日か」と「この先2日の行事・給料日」で決める。
PUSH_RATIO = 1.5          # 明日の曜日の注文が、曜日の平均のこの倍以上なら多め


def tonight_plan(sales, today, events, listable=None, days=90):
    """今夜の出品を多めにするか (純関数)。戻り {push, reasons, wd_counts}。"""
    wd = "月火水木金土日"
    since = today - dt.timedelta(days=days)
    cnt = {k: 0 for k in wd}
    for x in sales:
        if since <= x["date"] < today:
            cnt[wd[x["date"].weekday()]] += 1
    total = sum(cnt.values())
    tom = wd[(today + dt.timedelta(days=1)).weekday()]
    reasons = []
    avg = total / 7 if total else 0
    if avg and cnt[tom] >= PUSH_RATIO * avg:
        reasons.append(f"明日は{tom}曜 = 直近{days}日で注文が多い曜日 ({cnt[tom]}件 / {total}件)")
    soon = [e for e in (events or []) if e["date"] <= (today + dt.timedelta(days=2)).isoformat()]
    for e in soon:
        reasons.append(f'{int(e["date"][5:7])}/{int(e["date"][8:])} [{e["country"]}] {e["name"]}')
    push = bool(reasons)
    if push and listable is not None and listable <= 0:
        reasons.append("ただし出せる PSA の候補が無い")
    return {"push": push, "reasons": reasons, "wd_counts": cnt, "tomorrow": tom, "total": total}


COMMENTS_PATH = r"C:/dev/iMak_data/hq/pdca_ai_comments.json"


def _recent_comments(n=7):
    try:
        d = json.load(open(COMMENTS_PATH, encoding="utf-8"))
        return [d[k] for k in sorted(d)[-n:]]
    except Exception:                                          # noqa: BLE001
        return []


def _save_comment(day, text):
    try:
        d = json.load(open(COMMENTS_PATH, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        d = {}
    d[day.isoformat()] = text
    d = {k: d[k] for k in sorted(d)[-30:]}
    with open(COMMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def insight_facts(sales, ms, today):
    """一言の材料: 直近14日の 国別・曜日別・赤字・仮の送料・利益単価の前後比較 / 仕入元が1本の出品 (純関数 + 読むだけ)。"""
    y = today - dt.timedelta(days=1)
    last7 = [s for s in sales if y - dt.timedelta(days=6) <= s["date"] <= y]
    prev7 = [s for s in sales if y - dt.timedelta(days=13) <= s["date"] <= y - dt.timedelta(days=7)]
    month = [s for s in sales if ms["month"] <= s["date"] <= ms["last"]]

    def avg(xs):
        return round(sum(x["profit"] for x in xs) / len(xs)) if xs else None
    out = {"sales_last7": {"n": len(last7), "avg_profit": avg(last7)},
           "sales_prev7": {"n": len(prev7), "avg_profit": avg(prev7)},
           "month_loss_sales": [{"date": str(s["date"]), "title": s["title"][:40], "profit": s["profit"]}
                                for s in month if s["profit"] < 0],
           "month_provisional_ship_total": sum(s.get("ship_provisional", 0) for s in month),
           "month_by_weekday": {}}
    out["month_by_country"] = {}
    for s in month:
        k = "月火水木金土日"[s["date"].weekday()]
        out["month_by_weekday"][k] = out["month_by_weekday"].get(k, 0) + 1
        c = out["month_by_country"].setdefault(s.get("country") or "?", {"n": 0, "profit": 0})
        c["n"] += 1
        c["profit"] += round(s["profit"])
    try:
        import psa_hoju_fill as H
        out["psa_listings_with_no_backup_supplier"] = len(H.select_backfill_targets(H._read_high(), max_backups=1))
    except Exception:                                          # noqa: BLE001
        pass
    return out


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


OFFER_SUBJECTS = ("新しいオファーがあります", "購入者が新しいオファーを送信しました")


def offer_counts(dates, today):
    """受信したオファーの日付 → {yesterday, last7, prev7} (純関数)。last7 = 昨日までの7日 / prev7 = その前の7日。

    ★2026-10-12 ユーザー「メールで取れない？」→「日報に追記して欲しい」: eBay はオファーの履歴を返さない
      (GetBestOffers は受信中だけ)。届いたメール「📩 新しいオファーがあります」を数える。
    """
    y = today - dt.timedelta(days=1)
    return {"yesterday": sum(1 for d in dates if d == y),
            "last7": sum(1 for d in dates if y - dt.timedelta(days=6) <= d <= y),
            "prev7": sum(1 for d in dates if y - dt.timedelta(days=13) <= d <= y - dt.timedelta(days=7))}


def offer_mail_dates(days=16):
    """Gmail の eBay のオファー受信メール → 受信日 (JST) の list (I/O)。読めなければ例外。"""
    import email
    import imaplib
    from email.header import decode_header
    from email.utils import parsedate_to_datetime
    import snkrdunk_purchases as SN
    jst = dt.timezone(dt.timedelta(hours=9))
    im = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        im.login(SN.USER, SN._password())
        im.select("INBOX", readonly=True)
        _t, d = im.search(None, "X-GM-RAW", f'"from:ebay@ebay.com newer_than:{days}d offer"')
        out = []
        for i in d[0].split():
            _t, m = im.fetch(i, "(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT)])")
            h = email.message_from_bytes(m[0][1])
            subj = "".join(x.decode(c or "utf-8", "replace") if isinstance(x, bytes) else x
                           for x, c in decode_header(h.get("Subject") or ""))
            if any(k in subj for k in OFFER_SUBJECTS):
                out.append(parsedate_to_datetime(h["Date"]).astimezone(jst).date())
        return out
    finally:
        try:
            im.logout()
        except Exception:                                      # noqa: BLE001
            pass


def yen(x):
    return ("▲" if x < 0 else "") + "¥{:,.0f}".format(abs(x))


def render(plan, ms, mv, ai_text, ai_yen, ai_err, today, hv=None, of=None, ev=None):
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
               f'<div class="small">■ 確定 {yen(ms["fixed"])} ({ms["n_fixed"]}件)　■ まだ動く {yen(ms["tmp"])} ({ms["n"] - ms["n_fixed"]}件)　| 今日までに届いていたい所 {pace:.0f}%</div>'
               + (f'<div class="small down">うち損失 {yen(-ms["loss"])} ({len(ms["losses"])}件: '
                  + " / ".join(f'{x["date"].month}/{x["date"].day} {e(x["what"][:30])} {yen(-x["amount"])}' for x in ms["losses"])
                  + ') — 確定から引いています</div>' if ms.get("loss") else ""))
    out.append('<table class="trio"><tr>'
               f'<td><span class="small">売れた件数</span><br><b>{ms["n"]}</b> 件<br><span class="small">先月同期 {ms["prev_same_n"]}件 ({yen(ms["prev_same_profit"])})</span></td>'
               f'<td><span class="small">利益単価</span><br><b>{yen(ms["unit"])}</b><br><span class="small">先月 {yen(ms["prev_unit"])}</span></td>'
               f'<td><span class="small">1日あたり 必要な件数</span><br><b>{ms["need_units_day"]:.1f}</b> 件<br><span class="small">今 {ms["pace_units_day"]:.1f}件</span></td>'
               '</tr></table>')
    if ms["pending"] or ms["negative"]:
        items = []
        for s in ms["pending"]:
            items.append(f'<li>{s["date"].month}/{s["date"].day} {e(s["title"][:40])} (${s["price"]:.0f}) ・ {"・".join(s["missing"])} ・ 利益 {yen(s["profit"])} は仮{(" (送料 仮 " + yen(s["ship_provisional"]) + " を引いた)") if s.get("ship_provisional") else ""}</li>')
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
        _when = (f'{mv["day"].month}/{mv["day"].day} 0〜24時 (日本時間)' if mv.get("src") == "ebay"
                 else f'出品は {mv["day"].month}/{mv["day"].day} (レポートの最新・日がずれている) ・ 売れたのは {ms["last"].month}/{ms["last"].day}')
        out.append(f'<div class="sec"><div class="sech">昨日の動き <span>{_when}</span></div>'
                   '<table class="moves"><tr>'
                   f'<td><span class="mk">新規</span><br><span class="mv">{mv["new"]}</span>件<br><span class="small">{nc}</span></td>'
                   f'<td><span class="mk">取下げ</span><br><span class="mv">{mv["ended"]}</span>件<br><span class="small">理由別は未取得</span></td>'
                   f'<td><span class="mk">純増</span><br><span class="mv {"down" if mv["net"] < 0 else "up"}">{mv["net"]:+d}</span>件<br><span class="small">{("出品中 %s" % format(mv["live"], ",")) if mv.get("live") is not None else ""}{(" (%d/%d 時点)" % (mv["live_day"].month, mv["live_day"].day)) if mv.get("live_day") else ""}</span></td>'
                   f'<td><span class="mk">売れた件数</span><br><span class="mv">{len(y)}</span>件<br><span class="small">今月 {ms["n"]}件</span></td>'
                   f'<td><span class="mk">利益</span><br><span class="mv">{yen(sum(s["profit"] for s in y))}</span><br><span class="small">{"仮を含む" if any(not s["confirmed"] for s in y) else "確定"}</span></td>'
                   + (f'<td><span class="mk">オファー</span><br><span class="mv">{of["yesterday"]}</span>件<br>'
                      f'<span class="small">7日 {of["last7"]}件 (前の7日 {of["prev7"]}件)</span></td>' if of else
                      '<td><span class="mk">オファー</span><br><span class="mv">?</span><br><span class="small">メールを読めず</span></td>')
                   + '</tr></table></div>')
    else:
        out.append('<div class="sec"><div class="sech">昨日の動き</div><div class="small down">Seller Hub のレポートが見つからない (データ欠け)</div></div>')
    # ★2026-10-16 この先7日の US/UK/AU/CA の祝日・行事・給料日 (閲覧に効くかは一般論・うちでは測っていない)
    if ev is not None:
        _cn = {"ALL": "全部", "US": "US", "UK": "UK", "AU": "AU", "CA": "CA"}
        rows_ = "".join(f'<li>{int(x["date"][5:7])}/{int(x["date"][8:])} [{_cn.get(x["country"], x["country"])}] {e(x["name"])}'
                        + (f' <span class="small">— {e(x["note"])}</span>' if x["note"] else "") + "</li>" for x in ev)
        out.append('<div class="sec"><div class="sech">この先7日の地元の出来事 <span>US / UK / AU / CA ・ 閲覧への効き方は一般論 (うちでは未測定)</span></div>'
                   + (f'<ul class="small" style="margin:0;padding-left:1.2em">{rows_}</ul>' if ev else '<div class="small">目立つ祝日・行事なし</div>')
                   + '</div>')
    if ai_text:
        out.append(f'<div class="sec ai"><div class="sech">Claude の一言</div><p class="ait">{e(ai_text)}</p></div>')
    elif ai_err:
        out.append(f'<div class="sec ai"><div class="sech">Claude の一言</div><p class="small">書けなかった: {e(ai_err)}</p></div>')
    cost = f" ・ 一言の費用 約{ai_yen:.1f}円" if ai_text else ""
    out.append(f'<div class="foot">出どころ: 販売実績シート ({ms["last"].month}/{ms["last"].day} まで) ・ '
               + (f'eBay (出品の新規・取下げ {mv["day"].month}/{mv["day"].day})' if mv and mv.get("src") == "ebay" else
                  f'Seller Hub のレポート ({(str(mv["day"].month) + "/" + str(mv["day"].day)) if mv else "なし"})') + f'{cost}</div></div>')
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
    _sh = gc.open_by_key(R.SALES_SHEET_ID)
    rows = _sh.get_worksheet_by_id(R.SALES_GID).get_all_values()
    try:
        losses = loss_rows(_sh.worksheet(LOSS_TAB).get_all_values())
    except Exception as e:                                     # noqa: BLE001 タブが無い = 損失なし
        losses = []
        print(f"  ⚠ 損失タブを読めず ({type(e).__name__}) — 損失 0 として出す")
    ms = month_summary(sales_rows(rows), today, plan["goal_profit_jpy"], losses)

    mv = None
    act_p, ina_p, rday = latest_reports()
    if act_p and ina_p and rday:
        rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")))  # noqa: E731
        mv = listing_moves(rd(act_p), rd(ina_p), rday)
        mv["src"] = "report"
    # ★2026-10-15: 新規・取下げは eBay から日本時間の昨日 0〜24時で取る (出品中の数だけレポートの物を使う)
    try:
        sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI")))
        import fix_de_speedpak_shipping as _fx
        _tok = _fx.token()
        mv = ebay_moves(today - dt.timedelta(days=1), lambda c, i: _fx.post(c, i, _tok, site="0"),
                        live=(mv or {}).get("live"))
        if act_p and rday:
            mv["live_day"] = rday
        print(f"📈 出品の動き (eBay・日本時間 {mv['day']:%m/%d} 0〜24時): 新規 {mv['new']} / 取下げ {mv['ended']}"
              f" / 今月 新規 {mv['new_month']}・取下げ {mv['ended_month']}")
    except Exception as e:                                     # noqa: BLE001 取れなければレポートの日のまま (その日付を出す)
        print(f"  ⚠ 出品の動きを eBay から取れず ({type(e).__name__}: {str(e)[:80]}) — レポート {rday} の分を出す")

    hv = None
    try:
        import psa_new_count as PN
        left = _intermediate_left()
        _pn = PN.count_workload()
        # ★2026-10-15 行の数ではなく、新しく出せるカードの種類で時期を決める (同じカードの2枚目・出品中のカードを除く)
        hv = harvest_timing(_pn.get("cards", _pn.get("n", 0)), mv["new_per_day"] if mv else 0,
                            left["treasure"], left["chara"])
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ トレハンの時期を出せず: {type(e).__name__}: {str(e)[:80]}")

    ev = []
    try:
        import local_events as _LE
        ev = _LE.upcoming(today, 7)
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 地元の出来事を出せず: {type(e).__name__}")
    print(f"🗓 この先7日の US/UK/AU/CA の出来事: {len(ev)}件")
    tp = None
    try:
        tp = tonight_plan(sales_rows(rows), today, ev, (hv or {}).get("listable"))
        print(f"🌙 今夜の出品: {'多め' if tp['push'] else 'いつもどおり'} / 理由 {len(tp['reasons'])}件 {tp['reasons'][:3]}")
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 今夜の出品を決められず: {type(e).__name__}")
    of, of_err = None, ""
    try:
        of = offer_counts(offer_mail_dates(), today)
    except Exception as e:                                     # noqa: BLE001
        of_err = f"{type(e).__name__}: {str(e)[:80]}"
        print(f"  ⚠ オファーのメールを読めず: {of_err}")

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
        facts["offers_received"] = of
        # ★2026-10-16: 気付きの材料 (突き合わせて初めて分かる物)
        try:
            facts.update(insight_facts(sales_rows(rows), ms, today))
        except Exception as _e:                                # noqa: BLE001
            print(f"  ⚠ 一言の材料の一部を作れず: {type(_e).__name__}")
        facts["recent_comments"] = _recent_comments()
        facts["local_events_next7"] = ev
        facts["tonight_listing_plan"] = tp
        ai_text, ai_yen, ai_err = ai_comment(facts)
        if ai_text and not a.dry_run:
            _save_comment(today, ai_text)

    body = render(plan, ms, mv, ai_text, ai_yen, ai_err, today, hv, of, ev)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(body)
    subject = (f"KamiKaze {today.month}/{today.day} 利益 {yen(ms['profit'])} ({ms['profit'] / plan['goal_profit_jpy'] * 100:.0f}%)"
               f" 純増 {mv['net']:+d}" if mv else "")
    sent = "送らない (--dry-run)"
    if not a.dry_run:
        r = subprocess.run([sys.executable, SEND_MAIL, "--subject", subject, "--body-file", OUT_HTML, "--html"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        sent = "送った" if r.returncode == 0 else f"送れなかった (exit {r.returncode}) {r.stderr[-200:]}"
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    print(f"📧 PDCA メール: {sent} / 今月の利益 {yen(ms['profit'])} ({ms['n']}件・まだ動く {len(ms['pending'])}件)"
          f" / 損失 {len(ms['losses'])}件 {yen(-ms['loss'])}"
          f" / オファー {('昨日 %d件・7日 %d件 (前の7日 %d件)' % (of['yesterday'], of['last7'], of['prev7'])) if of else '読めず ' + of_err}"
          f" / 出品の動き {mv['day'] if mv else 'データ欠け'} / 一言 {'約%.1f円' % ai_yen if ai_text else ('なし' if not ai_err else '失敗: ' + ai_err)}")
    return 0 if (a.dry_run or sent == "送った") else 1


if __name__ == "__main__":
    sys.exit(main())
