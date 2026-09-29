# -*- coding: utf-8 -*-
"""共有カタログ DB の「壊れ」と「1ビット化け」を毎朝見つける (2026-09-29 ユーザー確定)。

背景: この PC はメモリまわりの不具合で、書き込み中のデータが1ビット裏返る
(9/23〜9/29 に 29欄 / 9/29 夕方に DB の骨組みまで壊れた / OCCT のメモリ負荷で1分以内に落ちる)。
メモリは当面そのまま・重い負荷をかけない運用で様子見する (ユーザー判断)。その間、
**人が気づく前に機械が見つけて、カタログに戻してもらう**。

やること (毎朝のバックアップ data_backup.py の最後に呼ばれる):
  1. 今の products.sqlite に quick_check (骨組みの壊れ)
  2. 最新と1つ前のバックアップの products.sqlite を行ごとに比べ、**長さが同じで 1〜3 か所が
     各1ビットだけ違う欄** を数える (大文字小文字の違い 0x20 は正当な直しなので数えない)
     ★どちらが化けたかは2本では決まらない。2つ前のバックアップと比べて向きを決める (2026-09-30:
     「前」が化けていて「今」が直った値だった10欄に「前に戻せ」と依頼を出した)。
     2つ前 = 今 → 直った分 (数えない) / 2つ前 = 前 → 今が化けた / どちらでもない → 向き不明
  3. 結果を iMak_data/hq/data_integrity_last.json に書く (神風の状態の1行が読む)
  4. 化け・壊れが1つでもあれば catalog/requests/ に復元の依頼書を置く (同じ日の2通目は置かない)

    python data_integrity_watch.py          # 1回
    python data_integrity_watch.py --hourly # 1時間ごと (予約 iMakHQ_DataIntegrity_Hourly): quick_check だけ
★--hourly (2026-09-30 ユーザー確定): 「いつ壊れたか」を1時間の幅に絞るため。読むだけ (mode=ro)。
  毎回 hourly.jsonl に quick_check / ヘッダの変更カウンタ / -wal の大きさ・時刻 を1行残す
  (変更カウンタが動いていれば、その1時間に誰かが DB ファイルに書いた証拠)。壊れていたら依頼書を置く
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
import tempfile
import zipfile

DB = r"C:\dev\iMak_data\catalog\products.sqlite"
DAILY = r"G:\マイドライブ\iMak_backup\daily"
STATUS = r"C:\dev\iMak_data\hq\data_integrity_last.json"
HOURLY_LOG = r"C:\dev\iMak_data\hq\data_integrity_hourly.jsonl"
REQ_DIR = r"C:\dev\iMak_data\catalog\requests"


def bitflips(old_rows, new_rows, cols):
    """{rowid: 行} ×2 → 1ビット化けの欄のリスト (純関数)。

    同じ行・同じ列で、バイト長が同じ・違う所が1〜3か所・どれも1ビットだけの違い、を化けとみなす。
    大文字小文字 (0x20) は人の直しなので外す。行が無い/長さが違う = 普通の書き換え。
    """
    out = []
    for rid, new in new_rows.items():
        old = old_rows.get(rid)
        if old is None or old == new:
            continue
        for i, (a, b) in enumerate(zip(old, new)):
            if a == b or not isinstance(a, bytes) or not isinstance(b, bytes) or len(a) != len(b):
                continue
            d = [(k, a[k] ^ b[k]) for k in range(len(a)) if a[k] != b[k]]
            if 1 <= len(d) <= 3 and all(bin(v).count("1") == 1 and v != 0x20 for _, v in d):
                k0 = d[0][0]
                out.append({"rowid": rid, "column": cols[i] if i < len(cols) else str(i),
                            "offsets": [k for k, _ in d], "bits": [hex(v) for _, v in d],
                            "was": a[max(0, k0 - 25):k0 + 15].decode("utf-8", "replace"),
                            "now": b[max(0, k0 - 25):k0 + 15].decode("utf-8", "replace")})
    return out


def classify(flips, old_rows, new_rows, refs, cols):
    """それより前のバックアップ群 (refs = [{rowid: 行}, ...] 新しい順) で化けの向きを決める (純関数)。

    どれかに今と同じ値がある → 前が化けていて今は直った → 外す (化けが数日続いてから直る事がある) /
    一番新しい ref が前と同じ → 今が化けた → "now" / それ以外 → "unknown" (カタログに公式と比べてもらう)。
    """
    out = []
    for f in flips:
        ci = cols.index(f["column"])
        rid = f["rowid"]
        vals = [r[rid][ci] for r in refs if rid in r and ci < len(r[rid])]
        if new_rows[rid][ci] in vals:
            continue
        f["broken"] = "now" if vals and vals[0] == old_rows[rid][ci] else "unknown"
        out.append(f)
    return out


def _rows_from_zip(zp, tmp, name, only=None):
    with zipfile.ZipFile(zp) as z:
        n = [x for x in z.namelist() if x.endswith("products.sqlite")][0]
        p = os.path.join(tmp, name)
        with open(p, "wb") as f:
            f.write(z.read(n))
    con = sqlite3.connect(p)
    con.text_factory = bytes
    cols = [r[1].decode() if isinstance(r[1], bytes) else r[1] for r in con.execute("pragma table_info(products)")]
    if only is not None:                                       # 向き判定用: 化けた行だけ読む (メモリを食わない)
        q = ",".join("?" * len(only))
        rows = {r[0]: r[1:] for r in con.execute(f"select rowid,* from products where rowid in ({q})", list(only))}
        con.close()
        return rows, cols, {}
    rows = {r[0]: r[1:] for r in con.execute("select rowid,* from products")}
    ident = {r[0]: (r[1].decode("utf-8", "replace") if isinstance(r[1], bytes) else r[1],
                    r[2].decode("utf-8", "replace") if isinstance(r[2], bytes) else r[2])
             for r in con.execute("select rowid, category, product_id from products")}
    con.close()
    return rows, cols, ident


def quick_check(path=DB):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        r = con.execute("pragma quick_check").fetchone()[0]
        con.close()
        return r
    except Exception as e:                                     # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def _write_request(st):
    today = datetime.date.today().isoformat()
    # 同じ中身の2通目は置かない。中身が違えば _2, _3 … で置く
    # (2026-09-30: 朝の1通を閉じた後に DB の骨組みが壊れたが、同じ日の名前が在るので黙っていた)
    sig = f"quick_check={st['quick_check']!r} flips={sorted((f['rowid'], f['column']) for f in st['flips'])!r}"
    for n in range(1, 20):
        stem = f"{today}_catalog_integrity_auto" + (f"_{n}" if n > 1 else "")
        path = os.path.join(REQ_DIR, stem + ".md")
        seen = [q for q in (path, path.replace(".md", "_processed.md")) if os.path.exists(q)]
        if not seen:
            break
        if any(sig in open(q, encoding="utf-8").read() for q in seen):
            return ""
    else:
        return ""
    lines = [f"# 自動検出: カタログ DB の化け・壊れ ({today})", "",
             f"- 依頼日: {today} / 依頼者: HQ (data_integrity_watch.py が自動で出した) / 緊急度: 高 / フェーズ: 実装 (復元)",
             "- 種別: PC のメモリまわりの不具合による化け。値の判断ではなく、化ける前の値への復元", "",
             "## 既に判明していること (再調査するな)", "",
             f"- quick_check: {st['quick_check']}",
             f"- 見張りの印 (同じ中身の2通目を出さない用): `{sig}`",
             f"- 比べたバックアップ: {os.path.basename(st['pair'][0])} → {os.path.basename(st['pair'][1])}",
             f"- それより前のバックアップ {len(st.get('refs', []))}本と比べて向きを決めた。前のどれかに今の値があれば"
             "「直った分」として外してある。「今が化けた」= 2つ前と前が同じで今だけ違う / 「向き不明」= それ以外",
             f"- 1ビット化け {len(st['flips'])}欄 (rowid / category / product_id / 列 / バイト位置 / 前 → 今 / 判定):"]
    for f in st["flips"][:200]:
        lines.append(f"  - {f['rowid']} / {f.get('category','')} / {f.get('product_id','')} / {f['column']} / "
                     f"{f['offsets']} / {f['was']!r} → {f['now']!r} / "
                     + ("今が化けた" if f.get("broken") == "now" else "向き不明"))
    lines += ["", "## やってほしいこと", "",
              "1. 「今が化けた」欄は、前のバックアップ (1つ目の zip) の同じ行・同じ列の値に戻す (バイト位置で合わせる)。"
              "「向き不明」欄は公式の値と比べて、化けている方を直す",
              "2. quick_check が ok でなければ DB を作り直す",
              "3. 回答は同じ名前 + _response.md に「戻した件数 / 残り0件 / integrity_check」"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def run():
    st = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "ok": False,
          "quick_check": quick_check(), "flips": [], "pair": [], "request": ""}
    try:
        zs = sorted(os.path.join(DAILY, x) for x in os.listdir(DAILY) if x.endswith(".zip"))
        if len(zs) >= 2:
            st["pair"] = zs[-2:]
            st["refs"] = [os.path.basename(z) for z in zs[-3::-1]]
            with tempfile.TemporaryDirectory() as tmp:
                old, cols, _ = _rows_from_zip(zs[-2], tmp, "a.sqlite")
                new, _, ident = _rows_from_zip(zs[-1], tmp, "b.sqlite")
                fl = bitflips(old, new, cols)
                ids = {f["rowid"] for f in fl}
                refs = [_rows_from_zip(z, tmp, f"r{i}.sqlite", ids)[0]
                        for i, z in enumerate(zs[-3::-1])] if ids else []
            fl = classify(fl, old, new, refs, cols)
            for f in fl:
                f["category"], f["product_id"] = ident.get(f["rowid"], ("", ""))
            st["flips"] = fl
        st["ok"] = st["quick_check"] == "ok" and not st["flips"]
        if not st["ok"]:
            st["request"] = _write_request(st)
    except Exception as e:                                     # noqa: BLE001 見張り自体の失敗も知らせる
        st["error"] = f"{type(e).__name__}: {e}"
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    msg = ("✅ 化けなし・DB 正常" if st["ok"] else
           f"⚠️要対応 化け {len(st['flips'])}欄 / DB {st['quick_check']}" + (f" → 依頼書 {st['request']}" if st["request"] else ""))
    print(f"データの見張り: {msg}" + (f" (見張りの失敗: {st['error']})" if st.get("error") else ""))
    return st


def file_marks(path=DB):
    """DB ファイルの「書かれた印」: ヘッダの変更カウンタ (24〜27バイト目) / 本体と -wal の大きさ・更新時刻。"""
    m = {}
    try:
        with open(path, "rb") as f:
            m["change_counter"] = int.from_bytes(f.read(28)[24:28], "big")
    except Exception as e:                                     # noqa: BLE001
        m["change_counter"] = f"{type(e).__name__}"
    for k, q in (("db", path), ("wal", path + "-wal")):
        try:
            st = os.stat(q)
            m[k] = [st.st_size, datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")]
        except OSError:
            m[k] = None
    return m


def run_hourly():
    st = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "quick_check": quick_check(),
          **file_marks(), "request": ""}
    if st["quick_check"] != "ok":
        st["request"] = _write_request({"quick_check": st["quick_check"], "flips": [], "pair": ["(1時間ごとの検査)", ""]})
    with open(HOURLY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(st, ensure_ascii=False) + "\n")
    print(f"データの見張り(1時間): quick_check={st['quick_check'][:60]} 変更カウンタ={st['change_counter']}"
          + (f" → 依頼書 {st['request']}" if st["request"] else ""))
    return st


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    if "--hourly" in sys.argv:
        sys.exit(0 if run_hourly()["quick_check"] == "ok" else 1)
    sys.exit(0 if run().get("ok") else 1)
