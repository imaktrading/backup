#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スニダンで買った物を、購入メール (Gmail) から読む (2026-10-09)。注文 → 仕入れ の管理 (order_purchase_sync.py) が使う。

★ユーザー (2026-10-09): スニダンの購入履歴はスマホのアプリにしか無い →「メール来ているね」。
  「【SNKRDUNK】ご購入ありがとうございます。(取引ID：…)」に カード名と番号・支払い金額 (送料込み) が載っている。
  Gmail は IMAP + アプリ パスワード (iMak_data/credentials/gmail_app_password.txt・読むだけ) で読む。

注文との結び方: メールのカードの番号 (例 044/171・OP01-120) が注文のタイトルにあり、注文日以降に買った物。
仕入原価は「支払い金額 (税込)」(商品 + 送料 + 手数料)。

    python snkrdunk_purchases.py          # 直近60日の購入を出すだけ
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime

USER = "imax2303@gmail.com"
PASS_FILE = r"C:/dev/iMak_data/credentials/gmail_app_password.txt"
SENDER = "no-reply@snkrdunk.com"
SUBJECT_MARK = "ご購入ありがとうございます"
JST = dt.timezone(dt.timedelta(hours=9))


def _password(path=PASS_FILE):
    """ファイルの中の16文字の行 (空白は抜く)。ユーザーは空白あり・無しの2行で置いた (2026-10-09)。"""
    with open(path, encoding="utf-8-sig") as f:
        for line in f.read().splitlines():
            p = line.replace(" ", "").strip()
            if len(p) == 16:
                return p
    raise RuntimeError("Gmail のアプリ パスワードが読めません (%s に16文字の行が無い)" % path)


def _text(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            h = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            return re.sub(r"<[^>]+>", "\n", h)
    return ""


def parse_mail(subject, body, sent_at):
    """購入メール → {"id","title","no","price","at"} (純関数)。購入メールでなければ None。"""
    if SUBJECT_MARK not in (subject or ""):
        return None
    m = re.search(r"取引ID[：:]\s*(\d+)", subject)
    tid = m.group(1) if m else ""
    t = re.search(r"■\s*商品情報\s*\n\s*・(.+)", body or "")
    title = t.group(1).strip() if t else ""
    no = ""
    b = re.search(r"\[([^\]]+)\]", title)
    if b:
        tok = b.group(1).split()
        no = tok[-1] if tok else ""
    p = re.search(r"支払い金額[^：:]*[：:]\s*[¥￥]\s*([\d,]+)", body or "")
    price = int(p.group(1).replace(",", "")) if p else None
    return {"id": tid, "title": title, "no": no, "price": price, "at": sent_at}


def title_has_no(order_title, no):
    """注文のタイトルにカードの番号があるか (純関数)。044/171 は #044/171、OP01-120 はそのまま。"""
    if not no:
        return False
    t = (order_title or "").upper()
    n = no.upper()
    return bool(re.search(r"(?<![0-9A-Z])#?" + re.escape(n) + r"(?![0-9])", t))


def fetch_purchases(days=60):
    """直近 days 日の購入メール (I/O)。読めなければ例外。"""
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(USER, _password())
        imap.select("INBOX", readonly=True)
        _t, data = imap.search(None, '(FROM "%s" SINCE "%s")' % (SENDER, since))
        out = []
        for i in data[0].split():
            _t, d = imap.fetch(i, "(RFC822)")
            msg = email.message_from_bytes(d[0][1])
            subj = "".join(x.decode(c or "utf-8", "replace") if isinstance(x, bytes) else x
                           for x, c in decode_header(msg.get("Subject") or ""))
            if SUBJECT_MARK not in subj:
                continue
            at = parsedate_to_datetime(msg["Date"]).astimezone(JST).replace(tzinfo=None)
            p = parse_mail(subj, _text(msg), at)
            if p:
                out.append(p)
        return out
    finally:
        try:
            imap.logout()
        except Exception:                                      # noqa: BLE001
            pass


def match(orders, purchases):
    """注文 [(行番号, 注文日 date, 注文タイトル)] と購入を結ぶ (純関数)。{行番号: 購入}。

    1つの購入は1つの注文にだけ。注文日より前の購入は結ばない。古い注文から、いちばん早い購入を当てる。
    """
    used, out = set(), {}
    buys = sorted((p for p in purchases if p.get("at")), key=lambda p: p["at"])
    for row, day, title in sorted(orders, key=lambda o: (o[1], o[0])):
        for p in buys:
            if p["id"] not in used and p["at"].date() >= day and title_has_no(title, p["no"]):
                out[row] = p
                used.add(p["id"])
                break
    return out


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    for p in fetch_purchases():
        print(p["at"], p["id"], p["no"], p["price"], p["title"][:50])
