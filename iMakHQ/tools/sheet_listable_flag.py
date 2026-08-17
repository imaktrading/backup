#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sheet_listable_flag.py — 「itemID が空 = 出品候補」の見間違いを止める。

なぜ要るか (2026-08-17 実測):
  ユーザーは HIGH の **itemID 欄が空か**でシートを見て「候補はまだ沢山ある」と判断する。
  ところが itemID 空・売切でない 58行のうち、**本当に出せるのは 13行だけ**だった。
  残り 45行は「同じカードが既に出品中の2枚目」で、**何日待っても出品にならない**。
  = 見た目が「補充はまだ要らない」と誤読させる。これを色で分かるようにする。

やること:
  - AP列に「出せるか」を日本語で書く (出せる / 2枚目(出ない) / 売切 / 見送り / 仕入値なし)。
  - B列(itemID)の空セルを、出せない行だけ **グレーで塗る** 条件付き書式を張る (--setup-format)。
    → 従来どおり itemID 欄を見て「白い空欄=出せる / グレー=出せない」で判断できる。

判定は **出品くん (psa_to_csv) の抽出と同じ順序・同じ関数**を使う (ズレたら意味が無いため)。
B列に印 (9999) を入れる案は採らない: sheet_io は B 非空を「出品済」と読むので、本体が
売れた後に同じカードの次の1枚が **silent に出せなくなる** (2026-08-17 実機で確認)。

実行:
  python -m tools.sheet_listable_flag                 # dry-run (件数だけ)
  python -m tools.sheet_listable_flag --write         # AP列を更新
  python -m tools.sheet_listable_flag --setup-format  # 条件付き書式を張る (初回のみ)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io  # noqa: E402

A, B, D, I, K, M, F, N, R = 0, 1, 3, 8, 10, 12, 5, 13, 17
KEYC = sheet_io.PRODUCT_COL_KEY          # 34 (AI)
FLAG_COL = 41                            # AP (0-indexed) = 空き列
FLAG_HEADER = "出せるか"
OK = "出せる"

# 出品くんの抽出順と同じ。上から順に当てはめ、最初に当たった理由を採る。
SECOND = "2枚目(出ない)"
SAME_CERT = "同じ現物が出品中"
SOLD = "売切"
MIOKURI = "見送り"
NO_COST = "仕入値なし"

# ★2026-08-17 二度目の修正: 抽出を通っても、出品くんは **枠を選ぶ前に** さらに4つ落とす。
#   初版はそれを見ていなかったので「出せる14件」と出したのに CSV は0件だった
#   (= 直そうとした見間違いを、小さくして残していた)。同じ判定関数を使って揃える。
REVIEW_SKIP = "目視で該当なし(待機)"
GAP = "カタログ未収録"
OUT_OF_SCOPE = "参入しないゲーム"
NO_IMAGE = "画像が無く目視できない"


def _cell(row, idx):
    return (row[idx].strip() if len(row) > idx else "")


def classify_row(row, listed_certs, listed_keys, already_listed_reason):
    """1行 → AP列に書く文字 (純関数・test可)。空文字 = 何も書かない (=塗らない)。

    対象は **R列='TCG' かつ cert と URL があり itemID が空** の行だけ。
    それ以外 (出品済 / 別カテゴリ / cert無し) は判定の対象外なので空にする。
    """
    url, item_id, cert = _cell(row, A), _cell(row, B), _cell(row, I)
    if not cert or item_id or not url:
        return ""
    if _cell(row, R) != "TCG":
        return ""
    dup = already_listed_reason(cert, _cell(row, KEYC), listed_certs, listed_keys)
    if dup == "cert":
        return SAME_CERT
    if dup:
        return SECOND
    if _cell(row, D):
        return SOLD
    if _cell(row, K):
        return MIOKURI
    if not (_cell(row, N) or _cell(row, M) or _cell(row, F)):
        return NO_COST
    return OK


def classify_all(rows2d, listed_certs, listed_keys, already_listed_reason):
    """(pure) 全行 → [AP列の値] (header 行を含む・1行目は見出し)。"""
    out = [FLAG_HEADER]
    for row in rows2d[1:]:
        out.append(classify_row(row, listed_certs, listed_keys, already_listed_reason))
    return out


def downgrade_by_preflight(cert, skips, cls, has_image, live_dup):
    """「出せる」行を、出品くんの前段フィルタで落ちるなら理由に差し替える (純関数)。

    cls=None (PSA cache 無し / 例外) は **判定不能なので落とさない**。
    「読めなかった」を「対象外」に倒すと出品機会を静かに失う (向きを間違えない)。
    """
    if cert in skips:
        return REVIEW_SKIP
    if cls is None:
        return ""
    st = (cls or {}).get("status")
    if st == "GAP":
        return GAP
    if st == "OUT-OF-SCOPE":
        return OUT_OF_SCOPE
    if has_image is False:              # None (読めない) では落とさない
        return NO_IMAGE
    if live_dup:
        return SECOND
    return ""


