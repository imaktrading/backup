"""psa_cert - PSA 認証番号を psacard.com で引いて カード identity を確定する (fail-closed).

2026-08-17 新設。 メルカリ PSA10 出品を「新規出品候補」として拾うには、
**どのカードか** を確証をもって決める必要がある (グローバル CLAUDE.md の出品正確性原則)。
出品くん (iMakTCG) の入口が cert 番号なので、 Harvest 側は
「画像から読んだ cert が本当にその出品のカードか」 を保証して渡す責務を持つ。

2026-06-24 に本件を保留した理由は「読んだ cert の正しさを安く検証できない
(psacard.com が即 429)」 だったが、 2026-08-17 実測で **生 HTTP で 200 / 404 が普通に返る**
ことを確認したため再開 (POC: cert 153420191 → 200 + 全項目、 存在しない cert → 404)。
429 は起こりうる前提で throttle + retry し、 取れなければ **reject** (推測で通さない)。

検証ゲート (すべて満たした時だけ keep):
  ① cert が 8-9 桁で、 psacard.com が **200** を返す (404 = 誤読 → reject)
  ② Item Grade が GEM MT 10 (= PSA10 以外は対象外)
  ③ Vision がスラブラベルから読んだ文字列と PSA 公式の項目が **2 系統以上一致**
     (1 桁誤読すると「実在する別のカード」に当たるため、 ①②だけでは捕まらない。
      ラベル由来の romaji 同士を突合するので 和文タイトルとの言語差の影響を受けない)
"""
from __future__ import annotations

import html as _html
import re
import time
from typing import Optional

import requests

CERT_URL = "https://www.psacard.com/cert/{cert}"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# PSA cert は 8-9 桁 (POC 実測)。 桁数外は Vision 誤読として弾く
CERT_RE = re.compile(r"^\d{8,9}$")

# PSA10 のみ対象 (グレード表記は "GEM MT 10")
GRADE_PSA10 = "GEM MT 10"

# cert ページの項目テーブル (Cert Number / Item Grade / Year / Brand/Title / Subject / ...)
_FIELD_KEYS = {
    "Cert Number": "cert",
    "Item Grade": "grade",
    "Year": "year",
    "Brand/Title": "brand",
    "Subject": "subject",
    "Card Number": "card_number",
    "Category": "category",
    "Variety/Pedigree": "variety",
}

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style).*?</\1>", re.S | re.I)


def _flatten(page_html: str) -> list[str]:
    """HTML を `|` 区切りのテキスト片リストに潰す (= DOM 構造に依存しない項目抽出用)."""
    t = _SCRIPT_RE.sub(" ", page_html or "")
    t = _TAG_RE.sub("|", t)
    t = _html.unescape(t)
    return [p.strip() for p in t.split("|") if p.strip()]


def parse_cert_html(page_html: str) -> dict:
    """cert ページ HTML から項目を抽出 (純関数 = テスト対象).

    項目テーブルは `<dt>Subject</dt><dd>PERONA</dd>` 相当の「ラベル → 値」 並びなので、
    flatten 後に「ラベル片の次の片」を値として拾う。 見つからない項目は入れない
    (= 呼出側で欠落 = reject 判定できるよう、 空文字で埋めない)。
    """
    parts = _flatten(page_html)
    out: dict = {}
    for i, p in enumerate(parts[:-1]):
        key = _FIELD_KEYS.get(p)
        if key and key not in out:
            val = parts[i + 1]
            # 値の位置に別のラベルが来ていたら未取得扱い (テーブル崩れ時の誤取込防止)
            if val not in _FIELD_KEYS:
                out[key] = val
    return out


