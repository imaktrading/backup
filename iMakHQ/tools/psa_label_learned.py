"""目視で人が選び直したカードを、PSA のラベルごとに覚える (2026-09-22)。

★ユーザー「目視で候補が出ない場合、カタログで探して入れたら、次からそのカードが
  これだ！ってわかるんじゃないのか」「まとめてではなくて、都度修正して、次からは
  正しい引き方にしてほしい」。

それまでは選んだ結果を **鑑定番号 (cert) ごと** にしか残していなかった
(verified_certs.json)。同じカードの別の鑑定品が来ると、また候補が出ず、また探させていた。

ここでは **PSA のラベル (カテゴリ / Brand / CardNumber / Subject)** をキーにして覚える。
次に同じラベルが来たら、そのカタログIDを期待値にする (人は画像を見て ✅ を押すだけ)。

安全のため:
- 覚えるのは人が **候補から選び直した (CHOSEN)** 時だけ
- 同じラベルに別のカタログIDが選ばれたら **使わない** (パラレル違い等で決められない)
- 期待値にするだけで、目視は省かない
"""
import json
import os
from datetime import datetime

PATH = r"C:/dev/iMak_data/hq/psa_label_learned.json"


def label_key(category, brand, card_number, subject):
    def n(v):
        return " ".join(str(v or "").upper().split())
    return "|".join((n(category), n(brand), n(card_number), n(subject)))


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(data, path=PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def remember(data, key, product_id, cert="", now=None):
    """選ばれたカタログIDを積む (純関数・data を書き換えて返す)。"""
    if not key or not product_id:
        return data
    e = data.setdefault(key, {"picks": {}})
    p = e["picks"].setdefault(product_id, {"times": 0, "certs": []})
    p["times"] += 1
    if cert and cert not in p["certs"]:
        p["certs"].append(cert)
    p["last_at"] = now or datetime.now().isoformat(timespec="seconds")
    return data


def learned_pid(data, key):
    """1つに決まっている時だけカタログIDを返す。割れていたら None。"""
    picks = ((data or {}).get(key) or {}).get("picks") or {}
    return next(iter(picks)) if len(picks) == 1 else None


def record_chosen(results, targets_by_cert, path=PATH):
    """目視の回答から CHOSEN を覚える。覚えた件数を返す。"""
    data, n = load(path), 0
    for r in results:
        if r.get("choice") != "CHOSEN" or not r.get("selected_pid"):
            continue
        t = targets_by_cert.get(str(r.get("cert"))) or {}
        if not t.get("brand"):
            continue
        key = label_key(t.get("category"), t.get("brand"), t.get("card_number"), t.get("subject"))
        remember(data, key, r["selected_pid"], cert=str(r.get("cert")))
        n += 1
    if n:
        save(data, path)
    return n


def key_for_psa(category, psa):
    """PSA の鑑定データ (Brand / CardNumber / Subject) からキーを作る。無ければ ""。"""
    psa = psa or {}
    if not category or not psa.get("Brand"):
        return ""
    return label_key(category, psa.get("Brand"), psa.get("CardNumber"), psa.get("Subject"))


def record_picks(picks, path=PATH):
    """[(key, product_id, cert)] をまとめて覚える (補URLの確証から)。覚えた件数を返す。"""
    data, n = load(path), 0
    for key, pid, cert in picks:
        if key and pid:
            remember(data, key, pid, cert=str(cert or ""))
            n += 1
    if n:
        save(data, path)
    return n


CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"


def category_of(product_id, db=CATALOG_DB):
    """カタログIDのカテゴリ (KEY にカテゴリが付いていない時に引く)。引けなければ ""。"""
    import sqlite3
    try:
        conn = sqlite3.connect(db)
        try:
            r = conn.execute("SELECT category FROM products WHERE product_id=? LIMIT 1",
                             (product_id,)).fetchone()
        finally:
            conn.close()
        return (r[0] or "") if r else ""
    except sqlite3.Error:
        return ""