def _preflight_pass(vals, flags):
    """「出せる」判定の行に前段フィルタを当てる (I/O 有り・失敗しても flags を壊さない)。"""
    import datetime as _dt
    import json
    import sqlite3
    targets = [(i, _cell(vals[i], I)) for i, f in enumerate(flags) if f == OK and i < len(vals)]
    if not targets:
        return flags, {}
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "..", "iMakTCG"))
        from tcg_batch_select import load_review_skips, active_review_skips
        skips = active_review_skips(load_review_skips(), _dt.datetime.now())
    except Exception as e:
        print(f"  ⚠️ 目視済スキップ読込失敗(続行): {type(e).__name__}")
        skips = set()
    try:
        import psa_preflight as pf
        con = sqlite3.connect(pf.CATALOG_DB)
    except Exception as e:
        print(f"  ⚠️ preflight 読込失敗 → 前段フィルタ skip: {type(e).__name__}")
        return flags, {}

    # live に同じカードが居るか (出品くんと同じ dup_guard の index を使う)
    live_idx, group_key = None, None
    try:
        import dup_guard as dg
        titles, _skus, fresh = dg.ensure_fresh_live_cache()
        if fresh and titles:
            live_idx, _ = dg.live_card_index(vals, titles, set(titles.keys()))
            group_key = dg.group_key
    except Exception as e:
        print(f"  ⚠️ live 重複の前置き skip (古い cache を根拠にしない): {type(e).__name__}")

    changed = {}
    for i, cert in targets:
        cls = None
        has_image = None
        f = pf.PSA_CERTS_DIR / f"{cert}.json"
        if f.exists():
            try:
                cls = pf.classify(str(cert), json.loads(f.read_text(encoding="utf-8")), con)
            except Exception:
                cls = None
        pid = (cls or {}).get("product_id")
        if pid:
            try:
                row = con.execute("SELECT images FROM products WHERE category=? AND product_id=?",
                                  ((cls or {}).get("category"), pid)).fetchone()
                if row is not None:
                    has_image = len(json.loads(row[0] or "[]")) > 0
            except Exception:
                has_image = None
        live_dup = False
        if pid and live_idx is not None and group_key is not None:
            try:
                live_dup = group_key(f"{cls.get('category')}:{pid}") in live_idx
            except Exception:
                live_dup = False
        new = downgrade_by_preflight(cert, skips, cls, has_image, live_dup)
        if new:
            flags[i] = new
            changed[cert] = new
    con.close()
    return flags, changed


def _col_a1(idx0):
    """0-indexed 列番号 → A1 の列名 (41 → 'AP')。"""
    s, i = "", idx0 + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def setup_conditional_format(ws):
    """B列(itemID)の空セルを「出せない行だけ」グレーにする条件付き書式を張る (冪等)。

    既存の同一 range の rule は消してから張り直す (二重登録を避ける)。
    """
    flag = _col_a1(FLAG_COL)
    rule = {
        "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": B,
                    "endColumnIndex": B + 1}],
        "booleanRule": {
            "condition": {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue":
                            f'=AND($B2="", ${flag}2<>"", ${flag}2<>"{OK}")'}],
            },
            "format": {"backgroundColor": {"red": 0.75, "green": 0.75, "blue": 0.75}},
        },
    }
    ws.spreadsheet.batch_update({"requests": [{"addConditionalFormatRule":
                                              {"rule": rule, "index": 0}}]})
    return f"B列に条件付き書式を追加 (グレー = {flag}列が「{OK}」以外)"


def main():
    do_write = "--write" in sys.argv
    do_format = "--setup-format" in sys.argv
    ws = sheet_io._product_ws()
    vals = ws.get_all_values()

    listed_keys = sheet_io.listed_key_forms(vals)
    listed_certs = sheet_io.listed_certs(vals) | sheet_io.live_listed_certs()
    flags = classify_all(vals, listed_certs, listed_keys, sheet_io.already_listed_reason)
    flags, changed = _preflight_pass(vals, flags)
    if changed:
        print(f"  🔎 前段フィルタで {len(changed)}件を「{OK}」から外した "
              f"(出品くんが枠を選ぶ前に落とす分)")

    counts = {}
    for f in flags[1:]:
        if f:
            counts[f] = counts.get(f, 0) + 1
    print(f"=== 出せるか判定 [{'実書込' if do_write else 'dry-run'}] AP列 ===")
    print(f"シート行数 {len(vals)}")
    for k in sorted(counts, key=lambda x: -counts[x]):
        mark = "🟢" if k == OK else "⬜"
        print(f"  {mark} {k}: {counts[k]}件")
    if not counts.get(OK):
        print("  ⚠️ 出せる行が0件 = 補充が要る (2枚目は何日待っても出品にならない)")

    if do_write:
        col = _col_a1(FLAG_COL)
        ws.update(f"{col}1:{col}{len(flags)}", [[f] for f in flags],
                  value_input_option="RAW")
        print(f"  ✏️ {col}1:{col}{len(flags)} を更新")
    if do_format:
        print("  🎨 " + setup_conditional_format(ws))


if __name__ == "__main__":
    main()
