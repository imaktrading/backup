#!/usr/bin/env python3
"""eBay の Item Specifics 選択肢を取りに行って保存する (取得日つき).

2026-08-21 制定。それまでは「誰かが取ってくれた JSON」を待つしかなく、
変換表の値は推測のままだった (4ヶ月で 269本の依頼を生んだ原因)。
鍵が共有領域に来たので、カタログが自分で取りに行けるようになった。

## 何を取るか
`commerce/taxonomy/v1 get_item_aspects_for_category` (category 183454 = CCG Individual Cards)。
35 aspect が返る。うち `Set` / `Card Type` は Game 別にも分けて保存する
(全ゲーム混在のまま照合すると 'Promo Cards' が Final Fantasy の 'FF: Promo Cards' に
寄る。2026-08-21 実測)。

## 保存先
    _input/ebay_aspects_183454_<取得日>.json   ← 取得ごとに1ファイル。上書きしない
    _input/ebay_aspects_183454_latest.json     ← 最新へのコピー (照合ツールはこれを見る)

**上書きしないのは、いつの一覧で判断したかを後から追えるようにするため。**

実行:
  python tools/fetch_ebay_aspects.py            # 取得して保存
  python tools/fetch_ebay_aspects.py --dry-run  # 取得して件数だけ表示 (保存しない)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "iMakeBayAPI"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY_ID = "183454"          # CCG Individual Cards
MARKETPLACE = "EBAY_US"
OUT_DIR = Path(r"C:\dev\iMak_data\catalog\_input")
# Game 別に分けて持つ aspect (混ざると別ゲームの値に寄るもの)
SPLIT_BY_GAME = ("Set", "Card Type", "Rarity")


def oauth_token() -> str:
    from credentials import ebay_keys  # 鍵の決定口は1か所だけ
    k = ebay_keys()
    cred = base64.b64encode(f"{k['AppID']}:{k['AppSecret']}".encode()).decode()
    req = urllib.request.Request(
        "https://api.ebay.com/identity/v1/oauth2/token",
        data=urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Authorization": f"Basic {cred}"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())["access_token"]


def fetch_aspects(token: str) -> list:
    url = ("https://api.ebay.com/commerce/taxonomy/v1/category_tree/0/"
           f"get_item_aspects_for_category?category_id={CATEGORY_ID}")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read()).get("aspects", [])


def shape(aspects: list) -> dict:
    """API の返りを、照合ツールが使う形に整える."""
    out = {}
    for a in aspects:
        name = a["localizedAspectName"]
        c = a.get("aspectConstraint", {})
        vals, by_game = [], defaultdict(list)
        for v in a.get("aspectValues", []):
            s = (v.get("localizedValue") or "").strip()
            if not s:
                continue
            vals.append(s)
            # 値に紐づく Game (eBay は valueConstraints で親 aspect を返す)
            for vc in v.get("valueConstraints", []):
                for ac in vc.get("applicableForLocalizedAspectValues", []):
                    if vc.get("applicableForLocalizedAspectName") == "Game":
                        by_game[ac.strip()].append(s)
        out[name] = {
            "all": vals,
            "by_game": {g: sorted(set(x)) for g, x in by_game.items()},
            "constraint": {
                "required": c.get("aspectRequired"),
                "usage": c.get("aspectUsage"),
                "mode": c.get("aspectMode"),
                "data_type": c.get("aspectDataType"),
                # ★2026-08-22 追加: 複数値を入れてよい aspect かどうか。
                #   これを落とすと Features のような項目で「1つしか入れられない」と
                #   誤解する (旧マスタには在ったのに新しい取得で落ちていた)。
                "cardinality": c.get("itemToAspectCardinality"),
            },
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=== eBay Item Specifics 取得 (category %s / %s) ===" % (CATEGORY_ID, MARKETPLACE))
    tok = oauth_token()
    print("  OAuth: OK")
    raw = fetch_aspects(tok)
    data = shape(raw)
    print("  aspect: %d\n" % len(data))

    print("  %-24s %8s %6s %-14s %s" % ("aspect", "値数", "Game別", "必須", "mode"))
    for name, a in data.items():
        req = "★必須" if a["constraint"]["required"] else ""
        print("  %-24s %8d %6d %-14s %s"
              % (name, len(a["all"]), len(a["by_game"]), req, a["constraint"]["mode"]))

    missing = [n for n in SPLIT_BY_GAME if n in data and not data[n]["by_game"]]
    if missing:
        print("\n  ⚠ Game 別に分けられなかった aspect: %s" % missing)
        print("    (eBay が valueConstraints を返していない。全ゲーム混在のまま使うと"
              " よそのゲームの値に寄るので、照合側で注意)")

    if args.dry_run:
        print("\n(--dry-run のため保存していません)")
        return 0

    today = date.today().isoformat()
    doc = {"category_id": CATEGORY_ID, "marketplace": MARKETPLACE, "fetched": today,
           "source": "commerce/taxonomy/v1 get_item_aspects_for_category",
           "aspects": data}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dated = OUT_DIR / f"ebay_aspects_{CATEGORY_ID}_{today}.json"
    latest = OUT_DIR / f"ebay_aspects_{CATEGORY_ID}_latest.json"
    body = json.dumps(doc, ensure_ascii=False, indent=1)
    dated.write_text(body, encoding="utf-8")
    latest.write_text(body, encoding="utf-8")
    print("\n  保存: %s" % dated)
    print("  最新: %s" % latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
