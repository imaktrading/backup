"""supply_guard - 仕入元の「中身」の急変を見張る (2026-10-09 HQ 実装 GO、ブラボー B-20261009-014).

実害 (2026-10-09): シャワーズ (820133532757) の補URL (メルカリ Shops) の商品名が
「(PSA10)」→「(PSA7)」に書き換わり、巡回はその ¥4,830 を仕入値に採って赤字で 2 件売れた。
メルカリ Shops は同じ URL で在庫 (カード・鑑定) を入れ替えて売り続けられる =
**同じ URL でも中身が変わる前提**で見る。読み取りは増やさない (既に読んでいる商品名・値段だけ使う)。

  1. 鑑定 : 行の商品が PSA10 なのに、仕入元の商品名が PSA10 でない → 売切と同じ扱い
  2. 名前 : 初めて見た時の商品名から、カード番号か鑑定の数字が消えた・変わった → 売切と同じ扱い + 目視
  3. 値段 : 同じ行のほかの在庫あり仕入元 (中央値) か 前回の M 列 より 4 割以上安い → M を前回のまま据え置く + 目視
            (在庫ありのまま = 取下げはしない。安値も、ほかの仕入元の高値も採らない)

1・2 を「売切と同じ扱い」にするのは「取下げ漏れ > 過剰取下げ」の原則 (中身の違う物を在庫ありと数えると、
売れてから仕入れられない)。補URL なら既存の補URL消込 (2 回目も売切で外す) に乗り、仕入元なら取下げに乗る。
"""
from __future__ import annotations

import atexit
import json
import os
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
BASELINE_PATH = DECISION_LOG_DIR / "supply_name_baseline.json"
REVIEW_PATH = DECISION_LOG_DIR / "supply_guard_review.jsonl"

PRICE_DROP_RATIO = 0.6          # 基準の 60% 未満 (= 4 割以上安い) で外す

# ── 1. 鑑定 ──────────────────────────────────────────────────────────────
# HQ iMakHQ/tools/mercari_psa_resource.is_psa10 と同じ判定 (LAPTOP の巡回は HQ を import しない流儀のため写し)。
_OTHER_GRADER_RE = re.compile(r"(?<![A-Z])(CGC|SGC|AGS|HGA|BGS|ARS|BVG|GMA|PCG)(?![A-Z])")


def is_psa10(name: str) -> bool:
    name = name or ""
    n = name.replace(" ", "").upper()
    if any(b in n for b in ("PSA9", "PSA8", "PSA7")):
        return False
    if _OTHER_GRADER_RE.search(name.upper()):
        return False
    if "相当" in name:
        return False
    return "PSA10" in n


def grade_problem(row_title: str, supply_name: str) -> str:
    """行が PSA10 の商品なのに 仕入元の商品名が PSA10 でない → 理由文字列。問題なし / 判定しない → ""."""
    if not supply_name or supply_name == "(deleted)":
        return ""
    if not is_psa10(_nfkc(row_title)):
        return ""
    if is_psa10(_nfkc(supply_name)):
        return ""
    return "商品名が PSA10 でない"


# ── 2. 名前の変化 ────────────────────────────────────────────────────────
_CARD_SLASH_RE = re.compile(r"(?<![0-9])(\d{1,3})\s*/\s*(\d{1,3})(?![0-9])")
_CARD_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{1,5}\d{0,3}[A-Z]?)-([A-Z]{0,2}\d{2,3})(?![0-9])")
_GRADE_RE = re.compile(r"(PSA|BGS|CGC|ARS|SGC)\s*(\d{1,2}(?:\.5)?)(?![0-9])")


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def name_keys(name: str) -> tuple:
    """商品名 → (カード番号の集合, 鑑定の集合)。'031/087' と '31/87' は同じに数える."""
    u = _nfkc(name).upper()
    cards = {f"{int(a)}/{int(b)}" for a, b in _CARD_SLASH_RE.findall(u)}
    cards |= {f"{a}-{b}" for a, b in _CARD_CODE_RE.findall(u)}
    grades = {f"{g}{v}" for g, v in _GRADE_RE.findall(u)}
    return cards, grades


def name_change(base_name: str, now_name: str) -> str:
    """控えの名前から カード番号 か 鑑定 が消えた・変わった → 理由。変わっていない / 比べられない → ""."""
    if not base_name or not now_name or now_name == "(deleted)":
        return ""
    bc, bg = name_keys(base_name)
    nc, ng = name_keys(now_name)
    if bc and not (bc & nc):
        return f"カード番号が変わった ({'/'.join(sorted(bc))} → {'/'.join(sorted(nc)) or 'なし'})"
    if bg and bg != ng:
        return f"鑑定が変わった ({'/'.join(sorted(bg))} → {'/'.join(sorted(ng)) or 'なし'})"
    return ""


