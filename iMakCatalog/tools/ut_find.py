# -*- coding: utf-8 -*-
"""出品くんの「カタログに無い」依頼を **1本で探す** (2026-09-14 新設・ユーザー指示).

ユーザー:「出品くんで、カタログにない→依頼の場合、どうやって探すの？」
これまでは道具がばらばらで、依頼のたびに手で順番に回していた。1本にする。

## 入力

依頼書 (`catalog/requests/*_ut_not_in_catalog.md`) の表をそのまま読む。
使う列: メルカリのタイトル / 色 / サイズ / タグの番号 / 写真URL

## 探す順番 (上から当たった所で止める)

    1. タグの番号 (E######-###) が有る
         → catalog に在るか → 無ければ 公式 jp → us → kr → レビューAPI(廃盤判定) → Wayback → 画像サーバー
    2. 番号が無い
         → タイトルから語を拾う (コラボ名・キャラ名。辞書は catalog のコラボ名から作る)
         → catalog を検索 (公式の行 + 柄の記録)。候補が 1〜数件に絞れれば返す
         → 絞れなければ候補の一覧を返す (目視で選ぶ用。こちらで1件に決めない)
    3. どれにも当たらない → 「見つからない」+ 理由

★Google 検索と画像読み取りは Claude のツールでしか使えないので、この道具では回さない。
  出力に「Google で引く語」を書いておき、依頼を受けたセッションがそれで引く。

## 出力

    C:/dev/iMak_data/catalog/requests/<依頼書名>_response_draft.md
    行ごとに 結果 (在る / 中身なし / 柄の記録だけ / 見つからない) と 根拠・候補の品番

★公式の品番でない行 (柄の記録 FP...) は「出品不可」と明記する (KEY の取り違え防止)。

実行:
    python tools/ut_find.py <依頼書のパス>
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PID = re.compile(r"E\d{6}-\d{3}")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"}
API = {"jp": "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/price-groups/00/details?httpFailure=true",
       "us": "https://www.uniqlo.com/us/api/commerce/v5/en/products/{pid}/price-groups/00/details?httpFailure=true",
       "kr": "https://www.uniqlo.com/kr/api/commerce/v5/ko/products/{pid}/price-groups/00/details?httpFailure=true"}
REVIEWS = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/reviews?limit=1"
NOISE = set("ユニクロ UNIQLO UT Tシャツ tシャツ T シャツ 新品 未使用 限定 サイズ メンズ レディース "
            "MENS WOMENS ホワイト ブラック ネイビー グレー ベージュ 半袖 長袖 コラボ 海外 日本未発売 "
            "韓国 XS S M L XL XXL 3XL 4XL".split())


def _json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def parse_request(path: Path) -> list[dict]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|") or "---" in ln or "タイトル" in ln:
            continue
        c = [x.strip() for x in ln.strip("|").split("|")]
        if len(c) < 4:
            continue
        rows.append({"title": c[0], "color": c[1] if len(c) > 1 else "",
                     "size": c[2] if len(c) > 2 else "", "tag": c[3] if len(c) > 3 else "",
                     "photo": c[-1] if c[-1].startswith("http") else ""})
    return rows


def load_catalog() -> list[dict]:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    out = []
    for pid, name, specs in db.execute(
            "SELECT product_id, name, specs FROM products WHERE category IN ('uniqlo_ut','gu')"):
        s = json.loads(specs or "{}")
        if s.get("not_tee"):
            continue
        out.append({"pid": pid, "name": name or "", "collab": s.get("collab") or "",
                    # ★キャラ名は商品名に無く説明文や英語名にあることが多い (「ポケモン UT」だけの名前)
                    "hay": " ".join(str(x) for x in (
                        name, s.get("collab"), s.get("long_description"), s.get("design_detail"),
                        s.get("name_en_official_us"), s.get("price_text"),
                        s.get("article_title")) if x),
                    "level": s.get("data_level") or ("overseas" if s.get("region_only") else "full"),
                    "gender": str(s.get("gender") or "").upper(),
                    "colors": [x.get("name", "") for x in (s.get("color_variants") or [])
                               if isinstance(x, dict)],
                    "gone": bool(s.get("official_gone_at"))})
    db.close()
    return out


def by_pid(pid: str, cat: dict[str, dict]) -> tuple[str, str]:
    """番号から (結果, 根拠)."""
    if pid in cat:
        c = cat[pid]
        if c["level"] == "fp_design":
            return "柄の記録だけ", f"{pid} は柄の記録 (出品不可)"
        if c["level"] == "images_only":
            return "中身なし", f"{pid} は画像とコラボ名だけ (出品不可)"
        return "在る", f"{pid} {c['name'][:40]}"
    for reg in ("jp", "us", "kr"):
        d = (_json(API[reg].format(pid=pid)) or {}).get("result") or {}
        if d.get("name"):
            return "公式に在る (未収録)", f"{reg} の公式に在る: {d['name'][:40]} → 取り込みに回す"
    bc = ((_json(REVIEWS.format(pid=pid)) or {}).get("result") or {}).get("breadcrumbs") or {}
    if bc:
        return "中身なし", f"{pid} は公式の分類だけ残っている (廃盤) → Wayback/画像を試す"
    return "見つからない", f"{pid} は公式のどこにも無い"


def words(title: str) -> list[str]:
    t = re.sub(r"[【】\[\]()（）/／・,、!！?？]", " ", title)
    return [w for w in t.split() if len(w) >= 2 and w not in NOISE and not re.fullmatch(r"\d+.*", w)]


def by_words(row: dict, cat_list: list[dict]) -> tuple[str, str, list[dict]]:
    import math
    ws = words(row["title"])
    # ★珍しい語ほど重く数える。「ポケモン」は数十行に当たるが「イーブイ」は数行 (2026-09-14 実測:
    #   語の数だけで数えたら 8件とも「ポケモン」で49件に広がり、1件も絞れなかった)
    df = {w: sum(1 for c in cat_list if w in c["hay"]) for w in ws}
    n = len(cat_list)
    scored = []
    for c in cat_list:
        hit = sum(math.log(n / (1 + df[w])) for w in ws if df[w] and w in c["hay"])
        if hit:
            if row["color"] and any(row["color"][:2] in x or x.lower() in row["color"].lower()
                                    for x in c["colors"]):
                hit += 0.5
            scored.append((round(hit, 3), c))
    if not scored:
        return "見つからない", f"タイトルの語 {ws} に当たる行が無い", []
    best = max(h for h, _ in scored)
    cands = [c for h, c in scored if h == best]
    full = [c for c in cands if c["level"] in ("full", "overseas")]
    if len(full) == 1:
        return "在る (候補1件)", f"語 {ws} で1件に絞れた", full
    if full:
        return "候補が複数", f"語 {ws} で {len(full)}件。写真で目視して選ぶ", full[:12]
    return "柄の記録だけ", f"語 {ws} で当たるのは柄の記録だけ (出品不可)", cands[:12]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    req = Path(sys.argv[1])
    rows = parse_request(req)
    cat_list = load_catalog()
    cat = {c["pid"]: c for c in cat_list}
    stat = Counter()
    lines = [f"# 回答 (下書き): {req.stem}", "", f"- ut_find.py で自動作成 / 行数 {len(rows)}", ""]
    for i, r in enumerate(rows, 1):
        tag = (PID.findall(r["tag"]) or PID.findall(r["title"]) or [None])[0]
        if tag:
            res, why = by_pid(tag, cat)
            cands = []
        else:
            res, why, cands = by_words(r, cat_list)
        stat[res] += 1
        lines += [f"## {i}. {r['title']}", "", f"- 結果: **{res}**", f"- 根拠: {why}"]
        for c in cands:
            flag = " (出品不可)" if c["level"] in ("fp_design", "images_only") else ""
            lines.append(f"  - {c['pid']}  {c['name'][:50]}{flag}")
        if res in ("見つからない", "候補が複数", "柄の記録だけ"):
            q = " ".join(["ユニクロ UT"] + words(r["title"])[:3])
            lines.append(f"- Google で引く語: `{q}` (uniqlo.com に限定)。写真: {r['photo']}")
        lines.append("")
    out = req.with_name(req.stem + "_response_draft.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"=== {req.name} — {len(rows)}行 ===")
    for k, v in stat.most_common():
        print(f"  {k:20s} {v}")
    print(f"  → {out}")


if __name__ == "__main__":
    main()
