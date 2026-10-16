# -*- coding: utf-8 -*-
"""US / UK / AU / CA の「eBay の閲覧に効きそうな地元の出来事」(毎朝のメール用・2026-10-16)。

ユーザー「アメリカでは祝日とか給料日とか〇〇祭とかスーパーボールがあると、eBay の閲覧に影響しそうな地場情報。UK や AU、CA もあれば」
「だから、出品数をいつもより多くしてもいいかもとかさ」

- 祝日は holidays ライブラリ (国の祝日の表)。買い物の行事・給料日はここの決まりで出す
- ★閲覧に効くかは一般に言われていることで、うちの数字では測っていない (メールにもそう書く)
"""
from __future__ import annotations

import datetime as dt

# 国の祝日 (holidays の国コード, 地域)
_HOLIDAY_COUNTRIES = {"US": ("US", None), "UK": ("GB", None), "AU": ("AU", "NSW"), "CA": ("CA", "ON")}


def _nth_weekday(y, m, weekday, n):
    """y年m月の n 番目の weekday (0=月)。n=-1 は最後。純関数。"""
    if n > 0:
        d = dt.date(y, m, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _last_workday(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def shopping_events(y):
    """[(日付, 国, 名前, 何が起きるか)] — 買い物の行事 (純関数)。"""
    thanks = _nth_weekday(y, 11, 3, 4)                      # 11月 第4木曜
    out = [
        (dt.date(y, 2, 27), "ALL", "ポケモンデー", "ポケモンの新商品・話題が出やすい"),
        (_nth_weekday(y, 2, 6, 2), "US", "スーパーボウル", "当日の夕方〜夜は見る人が減り、前後の週末に買い物が増えやすい"),
        (_nth_weekday(y, 5, 6, 2), "US", "母の日", ""),
        (_nth_weekday(y, 6, 6, 3), "US", "父の日", ""),
        (dt.date(y, 10, 31), "US", "ハロウィン", ""),
        (thanks, "US", "感謝祭", "当日は閲覧が減り、翌日から買い物が増える"),
        (thanks + dt.timedelta(days=1), "ALL", "ブラックフライデー", "年で一番買い物が多い週末の始まり"),
        (thanks + dt.timedelta(days=4), "ALL", "サイバーマンデー", "ネットの買い物が多い日"),
        (dt.date(y, 12, 15), "US", "クリスマスに間に合う発送の締め切りが近い", "海外発送は早めに買われる"),
        (dt.date(y, 12, 26), "UK", "ボクシングデー", "年末のセールで閲覧が増える"),
        (dt.date(y, 12, 26), "AU", "ボクシングデー", "年末のセールで閲覧が増える"),
        (dt.date(y, 12, 26), "CA", "ボクシングデー", "年末のセールで閲覧が増える"),
        (_nth_weekday(y, 11, 1, 2), "AU", "クリックフレンジー (豪州のネットセールの頃)", "日付は年により前後する"),
    ]
    return out


def paydays(y, m):
    """[(日付, 国, 名前, 説明)] — よくある給料日 (純関数)。会社によって違うので「多い日」として出す。"""
    out = [(dt.date(y, m, 15), "US", "給料日が多い日 (15日)", ""),
           (_last_workday(y, m), "US", "給料日が多い日 (月末)", ""),
           (_last_workday(y, m), "UK", "給料日が多い日 (月末の平日)", ""),
           (_last_workday(y, m), "CA", "給料日が多い日 (月末)", "")]
    return out


def upcoming(today, days=7):
    """today から days 日の出来事 [{date, country, name, note}] を日付順に (I/O は祝日の表だけ)。"""
    end = today + dt.timedelta(days=days - 1)
    rows = []
    try:
        import holidays
        for c, (code, sub) in _HOLIDAY_COUNTRIES.items():
            for d, name in holidays.country_holidays(code, subdiv=sub, years=[today.year, end.year]).items():
                if today <= d <= end:
                    rows.append((d, c, f"祝日: {name}", "休みの日は閲覧が増えやすい"))
    except Exception:                                          # noqa: BLE001 表が無ければ祝日は出さない
        pass
    for y in {today.year, end.year}:
        rows += [r for r in shopping_events(y) if today <= r[0] <= end]
    for y, m in {(today.year, today.month), (end.year, end.month)}:
        rows += [r for r in paydays(y, m) if today <= r[0] <= end]
    seen, out = set(), []
    shop = {(d, c) for d, c, n, _ in rows if not n.startswith("祝日")}
    for d, c, n, note in sorted(rows):
        if (d, c, n) in seen or (n.startswith("祝日") and (d, c) in shop):   # 感謝祭など行事と祝日が重なれば行事だけ
            continue
        seen.add((d, c, n))
        out.append({"date": d.isoformat(), "country": c, "name": n, "note": note})
    return out


# ── 各マーケットの事情 (2026-10-16 ユーザー「各マーケット事情を教えて欲しい。当店の過去の実績なんていらない」) ──
# ★ここに書くのは一般に言われていること (eBay や各国の買い物の傾向)。うちの数字では測っていない
MARKETS = {
    "US": {"tz": "America/New_York", "label": "US (東部)",
           "notes": ["週末と平日の夜に閲覧が増え、日曜の夜が一番多いと言われる", "給料日は15日・月末、隔週金曜の会社も多い",
                     "感謝祭からサイバーマンデーが年で一番の買い物の時期"]},
    "UK": {"tz": "Europe/London", "label": "UK",
           "notes": ["日曜の夜が一番見られると言われる", "給料日は月末の平日が多い (月末の週末は財布が緩む)",
                     "ボクシングデー (12/26) からの年末セール"]},
    "AU": {"tz": "Australia/Sydney", "label": "AU (シドニー)",
           "notes": ["季節が逆 (10〜11月は春)", "給料日は隔週の木曜が多いと言われる", "11月のクリックフレンジー・ブラックフライデーでネットの買い物が増える"]},
    "CA": {"tz": "America/Toronto", "label": "CA (トロント)",
           "notes": ["週末と夜に閲覧が増える (US とほぼ同じ)", "給料日は隔週金曜・月末が多い", "ボクシングデー (12/26) のセール"]},
}
_FALLBACK_OFFSET = {"America/New_York": -4, "Europe/London": 1, "Australia/Sydney": 11, "America/Toronto": -4}
LISTING_HOUR_JST = 19          # 夕方の出品が公開される頃 (日本時間)


def market_context(today, hour_jst=LISTING_HOUR_JST):
    """今夜 (today の hour_jst 時) に出した出品が、各マーケットで何曜日の何時に並ぶか + その国の今後2日の出来事 + 一般的な事情。"""
    jst = dt.timezone(dt.timedelta(hours=9))
    t = dt.datetime.combine(today, dt.time(hour_jst), jst)
    ev = upcoming(today, 3)
    out = {}
    for k, m in MARKETS.items():
        try:
            from zoneinfo import ZoneInfo
            lt = t.astimezone(ZoneInfo(m["tz"]))
        except Exception:                                      # noqa: BLE001 時差の表が無い時は夏時間の差で
            lt = t.astimezone(dt.timezone(dt.timedelta(hours=_FALLBACK_OFFSET[m["tz"]])))
        wd = "月火水木金土日"[lt.weekday()]
        out[k] = {"market": m["label"], "listed_at_local": f"{lt:%m/%d} ({wd}) {lt:%H:%M}",
                  "weekend_soon": lt.weekday() >= 4,
                  "events_next_2_days": [e for e in ev if e["country"] in (k, "ALL")],
                  "general_notes": m["notes"]}
    return out
