#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログ整合 定期監査 (read-only, 2026-06-08 新設 = 再発防止 #3)。

「正しい辞書を一度作る → 参照するだけ」を守るための定期点検。新旧含めドリフトを検出。
HQ判断: ABC修正は一度で済むが、新弾取り込み等でズレが入る可能性 → 週次で自動検査し早期発見。

3つの内部検査 (外部データ不要):
  1. name_en 自己整合: 同一 name_jp で name_en が割れてないか (Durant型)。全TCGカテゴリ。
  2. set_code↔set_name_ebay 整合: 1 set_code が複数 set名に割れてないか (Dragonball FB型)。
  3. filter_map yaml↔DB ドリフト: yaml(SSOT) と DB表の値が食い違ってないか (INSERT OR IGNORE 波及)。

exit code: 異常0件=0 / 異常あり=1 (cron/Task Scheduler でアラート判定に使える)。
レポートは iMakHQ/tools/_audit_reports/ に日付付きで保存 (timestampは引数で受ける=再現性)。
"""
import collections
import glob
import json
import os
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"
YAML_DIR = r"C:\dev\iMak\iMakCatalog\ebay_filter_map"
TCG_CATS = ["pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg"]


def check_name_en(con):
    """同一 name_jp で name_en が割れている高信頼 suspect を返す。"""
    out = {}
    for cat in TCG_CATS:
        rows = con.execute(
            "SELECT name_jp,name_en FROM products WHERE category=? "
            "AND name_jp IS NOT NULL AND name_jp<>'' AND name_en IS NOT NULL AND name_en<>''",
            (cat,),
        ).fetchall()
        g = collections.defaultdict(collections.Counter)
        for jp, en in rows:
            g[jp][en] += 1
        high = []
        for jp, by in g.items():
            if len(by) < 2:
                continue
            ranked = by.most_common()
            maj_n = ranked[0][1]
            for en, n in ranked[1:]:
                # 高信頼 = 多数派>=5 かつ 少数派<=2 (表記揺れでなく誤りの疑い)
                if maj_n >= 5 and n <= 2:
                    high.append((jp, ranked[0][0], maj_n, en, n))
        out[cat] = high
    return out


def _valid_ebay_names(con, cat):
    """そのカテゴリの「正規 eBay set 名」集合 = filter_map の ebay_value + verified_manual 値。
    再録/マルチデッキは正規名同士なので除外され、literal/生文字列(Fever-Burst Fighter等)だけ残る。"""
    names = set()
    for (ev,) in con.execute(
        "SELECT DISTINCT ebay_value FROM ebay_filter_map WHERE category=? AND field IN ('set','set_code')",
        (cat,),
    ).fetchall():
        if ev and str(ev).strip():
            names.add(ev.strip())
    # HQ確定の verified_manual も正規とみなす (pokemon の em-dash 値等)
    try:
        for rid, in con.execute(
            "SELECT product_id_ref FROM b_layer_status WHERE category=? AND field='set_name_ebay' AND status='verified_manual'",
            (cat,),
        ).fetchall():
            r = con.execute("SELECT specs FROM products WHERE rowid=?", (rid,)).fetchone()
            if r and r[0]:
                v = json.loads(r[0]).get("set_name_ebay")
                if v and str(v).strip():
                    names.add(v.strip())
    except Exception:
        pass
    return names


def check_set_code(con):
    """set_name_ebay が「正規 eBay 名でない」(=literal/生文字列) ものを検出。
    再録/マルチデッキ(SMM/SMI)/同セット別名は正規名なので出ない。CARDID等の壊れ id は除外。"""
    out = {}
    for cat in TCG_CATS:
        valid = _valid_ebay_names(con, cat)
        rows = con.execute(
            "SELECT product_id,specs FROM products WHERE category=?", (cat,)
        ).fetchall()
        bad = collections.Counter()  # 正規でない set_name_ebay 値 -> 件数
        for pid, sp in rows:
            if (pid or "").upper().startswith("CARDID"):
                continue  # 壊れた product_id は別問題 (取得の穴)
            try:
                v = json.loads(sp).get("set_name_ebay") if sp else None
            except Exception:
                v = None
            v = (v or "").strip()
            if not v:
                continue
            # raw 生文字列の兆候のみフラグ = bracket[XX]/【XX】 or "PACK -"/"DECK -" の囲み形式。
            # 単なる "Booster" 部分一致は正名(Premium Booster等)を誤検出するので使わない。
            looks_raw = ("[" in v or "】" in v or "【" in v
                         or "PACK -" in v.upper() or "DECK -" in v.upper())
            if looks_raw:
                bad[v] += 1
        out[cat] = bad.most_common(30)
    return out


# ★2026-08-02 追加 (検査4・5)。
#   背景: ST-18/ST-26 が **4月から今日まで**「別セットなのに同じ eBay 値」のまま放置された。
#   既存の検査は「表に載っているか」「yaml と DB がズレていないか」しか見ておらず、
#   **載っている値そのものの確からしさを誰も見ていなかった**。
#   ユーザー指摘:「管理物の確からしさは誰がチェックするの」
#   ★`ebay_filter_map` は **①(カタログ)の一部**。map の誤りは①の誤り (1丁目1番地 追記③)。

# 人が「未検証」と自分で書いた印。これが残っている限り、その行は①の正の根拠にできない。
UNVERIFIED_MARKERS = ("REVIEW", "要確認", "推定", "仮")

# 同じ eBay 値に潰れていても**正しい**組 (JA/EN 表記ゆれ・hyphen 変異体など、実体が同一)。
# ここに入れる時は「実体が同一である根拠」をコメントで残すこと。安易に足すと検査が死ぬ。
COLLISION_ALLOW = {
    # 同一セットの JA 表記と EN 表記 / set_code の hyphen 有無。実体が同じなので潰れて正しい。
    ("one_piece_tcg", "set_code", "500 Years in the Future"),
    ("one_piece_tcg", "set_code", "Premium Booster One Piece The Best"),
    ("one_piece_tcg", "set_code", "Adventure on Kami's Island"),
    ("one_piece_tcg", "set_code", "The Azure Sea's Seven Heroes"),
}


def check_unverified_filtermap(con):
    """`note` に未検証の印が残っている変換表の行 (= ①の正の根拠にできない行)。"""
    out = {}
    like = " OR ".join(["note LIKE ?"] * len(UNVERIFIED_MARKERS))
    args = [f"%{m}%" for m in UNVERIFIED_MARKERS]
    rows = con.execute(
        f"SELECT category, field, source_value, ebay_value, note FROM ebay_filter_map "
        f"WHERE {like} ORDER BY category, field, source_value", args).fetchall()
    for cat, field, src, ev, note in rows:
        out.setdefault(cat, []).append((field, src, ev, (note or "")[:60]))
    return out


def check_filtermap_collision(con):
    """複数の公式値が同じ eBay 値に潰れている組 (ST-18/26 と同型)。

    潰れ自体が即誤りとは限らない (JA/EN 表記ゆれは正しい) ので、実体が同一だと
    確認できたものだけ `COLLISION_ALLOW` に入れて除外する。**残りは要検証**。
    """
    rows = con.execute(
        "SELECT category, field, ebay_value, COUNT(*) n, GROUP_CONCAT(source_value) "
        "FROM ebay_filter_map GROUP BY category, field, ebay_value "
        "HAVING n > 1 ORDER BY category, field, n DESC").fetchall()
    out = {}
    for cat, field, ev, n, srcs in rows:
        if (cat, field, ev) in COLLISION_ALLOW:
            continue
        out.setdefault(cat, []).append((field, ev, n, srcs))
    return out


def check_filtermap_drift(con):
    """yaml(SSOT) と DB ebay_filter_map の値ズレ (INSERT OR IGNORE 波及)。"""
    drift = []
    try:
        import yaml as _yaml
    except Exception:
        return [("(PyYAML未導入でskip)", "", "", "")]
    for path in glob.glob(os.path.join(YAML_DIR, "*.yaml")):
        cat = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                doc = _yaml.safe_load(f) or {}
        except Exception as e:
            drift.append((cat, "(yaml読込失敗)", str(e), ""))
            continue
        # yaml 構造: {field: {source_value: ebay_value}} を想定 (柔軟に走査)
        def walk(node, field=None):
            if isinstance(node, dict):
                for k, v in node.items():
                    if isinstance(v, dict):
                        walk(v, k)
                    elif isinstance(v, str):
                        yield (field, k, v)
        for field, sv, ev_yaml in walk(doc):
            row = con.execute(
                "SELECT ebay_value FROM ebay_filter_map WHERE category=? AND field=? AND source_value=?",
                (cat, field, sv),
            ).fetchone()
            if row and row[0] != ev_yaml:
                drift.append((cat, f"{field}/{sv}", ev_yaml, row[0]))
    return drift


def main():
    stamp = sys.argv[1] if len(sys.argv) > 1 else "manual"
    con = sqlite3.connect(DB)
    ne = check_name_en(con)
    sc = check_set_code(con)
    df = check_filtermap_drift(con)
    uv = check_unverified_filtermap(con)
    cl = check_filtermap_collision(con)

    n_ne = sum(len(v) for v in ne.values())
    n_sc = sum(len(v) for v in sc.values())
    n_df = len([d for d in df if not d[0].startswith("(")])
    n_uv = sum(len(v) for v in uv.values())
    n_cl = sum(len(v) for v in cl.values())

    lines = [f"# カタログ整合 定期監査 ({stamp})", ""]
    lines.append(f"## サマリー: name_en割れ={n_ne} / set_code割れ={n_sc} / filter_mapドリフト={n_df}"
                 f" / **未検証map={n_uv}** / **map潰れ={n_cl}**")
    lines.append("")
    lines.append("## 1. name_en 自己整合 (高信頼 suspect)")
    for cat, items in ne.items():
        lines.append(f"### {cat}: {len(items)}件")
        for jp, maj, mn, sus, sn in items[:20]:
            lines.append(f"  - {jp} : 正?{maj}({mn}) 誤?{sus}({sn})")
    lines.append("")
    lines.append("## 2. set_name_ebay が正規eBay名でない (literal/生文字列)")
    for cat, items in sc.items():
        lines.append(f"### {cat}: {len(items)}種")
        for v, n in items[:20]:
            lines.append(f"  - {v!r} : {n}件")
    lines.append("")
    lines.append("## 3. filter_map yaml↔DB ドリフト")
    for cat, key, ev_yaml, ev_db in df[:50]:
        lines.append(f"  - {cat} {key}: yaml={ev_yaml!r} DB={ev_db!r}")

    lines.append("")
    lines.append("## 4. 変換表に未検証の印が残っている行 (①の正の根拠にできない)")
    lines.append("   → 公式を今その場で再取得して検証し、note を根拠に置き換えること")
    for cat, items in uv.items():
        lines.append(f"### {cat}: {len(items)}件")
        for field, src, ev, note in items[:20]:
            lines.append(f"  - {field} {src} -> {ev!r} : {note}")
        if len(items) > 20:
            lines.append(f"  …他{len(items) - 20}件")

    lines.append("")
    lines.append("## 5. 別の公式値が同じ eBay 値に潰れている (ST-18/26 と同型)")
    lines.append("   → 実体が同一なら COLLISION_ALLOW に根拠付きで追加。違うなら①の誤り")
    for cat, items in cl.items():
        lines.append(f"### {cat}: {len(items)}組")
        for field, ev, n, srcs in items[:20]:
            lines.append(f"  - {field} {ev!r} x{n} <- {srcs}")
        if len(items) > 20:
            lines.append(f"  …他{len(items) - 20}組")

    report = "\n".join(lines)
    print(report)

    rdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_audit_reports")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, f"integrity_{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(report)

    anomalies = n_ne + n_sc + n_df + n_uv + n_cl
    print(f"\n=> 異常合計 {anomalies}件 (exit {'1' if anomalies else '0'})")
    sys.exit(1 if anomalies else 0)


if __name__ == "__main__":
    main()
