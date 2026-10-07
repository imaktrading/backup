# -*- coding: utf-8 -*-
"""バイヤーとのメッセージを注文ごとに並べ、段階に合った文を用意して送る (神風「メッセージ」タブの裏・2026-10-08)。

ユーザー確定 (2026-10-08):
  - 一覧で注文ごとに 支払い → 発送 → 到着 と問い合わせを管理し、適切な返信を手伝う画面
  - 変えるのは3つだけ: リピーターかどうか / 仕向地と値段に合った関税の一文 / 発送の文に追跡番号
  - 問い合わせは文例を先に出し、合わない時だけ「AI に下書き」を押す (Claude Opus 5.5・押した時だけ課金)
  - 画面から確認を挟んで eBay に送る
きっかけ: 英国 £140 の注文 (18-15195-45996) で、受け取り時の VAT を「関税を払っていない」と返金を求められた。
  支払い後の文で関税を説明していれば防げた。

事実だけを使う (確かめられない事は書かない):
  - 関税の一文 = 注文の「eBay が取った税額」で決める (国ごとの基準額を自前で持たない)。
      米国 → 関税込み (DDP・説明文どおり) / 税額あり → eBay が取り済み / 税額 0 → 受け取り時にかかることがある
  - 到着 = 注文の ActualDeliveryTime (日本郵便の分も eBay が持っている)
  - リピーター = 同じバイヤーの前の注文がある (注文の控え buyer_history.json に貯めて90日より前も覚える)
  - 送ったか = 送信済みフォルダの本文 (定型文の決まり文句) と、この画面から送った控え

使い方:
  python buyer_messages.py collect     # eBay から取って buyer_messages.json を作る (定期で回す)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.join(os.path.dirname(os.path.dirname(HERE)), "iMakeBayAPI")
for _p in (HERE, _API):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA_DIR = r"C:/dev/iMak_data/hq"
SNAPSHOT = os.path.join(DATA_DIR, "buyer_messages.json")
HISTORY = os.path.join(DATA_DIR, "buyer_history.json")
SENT_LOG = os.path.join(DATA_DIR, "buyer_messages_sent.json")
TEMPLATES = os.path.join(DATA_DIR, "message_templates.json")
URL = "https://api.ebay.com/ws/api.dll"
AI_MODEL = "claude-opus-5-5"
DAYS = 30

DEFAULT_TEMPLATES = {
    "paid": (
        "Thank you very much for your purchase!\n"
        "Your item will be carefully shipped from Osaka within the listed processing time.\n"
        "{customs_block}"
        "\nWe start preparing every order as soon as payment clears. If anything is not\n"
        "what you expected, please message us today — once your order is packed and\n"
        "handed over for shipping, it can no longer be changed or cancelled.\n\n"
        "Tracking information will be uploaded immediately after shipping.\n\n"
        "If you have any questions, please feel free to send us a message anytime.\n\n"
        "We're happy to help.\n\n"
        "We hope you enjoy your purchase.\n"
        "Your feedback after receiving your item is very important to us. Thank you very much! 😊\n\n"
        "Thank you.\niMak Trading Japan"),
    "repeat": (
        "Hi,\n\n"
        "Welcome back, and thank you so much for ordering from us again!\n"
        "It means a lot that you chose our small shop in Osaka once more.\n\n"
        "Your item will be carefully shipped from Osaka within the listed processing time, "
        "and tracking information will be uploaded right after shipping.\n"
        "{customs_block}"
        "\nIf there is a Japanese card or item you are looking for, just let us know. "
        "We would be glad to search for it for you.\n\n"
        "Thank you again for your continued support. 😊\n\n"
        "Best regards,\niMak Trading Japan"),
    "shipped": (
        "Your item has been shipped from Osaka, Japan.\n\n"
        "Carrier: {carrier}\nTracking number: {tracking}\n{track_url_line}"
        "\nYou can also check the delivery progress from your purchase history.\n"
        "{customs_block}"
        "\nIf you have any questions during the delivery process, please feel free to contact us anytime.\n"
        "We'll be happy to assist you.\n\n"
        "Thank you again for your purchase, and we hope you'll be satisfied with your item! 😊\n\n"
        "Best regards,\niMak Trading Japan"),
    "arrived": (
        "Hope your package arrived safely and everything looks good.\n"
        "If you have any questions or concerns, feel free to reach out anytime.\n\n"
        "If you're happy with your item, a quick feedback would mean a lot to us — it\n"
        "really helps a small seller like us. 😊\n\n"
        "Thanks again for your purchase!\n\n"
        "Best regards,\niMak Trading Japan"),
    # --- 問い合わせの文例 (直近30日の46件を読んで8種類にまとめた・2026-10-08) ---
    "ask_offer": (
        "Hi, thank you for your interest!\n\n"
        "Our prices are already set as low as we can while keeping every order safely shipped from Japan. "
        "The best way to get a lower price is to use the Make Offer button on the listing — we review every offer.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_thanks": (
        "Thank you so much for your kind message! 😊\n"
        "We're really glad to hear that. Please let us know anytime if there is something you are looking for.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_cancel": (
        "Hi, thank you for letting us know.\n\n"
        "We will take care of the cancellation now. You will receive the refund from eBay automatically.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_customs": (
        "Hi, thank you for your message.\n\n"
        "{customs}\n\n"
        "As stated in our listing, any import taxes or fees that are not collected by eBay at checkout "
        "are paid by the buyer on delivery.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_combine": (
        "Hi, thank you for your interest in more items!\n\n"
        "Each item is shipped separately with its own tracking number, so we are not able to combine shipping. "
        "This keeps every card fully protected and trackable from Japan.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_shipping": (
        "Hi, thank you for your message.\n\n"
        "Your item was shipped from Japan. {tracking_sentence}\n"
        "International parcels sometimes show no updates for a few days while they pass through customs. "
        "We are keeping an eye on it and will help right away if anything looks wrong.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_price": (
        "Hi, thank you for your question.\n\n"
        "We source directly in Japan and keep our costs low, which lets us offer fair prices. "
        "Every card is the PSA-graded card shown in the listing, shipped from Osaka.\n\n"
        "Best regards,\niMak Trading Japan"),
    "ask_stock": (
        "Hi, thank you for your message!\n\n"
        "We don't have that one listed right now, but we check Japanese shops every day. "
        "If you tell us the exact card name or number, we will look for it and let you know.\n\n"
        "Best regards,\niMak Trading Japan"),
}
TEMPLATE_LABELS = {
    "paid": "支払い後", "repeat": "支払い後 (リピーター)", "shipped": "発送", "arrived": "到着",
    "ask_offer": "値下げ交渉", "ask_thanks": "お礼・届いた", "ask_cancel": "キャンセル", "ask_customs": "関税",
    "ask_combine": "まとめ買い・同梱", "ask_shipping": "発送・追跡", "ask_price": "値段への疑問", "ask_stock": "在庫の問い合わせ",
}
# 問い合わせの中身 → 文例 (上から順に当てる。当たらなければ「お礼」でなく空 = 人が選ぶ)
ASK_RULES = [
    ("ask_cancel", r"\bcancel|refund|return it|purchased (this|it) twice|by mistake|accidentally"),
    ("ask_customs", r"custom|duty|duties|\bvat\b|import (fee|tax|charge)|threshold|£135|tax"),
    ("ask_combine", r"combine|combined|bundle|both items|two items|multiple items"),
    ("ask_shipping", r"tracking|track number|shipped|shipping|deliver|arriv|when will|where is|fedex|dhl|not received"),
    ("ask_offer", r"\$\s?\d|£\s?\d|€\s?\d|\b\d{2,4}(\.\d+)?\s*\?|lower|discount|best price|deal|meet at|can you do|how much|offer"),
    ("ask_price", r"low price|so cheap|cheaper than|why.*price|price.*why|reason.*price"),
    ("ask_stock", r"do you have|in stock|available|selling the|have any|looking for|restock"),
    ("ask_thanks", r"thank|received|got it|love it|great|fantastic|appreciat"),
]
# 送信済みの本文から、どの定型文を送ったかを見分ける決まり文句
SENT_MARKERS = {
    "paid": ("Thank you very much for your purchase", "Welcome back, and thank you so much for ordering"),
    "shipped": ("has been shipped from Osaka",),
    "arrived": ("Hope your package arrived safely",),
}
TRACK_URLS = {
    "japan post": "https://trackings.post.japanpost.jp/services/srv/search/direct?reqCodeNo1={n}&locale=en",
    "speedpak": "https://www.orangeconnex.com/tracking?language=en&trackingnumber={n}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={n}",
    "dhl": "https://www.dhl.com/global-en/home/tracking.html?tracking-id={n}",
    "ups": "https://www.ups.com/track?tracknum={n}",
    "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
}
TAX_NAMES = {"GB": "UK VAT", "AU": "Australian GST", "NZ": "NZ GST", "SG": "Singapore GST", "NO": "Norwegian VAT",
             "CH": "Swiss VAT", "CA": "Canadian sales tax"}
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
      "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}


# =========================================================== 純関数
def customs_line(country, tax_amount):
    """関税の一文 (英語)。注文の事実 (仕向地と eBay が取った税額) だけで決める。純関数。"""
    c = (country or "").upper()
    try:
        tax = float(tax_amount or 0)
    except (TypeError, ValueError):
        tax = 0.0
    if c == "US":
        return "All import duties and fees are already included in your payment, so there is nothing extra to pay on delivery."
    if tax > 0:
        name = TAX_NAMES.get(c) or ("EU VAT" if c in EU else "Import tax")
        return f"{name} was already collected by eBay at checkout, so there should be nothing extra to pay on delivery."
    extra = (" (In the UK, eBay collects VAT at checkout only for orders up to £135.)" if c == "GB"
             else " (In the EU, eBay collects VAT at checkout only for orders up to €150.)" if c in EU else "")
    return ("Please note: import taxes or duties were not collected at checkout for this order and may be charged "
            "by the delivery carrier on delivery, as stated in our listing." + extra)


def track_url(carrier, number):
    """運送会社と追跡番号 → 追跡ページの URL。分からなければ ""。純関数。"""
    if not number:
        return ""
    c = (carrier or "").lower()
    for k, u in TRACK_URLS.items():
        if k in c:
            return u.format(n=number)
    if re.fullmatch(r"[A-Z]{2}\d{9}JP", number or ""):
        return TRACK_URLS["japan post"].format(n=number)
    return ""


def classify(text):
    """問い合わせの本文 → 文例のキー。当たらなければ ""。純関数。"""
    t = (text or "").lower()
    for key, pat in ASK_RULES:
        if re.search(pat, t):
            return key
    return ""


def sent_kind(text):
    """送った本文 → どの定型文か ("paid"/"shipped"/"arrived"/"")。純関数。"""
    for k, marks in SENT_MARKERS.items():
        if any(m in (text or "") for m in marks):
            return k
    return ""


def stage_of(o):
    """注文の段階: paid / shipped / arrived / cancelled。純関数。"""
    if o.get("status") == "Cancelled":
        return "cancelled"
    if o.get("delivered"):
        return "arrived"
    if o.get("tracking") or o.get("shipped"):
        return "shipped"
    return "paid"


def is_repeat(buyer, order_id, created, history):
    """同じバイヤーの、この注文より前の注文があるか。純関数。"""
    for oid, ts in ((history or {}).get(buyer) or {}).items():
        if oid != order_id and ts and created and ts < created:
            return True
    return False


def render(key, ctx, templates=None):
    """文例 + 注文の情報 → 送る本文。足りない値は空で埋める (文例が崩れない)。純関数。"""
    tpl = (templates or DEFAULT_TEMPLATES).get(key) or DEFAULT_TEMPLATES.get(key, "")
    customs = ctx.get("customs") or ""
    url = ctx.get("track_url") or ""
    vals = {
        "customs": customs,
        "customs_block": ("\n" + customs + "\n") if customs else "",
        "carrier": ctx.get("carrier") or "",
        "tracking": ctx.get("tracking") or "",
        "track_url_line": (f"Track your parcel: {url}\n" if url else ""),
        "tracking_sentence": (f"Tracking number: {ctx.get('tracking')} ({ctx.get('carrier') or 'carrier'})."
                              + (f" {url}" if url else "")) if ctx.get("tracking") else "",
        "buyer": ctx.get("buyer") or "",
    }
    out = tpl
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v)
    return out


def todo_for(o, sent):
    """この注文で、まだ送っていない定型文のキー (無ければ "")。純関数。

    段階に合う1つだけ。前の段階の文は、もう遅いので出さない (発送後に「支払いありがとう」は送らない)。
    """
    st = o.get("stage")
    if st == "paid" and "paid" not in sent:
        return "repeat" if o.get("repeat") else "paid"
    if st == "shipped" and "shipped" not in sent and o.get("tracking"):
        return "shipped"
    if st == "arrived" and "arrived" not in sent:
        return "arrived"
    return ""


def fix_text(s):
    """eBay の本文の文字化け (UTF-8 を latin-1 で読んだ物: â€™ / Â£) を戻す。戻せなければそのまま。純関数。"""
    if not s or not re.search(r"[ÂâÃ]", s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def body_text(raw_html):
    """メッセージの HTML → 人が書いた文だけ。純関数。"""
    b = html.unescape(html.unescape(raw_html or ""))
    m = re.search(r'id="UserInputtedText"[^>]*>(.*?)</div>', b, re.S)
    t = m.group(1) if m else ""
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return fix_text("\n".join(" ".join(x.split()) for x in t.split("\n")).strip())


# =========================================================== eBay (I/O)
def _post(call, body):
    import requests
    import ebay_getitem_images as EG
    r = requests.post(URL, headers=EG._headers(call), data=body.encode("utf-8"), timeout=90)
    return r.text


def _g(pat, s, default=""):
    m = re.search(pat, s or "", re.S)
    return m.group(1) if m else default


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_orders(days=DAYS):
    now = datetime.now(timezone.utc)
    out, start = [], now - timedelta(days=days)
    while start < now:
        end = min(start + timedelta(days=30), now)
        page = 1
        while True:
            t = _post("GetOrders", (
                '<?xml version="1.0" encoding="utf-8"?><GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                f"<CreateTimeFrom>{_iso(start)}</CreateTimeFrom><CreateTimeTo>{_iso(end)}</CreateTimeTo>"
                "<OrderRole>Seller</OrderRole><OrderStatus>All</OrderStatus><DetailLevel>ReturnAll</DetailLevel>"
                f"<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
                "</GetOrdersRequest>"))
            if "<Ack>Failure</Ack>" in t:
                raise RuntimeError("GetOrders 失敗: " + _g(r"<LongMessage>([^<]*)", t))
            for o in re.findall(r"<Order>(.*?)</Order>", t, re.S):
                sa = _g(r"<ShippingAddress>(.*?)</ShippingAddress>", o)
                out.append({
                    "id": _g(r"<OrderID>([^<]*)", o),
                    "status": _g(r"<OrderStatus>([^<]*)", o),
                    "created": _g(r"<CreatedTime>([^<]*)", o),
                    "paid": _g(r"<PaidTime>([^<]*)", o),
                    "shipped": _g(r"<ShippedTime>([^<]*)", o),
                    "delivered": _g(r"<ActualDeliveryTime>([^<]*)", o),
                    "buyer": _g(r"<BuyerUserID>([^<]*)", o),
                    "country": _g(r"<Country>([^<]*)", sa),
                    "country_name": _g(r"<CountryName>([^<]*)", sa),
                    "currency": _g(r'<Total currencyID="(\w+)"', o),
                    "total": _g(r'<Total currencyID="\w+">([^<]*)', o),
                    "tax": _g(r'<TotalTaxAmount currencyID="\w+">([^<]*)', o, "0"),
                    "item_id": _g(r"<Item>.*?<ItemID>([^<]*)", o),
                    "title": html.unescape(_g(r"<Title>([^<]*)", o)),
                    "carrier": _g(r"<ShippingCarrierUsed>([^<]*)", o),
                    "tracking": _g(r"<ShipmentTrackingNumber>([^<]*)", o),
                })
            if "<HasMoreOrders>true" not in t:
                break
            page += 1
        start = end
    return out


def fetch_messages(days=DAYS, folder=0):
    """受信 (0) / 送信済み (1) のメッセージ。本文 (人が書いた所) 付き。"""
    now = datetime.now(timezone.utc)
    t = _post("GetMyMessages", (
        '<?xml version="1.0" encoding="utf-8"?><GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<DetailLevel>ReturnHeaders</DetailLevel><FolderID>{folder}</FolderID>"
        f"<StartTime>{_iso(now - timedelta(days=days))}</StartTime><EndTime>{_iso(now)}</EndTime>"
        "<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>"
        "</GetMyMessagesRequest>"))
    heads = []
    for m in re.findall(r"<Message>(.*?)</Message>", t, re.S):
        sender = _g(r"<Sender>([^<]*)", m)
        if folder == 0 and sender.lower() in ("ebay", "csfeedback@go.ebay.com"):
            continue
        heads.append({
            "mid": _g(r"<MessageID>([^<]*)", m), "ext": _g(r"<ExternalMessageID>([^<]*)", m),
            "sender": sender, "to": _g(r"<SendToName>([^<]*)", m),
            "item_id": _g(r"<ItemID>([^<]*)", m), "when": _g(r"<ReceiveDate>([^<]*)", m),
            "type": _g(r"<MessageType>([^<]*)", m), "replied": _g(r"<Replied>([^<]*)", m) == "true",
            "subject": html.unescape(_g(r"<Subject>([^<]*)", m)),
        })
    for i in range(0, len(heads), 10):
        chunk = heads[i:i + 10]
        t2 = _post("GetMyMessages", (
            '<?xml version="1.0" encoding="utf-8"?><GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            "<DetailLevel>ReturnMessages</DetailLevel><MessageIDs>"
            + "".join(f"<MessageID>{h['mid']}</MessageID>" for h in chunk) + "</MessageIDs></GetMyMessagesRequest>"))
        bodies = {_g(r"<MessageID>([^<]*)", m): body_text(_g(r"<Text>(.*?)</Text>", m))
                  for m in re.findall(r"<Message>(.*?)</Message>", t2, re.S)}
        for h in chunk:
            h["text"] = bodies.get(h["mid"], "")
    return heads


# =========================================================== 組み立て
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_templates():
    t = _load(TEMPLATES, None)
    if not isinstance(t, dict):
        _save(TEMPLATES, DEFAULT_TEMPLATES)
        return dict(DEFAULT_TEMPLATES)
    return {**DEFAULT_TEMPLATES, **t}


def build(orders, inbox, sent_msgs, history, sent_log, templates):
    """注文と問い合わせ → 画面に出す一覧 (純関数)。"""
    for o in orders:
        if o.get("buyer") and o.get("id"):
            history.setdefault(o["buyer"], {})[o["id"]] = o.get("created", "")
    # 送った定型文 (送信済みフォルダの本文 + この画面の控え) を (相手, 商品) ごとに
    sent_by = {}
    for m in sent_msgs:
        k = sent_kind(m.get("text"))
        if k:
            sent_by.setdefault((m.get("to"), m.get("item_id")), set()).add(k)
    for oid, kinds in (sent_log or {}).items():
        sent_by.setdefault(("#order", oid), set()).update(kinds.keys() if isinstance(kinds, dict) else kinds)
    convs = []
    used_msgs = set()
    for o in sorted(orders, key=lambda x: x.get("created", ""), reverse=True):
        o = dict(o)
        o["stage"] = stage_of(o)
        if o["stage"] == "cancelled":
            continue
        o["repeat"] = is_repeat(o.get("buyer"), o.get("id"), o.get("created"), history)
        o["customs"] = customs_line(o.get("country"), o.get("tax"))
        o["track_url"] = track_url(o.get("carrier"), o.get("tracking"))
        sent = set(sent_by.get((o.get("buyer"), o.get("item_id")), set())) | set(sent_by.get(("#order", o["id"]), set()))
        o["sent"] = sorted(sent)
        thread = [m for m in inbox if m.get("sender") == o.get("buyer")]
        thread += [m for m in sent_msgs if m.get("to") == o.get("buyer")]
        for m in thread:
            used_msgs.add(m["mid"])
        o["thread"] = sorted(({"me": m.get("sender") != o.get("buyer"), "text": m.get("text", ""), "when": m.get("when", ""),
                               "mid": m.get("mid"), "ext": m.get("ext"), "item_id": m.get("item_id"), "replied": m.get("replied")}
                              for m in thread), key=lambda x: x["when"])
        last_in = next((m for m in reversed(o["thread"]) if not m["me"]), None)
        last = o["thread"][-1] if o["thread"] else None
        o["ask"] = classify(last_in["text"]) if (last and not last["me"]) else ""
        o["needs_reply"] = bool(last and not last["me"])
        o["todo"] = todo_for(o, sent)
        o["kind"] = "order"
        convs.append(o)
    # 注文の無い問い合わせ (買う前の質問・値下げ交渉)
    by_sender = {}
    for m in inbox:
        if m["mid"] in used_msgs:
            continue
        by_sender.setdefault((m.get("sender"), m.get("item_id")), []).append(m)
    for (sender, iid), ms in by_sender.items():
        ours = [m for m in sent_msgs if m.get("to") == sender and m.get("item_id") == iid]
        th = sorted(({"me": False, "text": m.get("text", ""), "when": m.get("when", ""), "mid": m["mid"], "ext": m.get("ext"),
                      "item_id": iid, "replied": m.get("replied")} for m in ms), key=lambda x: x["when"])
        th = sorted(th + [{"me": True, "text": m.get("text", ""), "when": m.get("when", ""), "mid": m["mid"]} for m in ours],
                    key=lambda x: x["when"])
        last_in = next((m for m in reversed(th) if not m["me"]), None)
        convs.append({"kind": "ask", "id": f"ask:{sender}:{iid}", "buyer": sender, "item_id": iid,
                      "title": re.sub(r"^.*?sent a message about ", "", ms[-1].get("subject", "")),
                      "thread": th, "stage": "ask", "needs_reply": bool(th and not th[-1]["me"]),
                      "ask": classify(last_in["text"]) if last_in else "", "todo": "", "sent": [],
                      "repeat": bool((history or {}).get(sender)), "created": th[-1]["when"] if th else ""})
    return convs, history


def collect(log=print):
    """eBay から取って一覧を作り直す (I/O)。走行ログに必ず1行出す。"""
    t0 = time.time()
    history = _load(HISTORY, {})
    first = not history
    orders = fetch_orders(90 if first else DAYS)          # 初回は90日ぶん取ってリピーターを覚える
    inbox = fetch_messages(DAYS, 0)
    sent_msgs = fetch_messages(DAYS, 1)
    templates = load_templates()
    convs, history = build(orders, inbox, sent_msgs, history, _load(SENT_LOG, {}), templates)
    if first:
        cut = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
        convs = [c for c in convs if (c.get("created") or "") >= cut]
    _save(HISTORY, history)
    snap = {"at": datetime.now().isoformat(timespec="seconds"), "convs": convs,
            "labels": TEMPLATE_LABELS}
    _save(SNAPSHOT, snap)
    n_todo = sum(1 for c in convs if c.get("todo"))
    n_reply = sum(1 for c in convs if c.get("needs_reply"))
    log(f"📨 メッセージの一覧を作り直した: 注文 {sum(1 for c in convs if c['kind'] == 'order')}件 / "
        f"返事待ち {n_reply}件 / 定型文まだ {n_todo}件 / リピーター {sum(1 for c in convs if c.get('repeat'))}件 "
        f"/ 受信 {len(inbox)}通・送信 {len(sent_msgs)}通 ({time.time() - t0:.0f}秒)")
    return snap


# =========================================================== 下書き (AI・押した時だけ)
def _api_key():
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if k:
        return k
    for f in (r"C:\dev\iMak_data\credentials\api_key.txt", r"C:\dev\iMak\iMak_ichibankuji\API key.txt"):
        if os.path.isfile(f):
            return open(f, encoding="utf-8").read().strip()
    raise RuntimeError("Anthropic の API キーが見つかりません")


def ai_draft(conv, templates=None, log=print):
    """問い合わせへの返事の下書きを Claude Opus 5.5 に書かせる (1回 約3円)。"""
    import anthropic
    templates = templates or load_templates()
    examples = "\n\n".join(f"[{TEMPLATE_LABELS.get(k, k)}]\n{v}" for k, v in templates.items() if k.startswith("ask_"))
    facts = {k: conv.get(k) for k in ("buyer", "title", "country_name", "currency", "total", "tax", "stage",
                                        "carrier", "tracking", "track_url", "customs", "repeat") if conv.get(k) not in (None, "")}
    thread = "\n".join(("[Us] " if m.get("me") else "[Buyer] ") + (m.get("text") or "") for m in conv.get("thread") or [])
    system = (
        "You write eBay buyer replies for iMak Trading Japan, a small shop in Osaka selling PSA-graded Japanese trading cards "
        "and Japanese goods. Write in clear, warm, professional English. Keep it short. Use only the facts given; "
        "never promise refunds, discounts, or anything not in the facts. If the buyer is wrong about a rule, explain it "
        "politely with the facts. End with 'Best regards,\\niMak Trading Japan'. Return only the message text.\n\n"
        "Our example replies (match this tone):\n" + examples)
    client = anthropic.Anthropic(api_key=_api_key())
    r = client.messages.create(
        model=AI_MODEL, max_tokens=4000, output_config={"effort": "low"}, system=system,
        messages=[{"role": "user", "content": "Order facts (JSON):\n" + json.dumps(facts, ensure_ascii=False)
                   + "\n\nConversation so far:\n" + thread + "\n\nWrite our reply to the buyer's last message."}])
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    u = r.usage
    yen = (u.input_tokens * 4 + u.output_tokens * 20) / 1e6 * 158
    log(f"🤖 AI の下書き: {conv.get('buyer')} / 入力 {u.input_tokens}・出力 {u.output_tokens} トークン / 約{yen:.1f}円")
    return {"text": text, "yen": round(yen, 1)}


# =========================================================== 送る (画面で確認した後だけ)
def _x(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(conv, body, kind="", log=print):
    """eBay に送る。注文があれば取引相手へ (AAQToPartner)、買う前の質問には返信 (RTQ)。"""
    body = (body or "").strip()
    if not body:
        return {"ok": False, "error": "本文が空です"}
    if len(body) > 2000:
        return {"ok": False, "error": f"本文が長すぎます ({len(body)}字・eBay の上限は2000字)"}
    if conv.get("kind") == "order":
        call = "AddMemberMessageAAQToPartner"
        xml = ('<?xml version="1.0" encoding="utf-8"?><AddMemberMessageAAQToPartnerRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
               f"<ItemID>{_x(conv['item_id'])}</ItemID><MemberMessage><Body>{_x(body)}</Body>"
               "<QuestionType>General</QuestionType>"
               f"<RecipientID>{_x(conv['buyer'])}</RecipientID><Subject>About your order</Subject></MemberMessage>"
               "</AddMemberMessageAAQToPartnerRequest>")
    else:
        last_in = next((m for m in reversed(conv.get("thread") or []) if not m.get("me") and m.get("ext")), None)
        if not last_in:
            return {"ok": False, "error": "返信先のメッセージが見つかりません"}
        call = "AddMemberMessageRTQ"
        xml = ('<?xml version="1.0" encoding="utf-8"?><AddMemberMessageRTQRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
               f"<ItemID>{_x(conv['item_id'])}</ItemID><MemberMessage><Body>{_x(body)}</Body>"
               f"<ParentMessageID>{_x(last_in['ext'])}</ParentMessageID>"
               f"<RecipientID>{_x(conv['buyer'])}</RecipientID></MemberMessage></AddMemberMessageRTQRequest>")
    t = _post(call, xml)
    ok = _g(r"<Ack>([^<]*)", t) in ("Success", "Warning")
    if ok and conv.get("kind") == "order" and kind in ("paid", "repeat", "shipped", "arrived"):
        mark_sent(conv["id"], "paid" if kind == "repeat" else kind)
    log(f"📤 メッセージを送った: {conv.get('buyer')} / {call} / {'成功' if ok else '失敗'}"
        + ("" if ok else " / " + _g(r"<LongMessage>([^<]*)", t)))
    return {"ok": ok, "error": "" if ok else (_g(r"<LongMessage>([^<]*)", t) or "送れませんでした")}


def mark_sent(order_id, kind):
    """この画面の控えに「送った」を書く (eBay の画面から手で送った時にも使う)。"""
    log = _load(SENT_LOG, {})
    log.setdefault(order_id, {})[kind] = datetime.now().isoformat(timespec="seconds")
    _save(SENT_LOG, log)
    return {"ok": True}


def find(conv_id):
    for c in (_load(SNAPSHOT, {}).get("convs") or []):
        if c.get("id") == conv_id:
            return c
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "collect":
        # 予約 (iMakHQ_BuyerMessages_30m・窓なし) からも動いたと分かるよう、1行をファイルにも残す
        _lp = os.path.join(os.path.dirname(HERE), "review_logs", "buyer_messages.log")

        def _log(line):
            print(line)
            with open(_lp, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M} {line}" + chr(10))
        try:
            collect(log=_log)
        except Exception as e:                                   # noqa: BLE001 失敗も1行残す
            _log(f"⚠️ メッセージの一覧を作り直せなかった: {type(e).__name__}: {e}")
            raise
    else:
        print(__doc__)
