#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""メルカリ・Shops で買った物を、購入メール (Gmail) から読む (2026-10-11)。注文 → 仕入れ の管理が使う。

★ユーザー (2026-10-11):「メルカリもメールで取るに修正したら」→「うん」。
  それまでは Edge の拡張で購入履歴の画面を読み、30分は控えを使い回していた。
  控えが 17:57、買ったのが 18:03 で、数え直しても買う前の控えを見て「仕入れ待ち」のままだった。
  スニダン (snkrdunk_purchases) と同じく Gmail を IMAP で読む (アプリ パスワード・読むだけ)。

メールの形 (2026-10-11 実物で確認):
  メルカリ: 件名「【メルカリ】ご購入ありがとうございます」/ 本文「商品ID : m47602546310」「商品名 : …」「支払い金額 : ￥4,800」
  Shops   : 件名「【店名】ご購入ありがとうございます」/ 本文「注文番号 : order_2JV…」「商品名 : …」「注文金額合計 ： ¥5,600」

返す形は mercari_purchases の購入履歴と同じ (id / url / title / at / shops / order_id) に
price (支払い金額) と no (カード番号) を足したもの。

    python mercari_mail_purchases.py      # 直近60日の購入を出すだけ
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime

import snkrdunk_purchases as SN

SENDERS = ("no-reply@mercari.jp", "no-reply@mercari-shops.com")
SUBJECT_MARK = "ご購入ありがとうございます"
JST = dt.timezone(dt.timedelta(hours=9))


def _norm_title(t):
    """Shops の商品名を比べる形 (mercari_purchases.norm_title と同じ: 空白・全角空白・タブを抜く)。"""
    return re.sub(r"[\s　]+", "", t or "")


def card_no(title):
    """商品名からカード番号 (075/071・OP01-120 等) を取る (純関数)。取れなければ ""。"""
    t = (title or "").upper().replace("／", "/")
    m = re.search(r"(?<![0-9])(\d{3}/\d{2,3})(?![0-9])", t)
    if m:
        return m.group(1)
    m = re.search(r"(?<![A-Z0-9])((?:[A-Z]{1,3}\d{1,2}[A-Z]?|P)-\d{3})(?![0-9])", t)   # OP01-120 / FB10-040 / P-043
    return m.group(1) if m else ""


def is_psa10(title):
    """商品名が PSA10 か (純関数)。PSA7 等をはっきり書いた物は False (2026-10-09 PSA7 を買った実例)。"""
    t = (title or "").upper().replace("Ｐ", "P").replace("Ｓ", "S").replace("Ａ", "A").replace("１", "1").replace("０", "0")
    if re.search(r"PSA\s*[1-9](?!0)", t):
        return False
    return bool(re.search(r"PSA\s*10", t))


def parse_mail(subject, body, sent_at, sender):
    """購入メール → 購入 (純関数)。購入メールでなければ None。"""
    if SUBJECT_MARK not in (subject or "") or "発送" in (subject or ""):
        return None
    body = body or ""
    name = re.search(r"商品名\s*[:：]\s*(.+)", body)
    title = name.group(1).strip() if name else ""
    if "mercari-shops" in (sender or ""):
        o = re.search(r"注文番号\s*[:：]\s*order_([A-Za-z0-9]+)", body)
        if not o:
            return None
        p = re.search(r"注文金額合計\s*[:：]\s*[¥￥]\s*([\d,]+)", body) or re.search(r"商品価格\s*[:：]\s*[¥￥]\s*([\d,]+)", body)
        return {"id": "name:" + _norm_title(title), "url": f"https://mercari-shops.com/orders/{o.group(1)}",
                "title": title, "at": sent_at, "shops": True, "order_id": o.group(1),
                "price": int(p.group(1).replace(",", "")) if p else None, "no": card_no(title)}
    m = re.search(r"商品ID\s*[:：]\s*(m\d+)", body)
    if not m:
        return None
    p = re.search(r"支払い金額\s*[:：]\s*[¥￥]\s*([\d,]+)", body)
    return {"id": m.group(1), "url": f"https://jp.mercari.com/transaction/{m.group(1)}",
            "title": title, "at": sent_at, "shops": False,
            "price": int(p.group(1).replace(",", "")) if p else None, "no": card_no(title)}


def fetch_purchases(days=60):
    """直近 days 日の購入メール (I/O)。新しい順ではなく届いた順。読めなければ例外。"""
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(SN.USER, SN._password())
        imap.select("INBOX", readonly=True)
        out = []
        for sender in SENDERS:
            _t, data = imap.search(None, '(FROM "%s" SINCE "%s")' % (sender, since))
            for i in data[0].split():
                _t, h = imap.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
                subj = "".join(x.decode(c or "utf-8", "replace") if isinstance(x, bytes) else x
                               for x, c in decode_header(email.message_from_bytes(h[0][1]).get("Subject") or ""))
                if SUBJECT_MARK not in subj:
                    continue
                _t, d = imap.fetch(i, "(BODY.PEEK[])")
                msg = email.message_from_bytes(d[0][1])
                at = parsedate_to_datetime(msg["Date"]).astimezone(JST).replace(tzinfo=None)
                p = parse_mail(subj, SN._text(msg), at, sender)
                if p:
                    out.append(p)
        return sorted(out, key=lambda p: p["at"])
    finally:
        try:
            imap.logout()
        except Exception:                                      # noqa: BLE001
            pass


def match_by_no(orders, purchases):
    """仕入元・補URL で結べなかった注文を、カード番号で結ぶ (純関数)。{行番号: 購入}。

    orders: [(行番号, 注文日 date, 注文タイトル)]。注文日より前の購入は結ばない。
    ★「仕入れてないのに仕入済」が一番きつい (2026-09-25) ので、PSA 10 の注文には PSA10 と書いた購入だけ
      (2026-10-09 にシャワーズの PSA7 を買ってしまった実例がある)。古い注文から、いちばん早い購入を当てる。
    """
    used, out = set(), {}
    buys = [p for p in purchases if p.get("at") and p.get("no")]
    for row, day, title in sorted(orders, key=lambda o: (o[1], o[0])):
        psa = bool(re.search(r"PSA\s*10", (title or "").upper()))
        for p in buys:
            k = (p["id"], p.get("order_id"))
            if k in used or p["at"].date() < day or (psa and not is_psa10(p["title"])):
                continue
            if SN.title_has_no(title, p["no"]):
                out[row] = p
                used.add(k)
                break
    return out


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    for p in fetch_purchases():
        print(p["at"], "Shops" if p["shops"] else "メルカリ", p["id"][:20], p["no"], p["price"], p["title"][:40])
