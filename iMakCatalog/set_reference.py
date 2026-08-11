# -*- coding: utf-8 -*-
"""Catalog-side helper for set-name integrity references (2026-08-11).

HQ-side consumers (check_csv, csv_auditor 等) がカタログの set_name_ebay に関する
整合ゲートを回す時の**公式インターフェース**。契約 v1.2 (2026-08-10 co-sign)
「カタログの interface は `specs["set_name_ebay"]` を維持」に従い、HQ 側は本 helper
経由でしかカタログの整合情報を取らない (catalog 境界を明確にする)。

公開 API (SSOT はここ):
  - set_total_reference(db=None) -> dict[str, str]
      {set_name_ebay: 主流 card_number_total}。1 セット=1 total が原則で、
      複数 total 混在 (誤マップ) は最多を「正」として返す。
  - row_set_issue(set_name, card_number, ref) -> str | None
      CSV 1 行の Set ↔ カード番号 total 整合。矛盾なら理由文字列、OK/判定不能は None。
  - eb_era(set_name) / ERA_YEARS
      世代 × Year 整合チェック用 (Pokemon set 名の世代 prefix と発売年レンジ)。
  - card_total(card_number)
      "097/080" → "080" (分母抽出、先頭 0 保持)。
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

_DB_PATH = Path(r"C:/dev/iMak_data/catalog/products.sqlite")

# set_name_ebay の世代プレフィックス → 妥当な発売年レンジ
ERA_YEARS = {
    "Black & White": (2011, 2014),
    "XY": (2013, 2017),
    "Sun & Moon": (2017, 2020),
    "Sword & Shield": (2019, 2023),
    "Scarlet & Violet": (2022, 2026),
}

# 同一 set に複数 total が混在しても正当なホワイトリスト (公式 EN 同名の別 JP セット等)。
# ここに載っている set は total 照合で誤ブロックしない。
_KNOWN_MULTI_TOTAL_OK = {
    # 拡張パック「サン＆ムーン」(SM1p /051) と コレクションサン/ムーン (SM1S/SM1M /060) が
    # 公式 EN 同名 "Sun & Moon" 別 total で正当 (異なる JP セットだが英語名同一)。2026-06-07 HQ 確認。
    "Sun & Moon",
}


def _is_excluded_pid(pid: str) -> bool:
    """整合対象外の不正 product_id (cardID-prefix 系は別案件)。"""
    return (pid or "").startswith("cardID")


def eb_era(eb: str) -> str:
    """set_name_ebay → 世代 (prefix から)。"""
    for era in ("Black & White", "XY", "Sun & Moon", "Sword & Shield", "Scarlet & Violet"):
        if (eb or "").startswith(era):
            return era
    return "bare/other"


def card_total(card_number) -> str:
    """'097/080' → '080' (分母=セット総数、先頭 0 保持で catalog 値と一致)。取れなければ ''。"""
    m = re.search(r"/\s*(\d+)", str(card_number or ""))
    return m.group(1) if m else ""


def set_total_reference(db: Optional[str] = None) -> dict:
    """{set_name_ebay: 主流(最多) card_number_total} を返す。出品時の整合チェック用参照。

    1 セット=1 total が原則なので、最多 total を「正」とする。check_csv が CSV 各行の
    C:Set ↔ カード番号 total を照合して矛盾 (誤マップ) を出品前に弾くのに使う。
    """
    path = db or str(_DB_PATH)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        tots: dict = collections.defaultdict(collections.Counter)
        for r in con.execute("SELECT specs FROM products WHERE category='pokemon_tcg'"):
            try:
                sp = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                continue
            eb = sp.get("set_name_ebay", "")
            t = str(sp.get("card_number_total", "")).strip()
            if eb and t:
                tots[eb][t] += 1
        return {eb: c.most_common(1)[0][0] for eb, c in tots.items()}
    finally:
        con.close()


def row_set_issue(set_name: str, card_number: str, ref: dict) -> Optional[str]:
    """CSV 1 行の C:Set ↔ カード番号 total 整合チェック。矛盾なら理由文字列、OK/判定不能は None。

    ref = set_total_reference()。set が参照に無い / 番号取れない場合は判定不能で None
    (fail-closed は呼出側で「不明は skip」運用)。verified-legit な多 total セット
    (異なる JP セットの公式 EN 同名等) は total 照合しない (誤ブロック回避)。
    """
    set_name = (set_name or "").strip()
    t = card_total(card_number)
    if not set_name or not t or set_name not in ref:
        return None
    if set_name in _KNOWN_MULTI_TOTAL_OK:
        return None
    exp = ref[set_name]
    if t != exp:
        return (f"Set↔カード番号 不整合: Set='{set_name}'(総数/{exp}) なのに カード/{t} "
                f"→ set_name_ebay 誤マップ疑い (catalog要確認)")
    return None


# ============================================================================
# 契約 v1.2 §4: 「183454 master に無い値が CSV に出ていない」CI 用 helper
# ============================================================================
def pokemon_set_master(db: Optional[str] = None) -> set:
    """category 183454 (Pokemon TCG) の master set_name_ebay 集合を返す。

    CI が「CSV の C:Set 値が master に無い = 生成側の脱線」を検出するために使う。
    空文字列は除外 (master に無いのと同義)。
    """
    path = db or str(_DB_PATH)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        out = set()
        for r in con.execute("SELECT specs FROM products WHERE category='pokemon_tcg'"):
            try:
                sp = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                continue
            eb = (sp.get("set_name_ebay") or "").strip()
            if eb:
                out.add(eb)
        return out
    finally:
        con.close()


__all__ = [
    "ERA_YEARS",
    "card_total",
    "eb_era",
    "pokemon_set_master",
    "row_set_issue",
    "set_total_reference",
]