def fetch_cert(cert: str, timeout: int = 20, retries: int = 2,
               sleep_sec: float = 3.0) -> dict:
    """cert を psacard.com で引く.

    Returns:
        {"status": int|None, "exists": bool, "info": dict, "error": str|None}
        - exists=True は **200 かつ項目が取れた** 時だけ。 429/5xx/例外は exists=False
          (= 「確認できなかった」 であり 「正しい」 ではない → 呼出側は reject する)
    """
    if not CERT_RE.match(cert or ""):
        return {"status": None, "exists": False, "info": {}, "error": "bad_cert_format"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(CERT_URL.format(cert=cert), headers={"User-Agent": _UA},
                             timeout=timeout)
        except Exception as e:  # noqa: BLE001 - network 例外は種類を問わず retry 対象
            last_err = f"{e!r}"
            time.sleep(sleep_sec)
            continue

        if r.status_code == 404:
            return {"status": 404, "exists": False, "info": {}, "error": None}
        if r.status_code == 200:
            info = parse_cert_html(r.text)
            if not info.get("cert"):
                return {"status": 200, "exists": False, "info": info,
                        "error": "parse_failed"}
            return {"status": 200, "exists": True, "info": info, "error": None}

        # 429 / 5xx = 一時障害。 retry して駄目なら「確認できなかった」で返す
        last_err = f"http_{r.status_code}"
        if attempt < retries:
            time.sleep(sleep_sec * (attempt + 2))

    return {"status": None, "exists": False, "info": {}, "error": last_err}


# --- Vision 読取 × PSA 公式 の突合 ------------------------------------------------

_NORM_RE = re.compile(r"[^A-Z0-9]+")
# ラベルに頻出で識別力の無い語 (一致判定から除く)
_STOPWORDS = {
    "THE", "AND", "CARD", "CARDS", "GAME", "JAPANESE", "JAPAN", "JPN", "JP",
    "TCG", "PROMO", "PROMOTION", "PACK", "SET", "EDITION", "ART", "ALT",
    "RARE", "SUPER", "PR", "CP", "NO",
}
# ★ゲーム(フランチャイズ)名。 同じゲーム内で探している以上、 ここが一致しても
# 「同じカード」 の根拠にならない。 2026-08-17: これを数えていたため
# 「Monkey D. Luffy」 と 「Portgas D. Ace」 が brand 一致してしまった。
_FRANCHISE_WORDS = {
    "ONE", "PIECE", "POKEMON", "DRAGON", "BALL", "GUNDAM", "DIGIMON",
    "YUGIOH", "YUGI", "WEISS", "SCHWARZ",
}


def _tokens(s: str) -> set[str]:
    """比較用トークン。 1 文字の語と 定型語・ゲーム名は落とす.

    1 文字を残すと "Monkey **D.** Luffy" と "Portgas **D.** Ace" が
    カード名一致になる (2026-08-17 にテストで検出)。 識別力が無いので除く。
    """
    return {w for w in _NORM_RE.sub(" ", (s or "").upper()).split()
            if len(w) > 1 and w not in _STOPWORDS and w not in _FRANCHISE_WORDS}


def _norm_num(s: str) -> str:
    """カード番号を比較用に正規化 ("#077" / "077" / "77" → "77")."""
    d = re.sub(r"\D", "", s or "")
    return d.lstrip("0") or ("0" if d else "")


def match_signals(vision: dict, info: dict) -> dict:
    """Vision がラベルから読んだ内容 と PSA 公式項目 の一致系統を数える (純関数).

    どちらもスラブ **ラベル由来の同じ文字列** なので、 cert を 1 桁誤読して別カードに
    当たった場合はここで外れる。 出品タイトル (和文) との突合ではないので言語差の影響なし。

    Returns: {"signals": [str], "count": int, "detail": {...}}
    """
    signals, detail = [], {}

    # ① カード名 (Vision label ↔ PSA Subject): token が 1 語でも重なれば一致
    v_tok = _tokens(vision.get("label") or "")
    s_tok = _tokens(info.get("subject") or "")
    detail["label_tokens"] = sorted(v_tok)
    detail["subject_tokens"] = sorted(s_tok)
    if v_tok and s_tok and (v_tok & s_tok):
        signals.append("subject")

    # ② 弾/セット名 (Vision label ↔ PSA Brand/Title): 2 語以上重なった時のみ
    #    (1 語だと "ONE"/"PIECE" 等で誰でも当たるため識別力が無い)
    b_tok = _tokens(info.get("brand") or "")
    if v_tok and b_tok and len(v_tok & b_tok) >= 2:
        signals.append("brand")

    # ③ カード番号
    v_num = _norm_num(vision.get("card_number") or "")
    p_num = _norm_num(info.get("card_number") or "")
    if v_num and p_num and v_num == p_num:
        signals.append("card_number")

    # ④ 発行年
    v_y = re.sub(r"\D", "", vision.get("year") or "")
    p_y = re.sub(r"\D", "", info.get("year") or "")
    if v_y and p_y and v_y == p_y:
        signals.append("year")

    return {"signals": signals, "count": len(signals), "detail": detail}


# --- ネット不要の事前ゲート -------------------------------------------------------
# psacard.com は IP 単位のレート制限が厳しく (2026-08-17 実測: 数発で 429、 復帰は分単位)、
# 公式 API も 2026 年半ばに無料枠がほぼ廃止された。 → **cert 1 件あたりの公式照会は 1 回だけ**
# に抑えたい。 そこで通信の要らない照合で先に落とせるものは落としておく。
#
# 使える無料の裏付け信号: メルカリ出品者は タイトルに cert 末尾 4 桁を入れる慣習がある
# (2026-06-24 POC で全件一致)。 Vision が読んだ cert と突き合わせれば、 通信ゼロで
# 誤読をかなり落とせる。 ただし **入っていない出品も普通にある** ので、
# 「入っていて食い違う」 時だけ reject する (無い = 判定材料が無いだけ、 で通す)。
_DIGITS_RE = re.compile(r"\d{4,}")


def title_cert_conflict(cert: str, title: str) -> bool:
    """タイトル中の数字列が cert 末尾 4 桁と食い違うか (True = 誤読の疑い).

    タイトルに 4 桁以上の数字が 1 つも無ければ False (= 判定材料なし、 conflict ではない)。
    どれか 1 つでも cert の末尾 4 桁と一致すれば False (= 裏付け取れた)。
    """
    if not cert or len(cert) < 4:
        return False
    nums = _DIGITS_RE.findall(title or "")
    if not nums:
        return False
    tail = cert[-4:]
    return not any(tail in n for n in nums)


def local_gate(vision: dict, title: str = "") -> dict:
    """通信せずに判定できる範囲で候補を絞る.

    Returns: {"ok": bool, "reason": str}
      ok=True は 「公式照会に出す価値がある」 という意味であって 「カード確定」 ではない。
      確定は verify() (= PSA 公式照会) を通ってから。
    """
    cert = (vision.get("cert") or "").strip()
    if not CERT_RE.match(cert):
        return {"ok": False, "reason": "cert_unreadable"}
    grade = (vision.get("grade") or "").upper()
    # ラベルのグレードが読めていて PSA10 以外なら、 照会するまでもなく対象外
    if grade and grade != GRADE_PSA10 and "10" not in grade:
        return {"ok": False, "reason": f"grade_not_psa10:{vision.get('grade')}"}
    if title_cert_conflict(cert, title):
        return {"ok": False, "reason": "title_cert_conflict"}
    return {"ok": True, "reason": "local_ok"}


def verify(vision: dict, min_signals: int = 2, **fetch_kwargs) -> dict:
    """Vision 読取結果を PSA 公式で検証する (= 本モジュールの入口).

    Args:
        vision: {"cert","grade","label","card_number","year"} (未読項目は空文字)
        min_signals: ラベル一致に要求する系統数 (既定 2 = 多信号一致ゲート)

    Returns:
        {"ok": bool, "reason": str, "cert": str, "info": dict, "match": dict}
        ok=True の時だけ 出品候補として下流に渡してよい。
    """
    cert = (vision.get("cert") or "").strip()
    if not CERT_RE.match(cert):
        return {"ok": False, "reason": "cert_unreadable", "cert": cert,
                "info": {}, "match": {}}

    res = fetch_cert(cert, **fetch_kwargs)
    if not res["exists"]:
        reason = "cert_not_found" if res["status"] == 404 else "psa_unreachable"
        return {"ok": False, "reason": reason, "cert": cert,
                "info": res["info"], "match": {}}

    info = res["info"]
    if (info.get("grade") or "").upper() != GRADE_PSA10:
        return {"ok": False, "reason": f"grade_not_psa10:{info.get('grade')}",
                "cert": cert, "info": info, "match": {}}

    m = match_signals(vision, info)
    if m["count"] < min_signals:
        return {"ok": False, "reason": f"label_mismatch:{m['count']}<{min_signals}",
                "cert": cert, "info": info, "match": m}

    return {"ok": True, "reason": "verified", "cert": cert, "info": info, "match": m}
