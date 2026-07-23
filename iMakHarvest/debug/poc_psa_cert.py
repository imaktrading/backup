"""POC: snkrdunk PSA10 実画像から Vision で cert 番号読取 → PSA 照合 通過率測定.

feasibility 検証専用 (本実装ではない)。
  1. snkrdunk used items (PSA10/出品中) の画像 URL を ~N 件収集
  2. Claude Vision (Haiku 4.5) に front + 追加 photo を送り cert(8-9桁)+grade を読む
  3. 読めた cert を psacard.com で照合 → grade10 + 実在 を確認
出力: 読取率 / 照合通過率 を集計。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scrapers import snkrdunk_op_catalog as OP
from scrapers import snkrdunk_official as SO
from scrapers.color_vision import MODEL_ID, _get_client

CERT_PROMPT = """この画像は PSA 鑑定済みトレカのスラブ(プラケース)です。
ラベル上部に印字された PSA の認証番号 (Certification Number / Cert #) を読んでください。
PSA cert 番号は通常 8〜9 桁の数字です (ラベル上部、 grade の近く)。

【出力 (JSON 1行のみ)】
{"cert":"<8-9桁数字 or NONE>","grade":"<10 等の数字 or NONE>","label":"<ラベルに見えるカード名 or NONE>"}

ルール:
- cert 番号が鮮明に読み取れる場合のみ数字を返す。 不鮮明/見切れ/確証なし → "NONE"
- 推測で埋めない (誤読は厳禁)。 読めない桁があれば cert="NONE"
- JSON 以外の説明文・記号は出力しない"""

CERT_RE = re.compile(r"\b(\d{8,9})\b")


def collect_images(model_ids, want=10):
    s = OP.create_session()
    out = []
    for mid in model_ids:
        items = OP.fetch_used_items(s, mid)
        for it in items:
            if not SO.is_psa10_on_sale(it):
                continue
            imgs = []
            pp = it.get("primaryPhoto") or {}
            if isinstance(pp, dict) and pp.get("imageUrl"):
                imgs.append(pp["imageUrl"])
            for ph in (it.get("photos") or []):
                u = ph.get("imageUrl") if isinstance(ph, dict) else None
                if u and u not in imgs:
                    imgs.append(u)
            if imgs:
                out.append({"model_id": mid, "instance_id": it["id"], "images": imgs[:4]})
            if len(out) >= want:
                return out
    return out


def read_cert(cli, images):
    content = [{"type": "image", "source": {"type": "url", "url": u}} for u in images]
    content.append({"type": "text", "text": CERT_PROMPT})
    try:
        msg = cli.messages.create(model=MODEL_ID, max_tokens=80, timeout=40,
                                  messages=[{"role": "user", "content": content}])
        text = ""
        for b in (msg.content or []):
            if getattr(b, "text", None):
                text = b.text
                break
        return text.strip()
    except Exception as e:
        return f"ERR:{e!r}"


def parse(text):
    try:
        j = json.loads(text[text.find("{"): text.rfind("}") + 1])
        cert = str(j.get("cert", "")).strip()
        if not CERT_RE.fullmatch(cert):
            cert = ""
        return cert, str(j.get("grade", "")).strip(), str(j.get("label", "")).strip()
    except Exception:
        return "", "", ""


def psa_lookup(cert):
    """psacard.com/cert/<n> を GET。 (status_code, 判定textの断片) を返す."""
    url = f"https://www.psacard.com/cert/{cert}"
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"})
        body = r.text or ""
        hit = ""
        for kw in ("PSA 10", "GEM MT", "GEM-MT", "One Piece", "Grade"):
            if kw.lower() in body.lower():
                hit += kw + ";"
        return r.status_code, len(body), hit
    except Exception as e:
        return None, 0, f"ERR:{e!r}"


def main():
    cli = _get_client()
    if cli is None:
        print("NG: Vision client 取得失敗 (api_key?)")
        return 1
    # ST30-001=793190, ST10-006=315324 等 + op cards から複数 model
    samples = collect_images([793190, 315324, 158327, 793190], want=10)
    print(f"収集: {len(samples)} listing\n")
    read_ok = 0
    psa_ok = 0
    for i, s in enumerate(samples, 1):
        raw = read_cert(cli, s["images"])
        cert, grade, label = parse(raw)
        print(f"[{i}] inst={s['instance_id']} imgs={len(s['images'])}")
        print(f"    vision raw: {raw[:120]}")
        print(f"    parsed: cert={cert!r} grade={grade!r} label={label[:30]!r}")
        if cert:
            read_ok += 1
            code, blen, hit = psa_lookup(cert)
            print(f"    PSA lookup: HTTP={code} bodylen={blen} hits={hit!r}")
            if code == 200 and ("PSA 10" in hit or "GEM" in hit):
                psa_ok += 1
        time.sleep(1.0)
    n = len(samples)
    print(f"\n=== 集計 ===")
    print(f"  Vision cert 読取: {read_ok}/{n}")
    print(f"  PSA 照合 grade10 確認: {psa_ok}/{n} (読取成功 {read_ok} 中 {psa_ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
