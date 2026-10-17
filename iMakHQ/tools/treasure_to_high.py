#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""トレジャーハントの候補 (中間スプシ `mercari_psa10_treasure`) を HIGH に「出品待ち」で足す。

    python iMakHQ/tools/treasure_to_high.py            # 何行足すか見るだけ
    python iMakHQ/tools/treasure_to_high.py --write    # HIGH に足して、中間スプシを緑に塗る
    python iMakHQ/tools/treasure_to_high.py --tab=chara [--write]   # キャラで拾った候補 (2026-09-24)

★2026-09-21 ユーザー確定「とりあえず、7マン以下は HIGH にコピーしたいね。重複があるなら除いて」
  「コピーしたら、色塗りして。重複も色塗り」。
  - 仕入値 (F列) が **会社の上限 7万円以下** の行だけ
  - HIGH に同じ仕入元 URL か 鑑定番号 が在る行は足さない (重複)。タブの中の重複も1行だけ
  - 足した行と、もともと HIGH に在った行を **緑** に塗る (緑 = HIGH にある行。harvest-targeting ③)

書く列 (psa_resource_gate.new_listing_rows_from_confirmed と同じ作り + PSA の新規分):
  A URL / C タイトル / D〜J (状態・F 仕入値・写真・説明・I 鑑定番号・J) / L ConditionID /
  R カテゴリ=TCG / S 色 / T サイズ / AC〜AG 補URL
★書かない列:
  B itemID (空 = まだ出していない = 出品くんが拾う) / K・M (HIGH では ポイント・現在価格。
  中間スプシの K・M は別の意味) / N・P (HIGH の数式) / **KEY** (未出品の行に KEY があると
  二重出品の守りが「出品済」と読んで止める。KEY は出品くんが判定した時に書く)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io as S
import treasure_fill_key as T

COST_CAP = 70000
GREEN = {"red": 0.851, "green": 0.918, "blue": 0.827}      # #d9ead3
COPY_COLS = (0, 2, 3, 4, 5, 6, 7, 8, 9, 11, 18, 19, 28, 29, 30, 31, 32)
COL_CATEGORY = 17


def _g(r, i):
    return (r[i] if len(r) > i else "").strip()


def _price(s):
    return int(re.sub(r"[^\d]", "", s or "") or 0)


# ★2026-10-11 ユーザー「空欄が追加できると判断したい」「中間スプシ内だけで活用したらいいやん」:
#   中間スプシの B列 (見出し itemID・どのタブも空だった) に印を書く。B列が空 = HIGH に追加できる。
#   印のある行は足さない。候補外の理由がある行も足さない (それまで理由を見ずに 368行を足す計算になっていた)
COL_FLAG = 1
FLAG_HIGH = "HIGH追加済"
# ★2026-10-11 ユーザー「価格上限越えの表現が複数あるから統一して」: 2つは別物 (カードごとの相場上限 / 会社の7万円) なので
#   「仕入値が高い」でそろえ、括弧でどちらかを書く
REASON_LABEL = (("vision_skipped", "写真を読めていない"), ("card_cost_over", "仕入値が高い（相場から見た上限超え）"),
                ("cost_over_limit", "仕入値が高い（7万円超）"),
                ("seller_rating", "出品者の評価不足"), ("bundle", "まとめ売り"), ("sold", "売り切れ"))


def flag_of_reason(reason):
    """候補外の理由 → B列に書く印 (純関数)。"""
    r = (reason or "").strip()
    for k, label in REASON_LABEL:
        if r.startswith(k):
            return "候補外: " + label
    return "候補外: " + r[:20]


def plan(treasure_rows, high_rows, cap=COST_CAP, reason_col=None):
    """どの行を足して、どの行を塗るか (純関数)。

    treasure_rows / high_rows: 見出しを除いた行 (list)。戻り: (足す[(シート行番号, 行)], 塗る行番号, 数)
    数["flags"] = {シート行番号: B列に書く印} (足す行は書いた後に HIGH追加済 を付ける)
    """
    hu = {_g(r, 0) for r in high_rows if _g(r, 0)}
    # ★2026-10-11: HIGH の補URL (AC〜AG) に使われている出品も足せない (足すと HIGH 側で弾かれ「見当たらない」になっていた)
    aux = {_g(r, c) for r in high_rows for c in range(28, 33) if _g(r, c)} - hu
    hc = {_g(r, 8) for r in high_rows if _g(r, 8)}
    add, paint, seen = [], [], set()
    n = {"over": 0, "noprice": 0, "in_high": 0, "dup_tab": 0, "flagged": 0, "reason": 0, "flags": {}}
    for i, r in enumerate(treasure_rows, start=2):
        url, cert, p = _g(r, 0), _g(r, 8), _price(_g(r, 5))
        if _g(r, COL_FLAG):
            n["flagged"] += 1                                   # もう印がある = 判断済み
            continue
        if url in hu or (cert and cert in hc):
            n["in_high"] += 1
            paint.append(i)
            n["flags"][i] = FLAG_HIGH
            continue
        if url in aux:
            n["aux"] = n.get("aux", 0) + 1
            n["flags"][i] = "候補外: 補URLで使用中"
            continue
        if reason_col is not None and _g(r, reason_col):
            n["reason"] += 1
            n["flags"][i] = flag_of_reason(_g(r, reason_col))
            continue
        if not p:
            n["noprice"] += 1
            n["flags"][i] = "候補外: 値段が読めない"
            continue
        if p > cap:
            n["over"] += 1
            n["flags"][i] = "候補外: 仕入値が高い（7万円超）"
            continue
        key = url or cert
        if key in seen:
            n["dup_tab"] += 1
            paint.append(i)
            n["flags"][i] = "候補外: タブ内の重複"
            continue
        seen.add(key)
        row = [""] * 39
        for c in COPY_COLS:
            row[c] = _g(r, c)
        row[COL_CATEGORY] = "TCG"
        add.append((i, row))
        paint.append(i)
    return add, paint, n


