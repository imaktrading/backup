#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eBay のメール (新しいオファー / 支払いがありました) を合図に、判断材料を付けてスマホに知らせる (2026-10-13)。

★ユーザー (2026-10-13):「オファーがもっと増えて、安い仕入元を探したり、仕入れたりの管理が怖い」
  →「神風頼みでいいのかどうか」(家の PC が落ちると神風も止まる) →「メールの方が早いし、PC 落ちるとか関係なくなるのでは？」
  →「その組み合わせが一番いい」= **合図はメール・中身は API**。KAGOYA で数分おきに動かす。

  - 📩 新しいオファー → そのオファーを eBay から取り (offer_calc.fetch_offers)、この額の利益・仕入値・補URLの本数・期限を付けて通知
  - 💰 支払いがありました (= 売れた) → 商品管理シートの仕入元・補URLの本数・仕入値を付けて通知 (すぐ仕入れる合図)
  判断は人がする (通知を押すと Seller Hub のそのページが開く)。メールを読むだけで、eBay にもシートにも書かない。

    python ebay_mail_alert.py            # 1回見る (予約から呼ぶ)
    python ebay_mail_alert.py --dry-run  # 通知を送らず、何を送るかだけ出す (記録もしない)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakeBayAPI"))

STATE = r"C:/dev/iMak_data/hq/ebay_mail_alert_state.json"
NTFY_TOPIC = r"C:/dev/iMak_data/credentials/ntfy_topic.txt"
OFFER_SUBJ = ("新しいオファーがあります", "購入者が新しいオファーを送信しました")
PAID_SUBJ = ("の支払いがありました",)
LOOKBACK_DAYS = 2
SELLERHUB_OFFER = "https://www.ebay.com/bo/seller/showOffers?itemid=%s"


def kind_of(subject):
    """件名 → "offer" / "paid" / "" (純関数)。"""
    s = subject or ""
    if any(k in s for k in OFFER_SUBJ):
        return "offer"
    if any(k in s for k in PAID_SUBJ):
        return "paid"
    return ""


def item_id_from(text):
    """件名・本文から eBay の出品番号 (12桁) を取る (純関数)。無ければ ""。"""
    m = re.search(r"[（(](\d{12})[）)]", text or "") or re.search(r"(?:itm/|item=|itemid=)(\d{12})", text or "", re.I)
    return m.group(1) if m else ""


def offer_line(o, profit, best=None, best_profit=None):
    """オファー1件 → (題, 本文) (純関数)。best = 今買える一番安い (条件OK) 仕入値・best_profit = その値段での利益。"""
    sym = o.get("sym") or "$"
    p = "利益 ¥{:,.0f}".format(profit) if isinstance(profit, (int, float)) else "利益 —(仕入値なし)"
    title = "📩 オファー %s%s → %s" % (sym, o.get("price"), p)
    body = "\n".join([
        (o.get("title") or "")[:60],
        "出品 %s%s / 仕入値 %s / 補URL %s本%s" % (
            sym, o.get("list"), ("¥{:,}".format(int(o["cost"])) if o.get("cost") else "—"), o.get("supply") or 0,
            " / ⚠️在庫0" if o.get("soldout") else ""),
        ("今買える一番安い ¥{:,} → 利益 {}".format(best, ("¥{:,.0f}".format(best_profit)
                                                    if isinstance(best_profit, (int, float)) else "—"))
         if best else "今買える仕入元: 控え無し (神風のオファー画面で探す)"),
        "期限 %s / %s (%s)" % (o.get("expire") or "", o.get("buyer") or "", o.get("country") or ""),
    ])
    return title, body


def paid_line(title, row_info):
    """売れた1件 → (題, 本文) (純関数)。row_info = {"cost", "supply", "url"} か None。"""
    t = "💰 売れた: %s" % (title or "")[:50]
    if not row_info:
        return t, "商品管理シートに行が見つかりません (ミラーかもしれません)。神風の仕入れ待ちで確かめてください"
    return t, "仕入値 %s / 仕入元+補 %s本%s" % (
        ("¥{:,}".format(row_info["cost"]) if row_info.get("cost") else "—"), row_info.get("n_urls") or 0,
        "" if row_info.get("n_urls") else " / 🚨仕入元なし")


