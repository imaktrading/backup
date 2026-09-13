# -*- coding: utf-8 -*-
"""タグの実物で品番が確かめられた UT を「画像だけの行」で入れる (2026-09-14).

出品くん依頼 `requests/2026-09-13_ut_not_in_catalog.md` の5行目
「ユニクロ新品未使用UT ヤムチャ 50th ドラゴンボール」。

    メルカリ写真2枚目のタグ: 「341-410898」 + 週刊少年ジャンプ 50th のタグ → 品番 E410898-000
    公式 jp / us detail : 404
    レビュー API        : 200 だが分類 (パンくず) が空
    Wayback            : 中身なし
    画像サーバー         : **4枚残っている**

ふだんの「画像だけの行」(`uniqlo_ut_images_only.py`) は公式の分類で UT を確かめてから入れるが、
この品番は分類が空で通らない。代わりに **タグの実物** (UT ロゴ + 品番 + ジャンプ50周年タグ) を
根拠にする (PSA のスラブ = 現物の印字、と同じ扱い)。

入れる値は画像と品番だけ。名前はコラボの表示「週刊少年ジャンプ 50th ドラゴンボール (ヤムチャ)」を
写真の印字 (YAMCHA SAAAN!) に基づいて付け、`name_is_collab_label=true` の印を付ける。
**出品には使わない** (`data_level=images_only`)。

実行:
    python migrations/2026-09-14_ut_yamcha_e410898_images_only.py --commit
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PID = "E410898-000"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    imgs = R.images_of(PID)
    print(f"{PID}: 画像 {len(imgs)}枚")
    if not imgs:
        print("画像が無いので入れない")
        return
    now = datetime.now().isoformat(timespec="seconds")
    label = "週刊少年ジャンプ 50th ドラゴンボール UT (ヤムチャ)"
    specs = {
        "gender": "MEN", "department": "Men", "collab": "週刊少年ジャンプ 50th",
        "name_is_collab_label": True, "data_level": "images_only", "not_for_listing": True,
        "image_urls": imgs, "official_gone_at": now, "revived_at": now,
        "revived_from": "tag_photo+cdn",
        "evidence": ("出品くん依頼 2026-09-13_ut_not_in_catalog 5行目。メルカリ m26495721051 の"
                     "写真2枚目のタグ「341-410898」+ 週刊少年ジャンプ50thタグ + UT ロゴ。"
                     "公式 detail は jp/us とも 404、レビュー API の分類は空"),
        "brand": "Uniqlo", "category_line": "UT",
    }
    if a.commit:
        api.upsert(category="uniqlo_ut", product_id=PID, name=label, name_jp=label,
                   set_name=None, set_name_official=None, card_set_id=None, language="ja",
                   specs=specs, images=imgs, source="uniqlo_tag_photo_cdn",
                   source_url=R.PDP.format(pid=PID))
        print("入れた")
    else:
        print("(dry-run — --commit で適用)")


if __name__ == "__main__":
    main()