# ★2026-09-24: キャラで拾った候補 (抽出くんの `mercari_psa10_chara`) も同じ作りで HIGH に足せるようにする。
#   列は treasure と同じ。枠に入れる順は tcg_batch_select が「市場で売れた枚数」で決める
#   (キャラで広く拾い、売れるカードを先に出す。ユーザー確定 2026-09-24)
TABS = {"treasure": T.TAB, "chara": "mercari_psa10_chara"}


def tab_of(argv):
    """--tab=treasure|chara (既定 treasure) → 中間スプシのタブ名。知らない名前は止める。"""
    for a in argv:
        if a.startswith("--tab="):
            k = a.split("=", 1)[1]
            if k not in TABS:
                raise SystemExit(f"--tab は {'/'.join(TABS)} のどれか: {k}")
            return TABS[k]
    return TABS["treasure"]


def pick_buyable(add, limit, check=None, sold_rows=None):
    """足す候補を上から見て、メルカリで今も買える物だけ limit 件選ぶ。戻り (選んだ, 外した数)。

    sold_rows: 渡すと「読めたが買えない (売り切れ)」と分かった行番号を足す (B列に印を付けるため)。
      読めなかった行 (check が None) は印を付けない = 次回また確かめる。
    """
    if check is None:
        import mercari_psa_resource as mp

        def check(url):
            d = mp.api_detail(url)
            return None if not d else bool(d.get("buyable"))
    out, skipped = [], 0
    for i, row in add:
        if len(out) >= limit:
            break
        ok = check(row[0])
        if ok:
            out.append((i, row))
        else:
            skipped += 1
            if ok is False and sold_rows is not None:
                sold_rows.append(i)
    return out, skipped


def main(argv):
    import psa_hoju_fill as H
    tab = tab_of(argv)
    _all = S.read_tab(tab, sheet_id=T.SHEET_ID)
    tr = _all[1:]
    if not tr:
        print(f"中間スプシ {tab} に行がありません")
        return 0
    rc = _all[0].index("候補外の理由") if "候補外の理由" in _all[0] else None
    hi = H._read_high()[1:]
    add, paint, n = plan(tr, hi, reason_col=rc)
    print(f"中間スプシ {len(tr)}行 → HIGH に足す {len(add)}行 / 塗る {len(paint)}行")
    print(f"  7万円超 {n['over']} / 値段が読めない {n['noprice']} / もう HIGH にある {n['in_high']} / "
          f"タブ内の重複 {n['dup_tab']} / 候補外の理由あり {n['reason']} / B列に印あり (判断済み) {n['flagged']}")
    lim = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--limit=")), None)
    if lim is not None:
        # ★2026-10-05 ユーザー「200追加して」: 一度に全部 (3,474行) 入れると新規の目視が溢れるので件数で区切る。
        #   入れる前にメルカリで今も買えるかを確かめ、買える物だけを上から lim 件 (10/5 の抜き取りで 9割が買えた)
        _sold = []
        if "--no-check" in argv:
            # ★2026-10-17 ユーザー「それは監視くんに任せたらいいのでは？」: 売り切れは HIGH に入れば監視くんが見るので、
            #   ここでメルカリに1件ずつ聞かない。上から lim 件をそのまま足す
            add, skipped = add[:lim], 0
        else:
            add, skipped = pick_buyable(add, lim, sold_rows=_sold)
        for i in _sold:
            n["flags"][i] = "候補外: 売り切れ"
        allowed = {i for i, _r in add}
        planned = {i for i, _r in plan(tr, hi, reason_col=rc)[0]}
        paint = [i for i in paint if i not in planned or i in allowed]   # 入れなかった行は塗らない (次回の候補)
        print(f"  --limit={lim}: 買える物を {len(add)}行 選んだ (確かめて売り切れ・読めないで外した {skipped}行)")
    if "--write" not in argv:
        print("★書くなら --write")
        return 0
    added = S.append_product_rows([r for _, r in add]) if add else 0
    # 確かめてから塗る: HIGH を読み直して、足した URL が本当に入ったか
    hi2 = {_g(r, 0) for r in H._read_high()[1:]}
    miss = [i for i, r in add if r[0] and r[0] not in hi2]
    ws = S._open(T.SHEET_ID).worksheet(tab)
    ok = [i for i in paint if i not in miss]
    last = S.col_letter(len(tr[0])) if hasattr(S, "col_letter") else "AL"
    reqs = [{"range": f"A{i}:{last}{i}", "format": {"backgroundColor": GREEN}} for i in ok]
    for k in range(0, len(reqs), 200):
        ws.batch_format(reqs[k:k + 200])
    # B列に印 (HIGH に入ったのを確かめた行だけ HIGH追加済。入らなかった行は空のまま = 次回の候補)
    flags = dict(n["flags"])
    flags.update({i: FLAG_HIGH for i, _r in add if i not in miss})
    if flags:
        ws.batch_update([{"range": f"B{i}", "values": [[v]]} for i, v in sorted(flags.items())],
                        value_input_option="RAW")
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    print(f"HIGH に足した {added}行 / HIGH に見当たらない {len(miss)}行 / 緑に塗った {len(ok)}行"
          f" / B列に印 {len(flags)}行 (HIGH追加済 {sum(1 for v in flags.values() if v == FLAG_HIGH)})")
    if miss:
        print("⚠️要対応: HIGH に入っていない行 (塗っていない):", miss[:20])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