class NameBaseline:
    """URL → 初めて見た時の商品名。複数の巡回 (SHEET/LOW/CAND) が同時に書くので、保存時に読み直して足す."""

    def __init__(self, path: Path = BASELINE_PATH):
        self.path = Path(path)
        self.data: dict = {}
        self.new: dict = {}
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def check(self, url: str, name: str) -> str:
        """控えと比べる。控えが無ければ今の名前を控える (変化なし扱い)."""
        if not url or not name or name == "(deleted)":
            return ""
        base = (self.data.get(url) or {}).get("name")
        if base is None:
            ent = {"name": name, "first_seen": datetime.now().isoformat(timespec="seconds")}
            self.data[url] = ent
            self.new[url] = ent
            if len(self.new) >= 50:
                self.save()
            return ""
        return name_change(base, name)

    def save(self) -> None:
        if not self.new:
            return
        try:
            cur = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = {}
        for k, v in self.new.items():
            cur.setdefault(k, v)            # 先に控えた方 (= 初めて見た名前) を残す
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        self.data.update(cur)
        self.new = {}


_BASELINE: Optional[NameBaseline] = None


def baseline() -> NameBaseline:
    global _BASELINE
    if _BASELINE is None:
        _BASELINE = NameBaseline()
        atexit.register(_BASELINE.save)
    return _BASELINE


# ── 3. 値段の急落 ────────────────────────────────────────────────────────
def price_drop(price: int, other_prices: list, prev_m: Optional[int]) -> str:
    """ほかの在庫あり仕入元の中央値 か 前回 M の 60% 未満なら理由。基準が無い / 問題なし → ""."""
    if not isinstance(price, int) or price <= 0:
        return ""
    if other_prices:
        med = statistics.median(other_prices)
        if price < med * PRICE_DROP_RATIO:
            return f"ほかの仕入元 (中央値 ¥{int(med):,}) より 4 割以上安い ¥{price:,}"
    if isinstance(prev_m, int) and prev_m > 0 and price < prev_m * PRICE_DROP_RATIO:
        return f"前回の仕入値 ¥{prev_m:,} より 4 割以上安い ¥{price:,}"
    return ""


def parse_jpy(s) -> Optional[int]:
    try:
        v = int(str(s).replace(",", "").replace("¥", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# ── 集計 + 目視の控え ────────────────────────────────────────────────────
COUNTS = {"read": 0, "grade": 0, "name": 0, "price": 0}
_REVIEWED_THIS_RUN: set = set()
_READ_URLS: set = set()


def count_read(url: str) -> None:
    """商品名を読んだ仕入元の本数 (同じ URL の読み直しは 1 本)."""
    if url not in _READ_URLS:
        _READ_URLS.add(url)
        COUNTS["read"] += 1


_ALREADY_LOGGED: Optional[set] = None


def _already_logged() -> set:
    """前の巡回までに目視の控えに載せた (kind, url, reason)。二度見せないため、載せ直さない."""
    global _ALREADY_LOGGED
    if _ALREADY_LOGGED is None:
        _ALREADY_LOGGED = set()
        try:
            for line in REVIEW_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    _ALREADY_LOGGED.add((d.get("kind"), d.get("url"), d.get("reason")))
                except ValueError:
                    continue
        except OSError:
            pass
    return _ALREADY_LOGGED


def record_review(kind: str, url: str, row: dict, reason: str, name: str = "", price=None) -> None:
    """目視に回す物を控える。件数は毎回数える (今の状態) が、控えのファイルには初めての物だけ足す."""
    key = (kind, url)
    if key in _REVIEWED_THIS_RUN:
        return
    _REVIEWED_THIS_RUN.add(key)
    COUNTS[kind] += 1
    seen = _already_logged()
    if (kind, url, reason) in seen:
        return
    seen.add((kind, url, reason))
    ent = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, "reason": reason,
           "row_index": row.get("row_index"), "item_id": row.get("item_id"),
           "title": (row.get("title") or "")[:80], "url": url, "supply_name": name[:120],
           "price_jpy": price}
    try:
        with REVIEW_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    except OSError:
        pass


def summary_line() -> str:
    return (f"🏷 商品名が PSA10 でない仕入元: {COUNTS['grade']}本 / 名前が変わった: {COUNTS['name']}本 / "
            f"値段が急落: {COUNTS['price']}本 (商品名を読んだ {COUNTS['read']}本のうち)")
