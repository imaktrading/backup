"""ut_tag_vision - メルカリ UT の写真から **タグの6桁の商品番号** を読む (目視の材料).

2026-09-11 新設 (Advisor POC)。 ★これで KEY を決めない。 目視画面の材料として
行に残すだけ (user 判断「PSA と同じように目視で特定」)。

実測 (2026-09-11, 25件): 読めた6件のうち1件が **別商品の番号** だった
(呪術廻戦の出品から ポケモン UT の番号)。 なので「読めた」は候補の手掛かり止まり。
"""
from __future__ import annotations

import re

from scrapers.color_vision import MODEL_ID, _get_client

PROMPT = ("これはメルカリに出品された服の写真です。ユニクロ/GU のタグ (品質表示・値札・"
          "ブランドタグ) に印字された **6桁の商品番号** (例: 486159) が写っていれば、"
          "その数字だけを答えてください。写っていない・読めない時は NONE とだけ答えてください。"
          "推測しないこと。")
_SIX_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def parse_answer(text: str) -> str:
    """Vision の答えから6桁だけ取り出す (純関数). 無ければ空."""
    m = _SIX_RE.search(text or "")
    return m.group(1) if m else ""


def read_tag_number(image_urls: list[str], client=None, max_images: int = 8) -> dict:
    """{number, error}. 読めなければ number は空。 障害は error に入れる (混ぜない)."""
    urls = [u for u in (image_urls or []) if u and u.startswith("http")][:max_images]
    if not urls:
        return {"number": "", "error": ""}
    content = [{"type": "image", "source": {"type": "url", "url": u}} for u in urls]
    content.append({"type": "text", "text": PROMPT})
    try:
        msg = (client or _get_client()).messages.create(
            model=MODEL_ID, max_tokens=30,
            messages=[{"role": "user", "content": content}])
        return {"number": parse_answer(msg.content[0].text), "error": ""}
    except Exception as e:  # noqa: BLE001
        # こちらの障害 (残高切れ等)。 「読めなかった」と混ぜない
        return {"number": "", "error": f"{type(e).__name__}"}
