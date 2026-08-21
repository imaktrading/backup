"""rakuten_delivery - 楽天の `deliveryMessage` から「即納か」を判定する.

2026-08-22 新設 (窓口 依頼 `2026-08-21_gacha_next_steps`)。

★**判定条件をこのファイルに書かない**。 唯一の条件表は
`C:/dev/iMak_data/shared/rakuten_delivery_rule.json` (窓口が8ケース検算済み)。
監視くん・出品側も同じ表を読む。 3箇所に書き写すとズレる。

以前は **ブラウザで描画後の「配送予定」欄**を読んでいたため、 店ごとに書き方が違い
(`即納｜…当日出荷` / `最短8/22(翌日)お届け` / `翌営業日までに発送`)、 その都度
正規表現を足していた。 `deliveryMessage` は静的HTMLに入っており 書き方が揃うので、
そちらへ寄せる。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RULE_PATH = Path(r"C:/dev/iMak_data/shared/rakuten_delivery_rule.json")

IMMEDIATE = "immediate"
PREORDER = "preorder"
SKIP = "skip"

_rule: dict | None = None


def load_rule(path: Path | None = None) -> dict:
    """条件表を読む (プロセス内キャッシュ)."""
    global _rule  # noqa: PLW0603
    if _rule is None or path is not None:
        p = path or RULE_PATH
        _rule = json.loads(p.read_text(encoding="utf-8"))
    return _rule


def judge_message(msg: str, rule: dict | None = None) -> str:
    """`deliveryMessage` -> immediate / preorder / skip.

    順序は表の `order` のとおり: DENY が先、 次に IMMEDIATE、 どちらでもなければ skip。
    **skip を即納に倒さない** (取寄せ・入荷次第を即納と誤判定すると、 無在庫で
    予約品を掴んでキャンセル -> Defect Rate -> BAN になる)。
    """
    r = rule or load_rule()
    m = (msg or "").strip()
    if not m:
        return SKIP
    if re.search(r["deny"], m):
        return PREORDER
    if re.search(r["immediate"], m):
        return IMMEDIATE
    return SKIP
