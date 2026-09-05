# -*- coding: utf-8 -*-
"""公式のプロモ一覧に在って catalog に無かった 50枚を入れる (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り** (行が足りない)。
公式 (onepiece-cardgame.com) を今その場で取り直して確認した。

## 何が起きていたか

公式のプロモ/限定ページは、**同じ券面番号の別刷り**を `OP10-022_p2` のような
**枝番つきの id** で並べている。catalog は bandai の API から取り込んでいるので、
API に無い配布物 (交流会記念品 / 雑誌付録 / 大会記念品 など) の刷りが入っていない。

    OP10-022_p2  メラメラの実争奪戦 上位記念品     → catalog に行が無い
    OP15-068_p1  スタンダードバトルパックVol.17    → 同上

PSA はこの刷りを鑑定するので、行が無いと **ブースターの行に当たってしまう**
(= 収録商品が違うまま出品) か、引けずに落ちる。

## 入れ方

公式ページの1枚ぶんの塊から そのまま写す (推測しない)。
`set_name_official` は公式の「入手情報」。`integrations/psa_to_csv.py` の
`_op_edition_matches` が PSA ラベルの商品名と突き合わせるので、ここが正確なほど引ける。

実行:
  python migrations/2026-09-05_op_promo_rows.py [--commit]
"""
from __future__ import annotations

import argparse
import html as H
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import official_drift_check as O  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SERIES = ["550901", "550801", "550204", "550115", "550117"]
BASE = "https://www.onepiece-cardgame.com/images/cardlist/card/"
SOURCE = "opcg_official_promo_20260905"


def _txt(block: str, cls: str) -> str:
    m = re.search(rf'class="{cls}"><h3>[^<]*</h3>(.*?)</div>', block, re.S)
    if not m:
        return ""
    return O._norm(re.sub(r"<[^>]+>", " ", m.group(1)))


def _label(block: str, cls: str) -> str:
    """その欄の見出し。LEADER だけ `class="cost"` の見出しが「ライフ」になる."""
    m = re.search(rf'class="{cls}"><h3>([^<]*)</h3>', block)
    return (m.group(1).strip() if m else "")


def parse_block(b: str) -> dict | None:
    mid = re.search(r'<dl class="modalCol" id="([^"]+)"', b)
    m_info = re.search(r'class="infoCol">(.*?)</div>', b, re.S)
    m_name = re.search(r'class="cardName">([^<]+)<', b)
    if not (mid and m_info and m_name):
        return None
    cells = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<span>(.*?)</span>", m_info.group(1))]
    if not cells:
        return None
    m_img = re.search(r'data-src="[^"]*?/card/([^"?]+)', b)
    m_attr = re.search(r'class="attribute">.*?alt="([^"]*)"', b, re.S)
    return {
        "product_id": mid.group(1),
        "card_number": cells[0],
        "rarity": cells[1] if len(cells) > 1 else "",
        "card_type": cells[2] if len(cells) > 2 else "",
        "name": O._norm(H.unescape(m_name.group(1))),
        # ★LEADER は「コスト」ではなく「ライフ」。公式は同じ div (class="cost") に
        #   見出しだけ変えて出す。見出しを見ずに写すと Leader に cost が付き、
        #   「その種別が持ち得ない項目」に出る (2026-08-25 に 105行直した所と同じ穴)。
        "cost": _txt(b, "cost") if _label(b, "cost") == "コスト" else "",
        "life": _txt(b, "cost") if _label(b, "cost") == "ライフ" else "",
        "power": _txt(b, "power"),
        "counter": _txt(b, "counter"), "color": _txt(b, "color"),
        "feature": _txt(b, "feature"), "card_text": _txt(b, "text"),
        "attribute": H.unescape(m_attr.group(1)) if m_attr else "",
        "get_info": _txt(b, "getInfo"),
        "image": BASE + m_img.group(1) if m_img else "",
    }


def run(commit: bool) -> None:
    seen, added = set(), 0
    print(f"=== 公式プロモの取り込み ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for sid in SERIES:
        page = O._get(O.LIST_URL.format(sid=sid))
        for b in re.split(r'(?=<dl class="modalCol")', page)[1:]:
            c = parse_block(b)
            if not c or c["product_id"] in seen:
                continue
            seen.add(c["product_id"])
            if api.lookup("one_piece_tcg", c["product_id"]) is not None:
                continue                       # 既に在る行は **触らない**
            print(f"    + {c['product_id']:18s} {c['name']:<22s} {c['get_info']}")
            added += 1
            if not commit:
                continue
            specs = {k: v for k, v in c.items() if k in (
                "rarity", "card_type", "cost", "life", "power", "counter", "color",
                "feature", "card_text", "attribute", "card_number") and v}
            api.upsert(
                category="one_piece_tcg", product_id=c["product_id"],
                name=c["name"], name_jp=c["name"],
                set_name=c["get_info"], set_name_official=c["get_info"],
                card_set_id=None, language="ja", specs=specs,
                images=[c["image"]] if c["image"] else [],
                source=SOURCE,
                source_url=O.LIST_URL.format(sid=sid) + f"#{c['product_id']}",
            )
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {added}枚")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
