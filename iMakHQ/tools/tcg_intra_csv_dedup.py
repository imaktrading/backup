# -*- coding: utf-8 -*-
"""生成後CSV内の「同じカード(同一design)」重複を1枚に間引く(2026-06-21)。

重複くん(dedupe_excluder)は「既に出品済のカード」としか照合せず、**同一CSV内**の同design
複数コピー(別cert)を互いに間引かない。orphan掃除で同designの全コピーがブロック解除されると、
一度に複数枚が同じCSVに入り両方出品される(= per-card KEY dedup が CSV内で効かない。
2026-06-21 ユーザー指摘「カード毎にKEYを設けて重複チェックしている意味がない」)。

このツールは CSV内で design key = (C:Game, C:Set, C:Card Number) が同一の行を1枚に絞る
(先頭を残し以降を物理除外)。重複くん本体(別worktree)は触らず、HQ post-chain の
「物理除外の後・KEY書込の前」に挟む(= 間引いた分の cert は write-keys 対象外 → orphan も出ない)。

dup_row_indices は純関数(test可)。I/O(CSV読み書き)は dedup_csv。
"""
import csv
import os
import sys


def _design_key(row, header):
    """row の design key = (game, set, card_number) を小文字で。純関数。"""
    def g(name):
        i = header.index(name) if name in header else -1
        return (row[i].strip().lower() if 0 <= i < len(row) else "")
    return (g("C:Game"), g("C:Set"), g("C:Card Number"))


def _title_key(row, header):
    """row の完全一致タイトル(小文字)を identity に。純関数。空なら ''。"""
    i = header.index("*Title") if "*Title" in header else -1
    return (row[i].strip().lower() if 0 <= i < len(row) else "")


CSV_CERT = "CDA:Certification Number - (ID: 27503)"


def _pid_of(row, header, pid_by_cert):
    """生成器が確定した canonical product_id (sidecar の by_cert)。無ければ ''。純関数。"""
    if not pid_by_cert or CSV_CERT not in header:
        return ""
    i = header.index(CSV_CERT)
    cert = row[i].strip() if i < len(row) else ""
    return pid_by_cert.get(cert, "") if cert else ""


def load_pid_by_cert(csv_path):
    """`<csv名>.canonical.json` の by_cert を読む (I/O・無ければ空)。"""
    import json
    side = os.path.splitext(csv_path)[0] + ".canonical.json"
    try:
        with open(side, encoding="utf-8") as f:
            return json.load(f).get("by_cert") or {}
    except (OSError, ValueError):
        return {}


def dup_row_indices(body, header, pid_by_cert=None):
    """同一 design key の 2件目以降の body index(0-based)を返す。純関数。

    ★2026-09-26: **生成器が確定した product_id があればそれで同定する** (最優先)。
      (Game, Set, 番号) だと、クラシックの フシギダネ デッキ (CLF-001) と カメックス デッキ
      (CLK-001) が同じ「Pokemon Card Game Classic / 001/032」になり、別カードを間引いて
      正しい出品を1件失った (2026-09-23 cert 158998557)。PID が無い行だけ従来の key に落とす。

    design key = (game, set, card_number)。構成要素に空がある行(catalog gap で C:Set 空等)は
    **完全一致タイトルにフォールバック**して同定する。card number 自体に set コードが含まれ、
    identical title = 同一 listing 確定なので Set 空でも安全に間引ける。別カードは title が違うため
    誤除外しない。design key も title も空なら同定不能 → 残す(fail-closed)。
    (2026-07-01: Set 空で design key が同定放棄され identical 2枚が素通りした事故の恒久対策。
     従来は `if "" in key: continue` で丸ごとスキップしていた)。
    """
    seen, drop = set(), set()
    for i, row in enumerate(body):
        pid = _pid_of(row, header, pid_by_cert)
        key = ("__pid__", pid) if pid else _design_key(row, header)
        if "" in key:
            t = _title_key(row, header)
            if not t:
                continue  # design key も title も無い → 同定不能、残す
            key = ("__title__", t)
        if key in seen:
            drop.add(i)
        else:
            seen.add(key)
    return drop


def dedup_csv(csv_path, execute=False):
    """CSV内の同design重複を1枚に間引く(I/O)。戻り: stats dict。"""
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return {"total": 0, "removed": 0, "executed": execute}
    header, body = rows[0], rows[1:]
    drop = dup_row_indices(body, header, load_pid_by_cert(csv_path))
    ti = header.index("*Title") if "*Title" in header else 0

    print(f"CSV内 同design重複(同じカードの2枚目以降): {len(drop)} 件")
    for i in sorted(drop):
        print(f"  ✂ 間引き: {body[i][ti][:58]}")

    if not execute:
        print("[DRY-RUN] 間引きなし。--execute で物理除外。")
        return {"total": len(body), "removed": len(drop), "executed": False}

    if drop:
        try:
            import shutil
            shutil.copyfile(csv_path, csv_path + ".bak_intradedup")
        except Exception:
            pass
        kept = [header] + [r for i, r in enumerate(body) if i not in drop]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f, quoting=csv.QUOTE_NONNUMERIC).writerows(kept)
        print(f"✅ {len(drop)} 件間引き → 同designは1枚のみ出品(残 {len(kept) - 1} 行)")
    return {"total": len(body), "removed": len(drop), "executed": True}


def main():
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="CSV内の同design重複を1枚に間引く")
    ap.add_argument("csv", help="対象 CSV")
    ap.add_argument("--execute", action="store_true", help="実除外(既定は dry-run)")
    a = ap.parse_args()
    dedup_csv(a.csv, execute=a.execute)


if __name__ == "__main__":
    main()
