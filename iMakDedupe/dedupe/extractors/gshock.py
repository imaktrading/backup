"""G-shock 型番 (= MPN) 抽出.

fail-closed: hit せず取れなければ None (= 「不明」、 推測 NG)。

2026-06-12 修正 (= 依頼書 `2026-06-12_gshock_model_extractor_align_with_listing_regex.md`):
出品くん `gshock_to_csv.extract_model_from_text` (= 汎用 regex) と整合.
旧 prefix 固定 whitelist (DW/GW/GA/GST/GMW/GBA/MTG/GMA 等) は GMC/GR/MR 等の取りこぼし発覚で
撤回。 接頭 1-4 大文字 + ハイフン + 残りに数字最低 1 文字 の汎用 regex に変更。

仕様:
- 接頭 1-4 大文字 + ハイフン + 残りに数字最低 1 文字 (= "G-SHOCK" 等の数字なし文字列を除外)
- 末尾 JF/JR optional (= 国内モデルサフィックス)
- 半角スペース除去 (例: 'GW-2320FP -1A1JR' → 'GW-2320FP-1A1JR')、 Mercari/Amazon セラー対応
- 複数候補時 最長 (= 最具体的) → ハイフン多 で優先
- 最終的に大文字統一で返却

cover prefix 拡張 (= 6/12 新規):
- GMC / GR / MR / ECB / EQB 等、 旧 whitelist 漏れの全 prefix を recall
- 取扱外 (= Baby-G BA/BGD、 ProTrek PRG/PRW、 CASIO 標準 W 等) も形式的に hit するが、
  **catalog lookup_gshock 側で「取扱外なら None」 返却** = 解決層で fail-closed (= 設計責務分離)

TCG card_id (= OP10-049 / SV1V-086 等) との衝突:
- TCG card_id は prefix 部分が「アルファベット + 数字」 (= 例 OP10) のため `[A-Z]{1,4}-`
  (= アルファベットのみ) には match しない (= prefix 直前で除外)
- 例外: 遊戯王 (= LIOV-EN042 / RA01-JP001 等) は prefix alpha のみ + 後段 `EN`/`JP` 始まり →
  明示的に除外 (= dedupe 側で TCG 誤検出ゼロ担保、 依頼書 §3 要件)
"""

from __future__ import annotations

import re
from typing import Optional

# 出品くん `gshock_to_csv.extract_model_from_text` (= line 514) と同等の汎用 regex.
# 接頭 1-4 大文字 + `-` + 残りに数字最低 1 文字 (= G-SHOCK 等除外) + 末尾 JF/JR optional.
_GSHOCK_RE = re.compile(
    r"\b([A-Z]{1,4}-(?=[A-Z0-9-]*\d)[A-Z0-9-]{3,18}(?:JF|JR)?)\b",
    re.IGNORECASE,
)

# TCG 遊戯王 card_id 形式 (= prefix-EN\d+ / prefix-JP\d+) 除外用.
# 例: LIOV-EN042 / RA01-JP001 / ETCO-JP021 等
_YGO_CARD_ID_RE = re.compile(r"^[A-Z]{1,5}-(?:EN|JP)\d+$", re.IGNORECASE)


def extract_gshock_model(title: str) -> Optional[str]:
    """G-shock 型番 (= 例 DW-5600-1JF / GA-2100-1A / MTG-B3000B-1A / GMC-B2100Y-1A)."""
    if not title:
        return None
    # 半角スペース除去 (= 出品くんと同等、 メルカリ/Amazon セラー対応)
    t = re.sub(r"(?<=[A-Z0-9])\s+-", "-", title)
    t = re.sub(r"-\s+(?=[A-Z0-9])", "-", t)
    matches = _GSHOCK_RE.findall(t)
    if not matches:
        return None
    # 最長 + ハイフン多 で優先 (= 最具体的)
    matches.sort(key=lambda m: (-len(m), -m.count("-")))
    for m in matches:
        if "-" not in m or len(m) < 6:
            continue
        # TCG 遊戯王 card_id 形式 除外 (= 依頼書 §3 TCG 誤検出ゼロ担保)
        if _YGO_CARD_ID_RE.match(m):
            continue
        return m.upper()
    return None
