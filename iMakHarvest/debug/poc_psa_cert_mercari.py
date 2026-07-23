"""POC-B: Mercari 実出品画像から Vision で PSA cert 読取率を測定.

snkrdunk(鑑定済・正面綺麗)で 9/10 だった read-rate が、 Mercari(seller撮影・品質バラつき)で
どこまで落ちるかを実画像で測る。 画像源 = HIGH スプシの mercari PSA グレード品行 col G (各最大4枚)。
PSA 照合は 429 回避のため throttle して先頭数件のみ確認。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scrapers.color_vision import MODEL_ID, _get_client
from sheet_writer import (
    HIGH_SHEET_ID,
    LISTINGS_GID,
    get_listings_worksheet,
    open_sheet_by_id,
)

CERT_PROMPT = """この画像群は PSA 鑑定済みトレカのスラブ(プラケース)の出品写真です(複数アングル)。
ラベル上部に印字された PSA 認証番号 (Certification Number / Cert #、 通常 8〜9 桁) を読んでください。

【出力 (JSON 1行のみ)】
{"cert":"<8-9桁数字 or NONE>","grade":"<10 等 or NONE>","label":"<カード名 or NONE>"}

ルール:
- cert が鮮明に読み取れる場合のみ数字を返す。 不鮮明/見切れ/裏面のみ/確証なし → "NONE"
- 推測で埋めない (誤読厳禁)。 読めない桁があれば cert="NONE"
- JSON 以外は出力しない"""

CERT_RE = re.compile(r"\b(\d{8,9})\b")


def read_cert(cli, images):
    content = [{"type": "image", "source": {"type": "url", "url": u}} for u in images]
    content.append({"type": "text", "text": CERT_PROMPT})
    try:
        msg = cli.messages.create(model=MODEL_ID, max_tokens=80, timeout=40,
                                  messages=[{"role": "user", "content": content}])
        for b in (msg.content or []):
            if getattr(b, "text", None):
                return b.text.strip()
        return ""
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
    try:
        r = requests.get(f"https://www.psacard.com/cert/{cert}", timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"})
        body = (r.text or "").lower()
        hit = ";".join(k for k in ("PSA 10", "GEM MT", "One Piece", "Grade") if k.lower() in body)
        return r.status_code, len(r.text or ""), hit
    except Exception as e:
        return None, 0, f"ERR:{e!r}"


def collect_mercari_psa_rows(want=12):
    sh = open_sheet_by_id(HIGH_SHEET_ID)
    ws = get_listings_worksheet(sh, LISTINGS_GID)
    out = []
    for r in ws.get_all_values():
        a = r[0] if len(r) > 0 else ""
        c = r[2] if len(r) > 2 else ""
        g = r[6] if len(r) > 6 else ""
        if "mercari" in a.lower() and "PSA" in c.upper() and "http" in g:
            imgs = [u for u in g.split("|") if u.startswith("http")][:4]
            if imgs:
                out.append({"title": c, "images": imgs})
        if len(out) >= want:
            break
    return out


def main():
    cli = _get_client()
    if cli is None:
        print("NG: Vision client 取得失敗")
        return 1
    rows = collect_mercari_psa_rows(12)
    print(f"Mercari PSA 行: {len(rows)}\n")
    read_ok = psa_checked = psa_ok = 0
    for i, s in enumerate(rows, 1):
        raw = read_cert(cli, s["images"])
        cert, grade, label = parse(raw)
        print(f"[{i}] title={s['title'][:34]!r} imgs={len(s['images'])}")
        print(f"    parsed: cert={cert!r} grade={grade!r} label={label[:28]!r}")
        if cert:
            read_ok += 1
            if psa_checked < 4:  # 429 回避で先頭4件だけ照合
                code, blen, hit = psa_lookup(cert)
                psa_checked += 1
                print(f"    PSA: HTTP={code} len={blen} hits={hit!r}")
                if code == 200 and ("PSA 10" in hit or "GEM MT" in hit):
                    psa_ok += 1
                time.sleep(4.0)
        time.sleep(0.5)
    n = len(rows)
    print(f"\n=== 集計 (Mercari) ===")
    print(f"  Vision cert 読取: {read_ok}/{n}")
    print(f"  PSA 照合(先頭{psa_checked}件のみ): grade10確認 {psa_ok}/{psa_checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
