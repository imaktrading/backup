"""psa_slab_vision - PSA スラブ出品写真から ラベル記載事項を読む (Claude Vision).

2026-08-17 新設。 2026-06-24 の POC (debug/poc_psa_cert_mercari.py、 Mercari 実画像で
cert 読取 12/12) を module 化し、 **cert 以外の項目も読む** ように拡張した。
cert だけだと 1 桁誤読を検出できないが、 ラベルのカード名 / 弾名 / 番号 / 年 も一緒に読めば
[[psa_cert.match_signals]] で PSA 公式と多信号突合でき、 誤読が落とせる。

設計は既存 vision_card_id.py / color_vision.py と同じ:
  - fail-closed: 読めない項目は空文字 (推測で埋めない)
  - API key は color_vision と同経路
"""
from __future__ import annotations

import json
import re
from typing import Optional

from scrapers.color_vision import MODEL_ID, _get_client

PROMPT = """この画像は PSA 鑑定済みトレーディングカードのスラブ(プラケース)の出品写真です。
上部の鑑定ラベルに印字されている内容を読み取ってください。

【出力 (JSON 1行のみ、他の文字は一切出力しない)】
{"cert":"<認証番号 8-9桁 or NONE>","grade":"<GEM MT 10 等 or NONE>","label":"<ラベルの年・弾名・カード名の行をそのまま or NONE>","card_number":"<カード番号 or NONE>","year":"<西暦4桁 or NONE>"}

ルール:
- 鮮明に読み取れた項目だけ埋める。 不鮮明 / 見切れ / 裏面のみ / 確証なし → "NONE"
- **推測で埋めない**。 1文字でも自信が無ければ "NONE" (誤読は事故になる)
- label は翻訳せず、 ラベルに印字されている通りの英字表記のまま書く
- ラベルが写っていない (カード単体・裏面のみ 等) → 全項目 "NONE"
"""

CERT_RE = re.compile(r"^\d{8,9}$")
_NONE = {"", "NONE", "N/A", "NULL", "UNKNOWN", "不明"}
_FIELDS = ("cert", "grade", "label", "card_number", "year")
DEFAULT_MAX_IMAGES = 4

# error に入る値。 「読めなかった」 (= 写真の問題、 正常な reject) と
# 「確認できなかった」 (= API 障害・残高切れ、 こちらの問題) を混ぜない。
# 2026-08-17: API 残高切れ時に 12 件全部が「ラベル不鮮明」として静かに消え、
# 障害だと気づけなかった (グローバル CLAUDE.md「silent drop 禁止」)。
ERR_NO_IMAGE = "no_image"
ERR_NO_CLIENT = "vision_client_unavailable"
ERR_API = "vision_api_error"
ERR_NO_TEXT = "vision_empty_response"


def _clean(v) -> str:
    s = str(v or "").strip()
    return "" if s.upper() in _NONE else s


def _empty(error: str = "") -> dict:
    d = {k: "" for k in _FIELDS}
    d["error"] = error
    return d


def parse_response(text: str) -> dict:
    """Vision 応答 (JSON 文字列) を dict に (純関数 = テスト対象).

    JSON が壊れている / cert が桁数不正 → 該当項目を空文字にして返す (fail-closed)。
    """
    out = _empty()
    t = text or ""
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return out
    try:
        j_obj = json.loads(t[i:j + 1])
    except Exception:  # noqa: BLE001 - 壊れ JSON は全項目空で返す
        return out
    if not isinstance(j_obj, dict):
        return out
    for k in _FIELDS:
        out[k] = _clean(j_obj.get(k))
    if not CERT_RE.match(out["cert"]):
        out["cert"] = ""
    return out


def read_slab(image_urls: list[str], client=None,
              max_images: int = DEFAULT_MAX_IMAGES,
              timeout: int = 40) -> dict:
    """出品写真 (複数アングル) から ラベル項目を読む.

    Returns: {"cert","grade","label","card_number","year","error"}
             error="" = 正常に読めた (項目が空なら 写真から読めなかった)。
             error!="" = **こちらの障害で確認できなかった** (= 呼出側は「不鮮明」と
             同列に数えず、 障害として報告すること)。
    """
    urls = [u for u in (image_urls or []) if u and u.startswith("http")][:max_images]
    if not urls:
        return _empty(ERR_NO_IMAGE)
    cli = client or _get_client()
    if cli is None:
        return _empty(ERR_NO_CLIENT)

    content = [{"type": "image", "source": {"type": "url", "url": u}} for u in urls]
    content.append({"type": "text", "text": PROMPT})
    try:
        msg = cli.messages.create(model=MODEL_ID, max_tokens=200, timeout=timeout,
                                  messages=[{"role": "user", "content": content}])
    except Exception as e:  # noqa: BLE001 - 残高切れ / rate limit / timeout 等
        return _empty(f"{ERR_API}:{type(e).__name__}:{str(e)[:120]}")
    for b in (msg.content or []):
        if getattr(b, "text", None):
            return parse_response(b.text)
    return _empty(ERR_NO_TEXT)