# ── I/O ────────────────────────────────────────────────────────────
def read_mails(days=LOOKBACK_DAYS):
    """Gmail の eBay からのメール → [{id, kind, subject, body}] (I/O)。"""
    import email
    import imaplib
    from email.header import decode_header
    import snkrdunk_purchases as SN
    im = imaplib.IMAP4_SSL("imap.gmail.com")
    out = []
    try:
        im.login(SN.USER, SN._password())
        im.select("INBOX", readonly=True)
        _t, d = im.search(None, "X-GM-RAW", f'"from:ebay@ebay.com newer_than:{days}d"')
        for i in d[0].split():
            _t, m = im.fetch(i, "(X-GM-MSGID BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            gid = re.search(rb"X-GM-MSGID (\d+)", m[0][0] or b"")
            h = email.message_from_bytes(m[0][1])
            subj = "".join(x.decode(c or "utf-8", "replace") if isinstance(x, bytes) else x
                           for x, c in decode_header(h.get("Subject") or ""))
            k = kind_of(subj)
            if not k:
                continue
            body = ""
            if k == "paid" or not item_id_from(subj):
                _t, mb = im.fetch(i, "(BODY.PEEK[TEXT])")
                body = (mb[0][1] or b"").decode("utf-8", "replace")[:20000]
            out.append({"id": gid.group(1).decode() if gid else i.decode(), "kind": k, "subject": subj, "body": body})
    finally:
        try:
            im.logout()
        except Exception:                                      # noqa: BLE001
            pass
    return out


def push(title, body, click=""):
    import requests
    topic = open(NTFY_TOPIC, encoding="utf-8").read().strip()
    h = {"Title": title.encode("utf-8"), "Priority": "high"}
    if click:
        h["Click"] = click
    return requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=30, headers=h).ok


def profit_of(o, p, cost=None):
    """オファー1件の、この額で承諾した時の利益 (円)。画面と同じ式 (offer_calc.calc_py)。分からなければ None。"""
    import offer_calc as OC
    cost = cost or o.get("cost")
    if not cost:
        return None
    try:
        tab = p["routes"][o["dest"]][0]
        dk = "US" if (tab.startswith("US") or o["dest"] == "その他 (US出品・米国外へ発送)") else o["dest"]
        return OC.calc_py(p, tab, o["cat"], dk, float(o["price"]), float(cost), 0.0, promo_on=False,
                          listed=float(o.get("list") or 0) or None)
    except Exception:                                          # noqa: BLE001
        return None


def sheet_info(item_id):
    """商品管理シート → {"cost", "n_urls"} (I/O)。無ければ None。"""
    import sheet_io as S
    for r in S._product_ws().get_all_values()[1:]:
        if len(r) > 1 and r[1].strip() == item_id:
            urls = [r[0]] + [r[S.PRODUCT_COL_AUX_START + k] for k in range(S.PRODUCT_AUX_MAX)
                             if len(r) > S.PRODUCT_COL_AUX_START + k]
            d = re.sub(r"[^\d]", "", r[13] if len(r) > 13 else "")
            return {"cost": int(d) if d else None, "n_urls": sum(1 for u in urls if (u or "").startswith("http"))}
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        st = {"seen": []}
    first = not st.get("seen")
    seen = set(st.get("seen") or [])
    mails = read_mails()
    new = [m for m in mails if m["id"] not in seen]
    sent = 0
    if first and not dry:
        # 初回は今あるメールを「見た」にするだけ (過去分をまとめて通知しない)
        print(f"📨 eBay メールの見張り: 初回なので {len(new)}通を見た扱いにしました (通知なし)")
        new = []
    offers = p = None
    failed = []
    for m in new:
        if m["kind"] == "offer":
            if offers is None:
                import offer_calc as OC
                offers, p = OC.fetch_offers(), OC.fetch()
            iid = item_id_from(m["subject"]) or item_id_from(m["body"])
            hit = [o for o in offers if str(o.get("itemId")) == iid] or []
            if not hit:
                title, body, click = "📩 オファー (もう対応待ちに無い)", m["subject"][:120], SELLERHUB_OFFER % iid if iid else ""
            else:
                o = hit[-1]
                best = ((o.get("supplyNow") or {}).get("best_ok"))
                title, body = offer_line(o, profit_of(o, p), best, profit_of(o, p, best) if best else None)
                click = SELLERHUB_OFFER % iid
        else:
            iid = item_id_from(m["body"]) or item_id_from(m["subject"])
            name = re.sub(r"(\.\.\.)?の支払いがありました.*$", "", m["subject"])
            title, body = paid_line(name, sheet_info(iid) if iid else None)
            click = "https://www.ebay.com/sh/ord" if not iid else "https://www.ebay.com/itm/%s" % iid
        print(f"  → {title} | {body.replace(chr(10), ' / ')}")
        ok = False
        if not dry:
            try:
                ok = push(title, body, click)
            except Exception as e:                             # noqa: BLE001
                print(f"  ⚠️ 通知を送れません ({type(e).__name__})")
            if not ok:
                failed.append(m["id"])
                print("  ⚠️ 通知を送れなかった → 次の回にもう一度送る")
        if ok:
            sent += 1
            seen.add(m["id"])
    # ★0件でも必ず出す (動いたかが走行ログで分かるように)
    print(f"📨 eBay メールの見張り: 新しい合図 {len(new)}通 (オファー {sum(1 for m in new if m['kind'] == 'offer')} / "
          f"売れた {sum(1 for m in new if m['kind'] == 'paid')}) / 通知 {sent}件 / 送れず {len(failed)}件" + (" [試しに見ただけ]" if dry else ""))
    if not dry:
        # 送れなかった物は「見た」にしない (次の回に送り直す)。それ以外のメールは見た扱い
        keep = sorted((seen | {m["id"] for m in mails}) - set(failed))[-2000:]
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"seen": keep, "at": dt.datetime.now().isoformat(timespec="seconds")},
                  open(STATE, "w", encoding="utf-8"))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
