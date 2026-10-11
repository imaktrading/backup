"""supply_guard - 仕入元の「中身」の急変を見張る (2026-10-09 HQ 実装 GO、ブラボー B-20261009-014).

実害 (2026-10-09): シャワーズ (820133532757) の補URL (メルカリ Shops) の商品名が
「(PSA10)」→「(PSA7)」に書き換わり、巡回はその ¥4,830 を仕入値に採って赤字で 2 件売れた。
メルカリ Shops は同じ URL で在庫 (カード・鑑定) を入れ替えて売り続けられる =
**同じ URL でも中身が変わる前提**で見る。読み取りは増やさない (既に読んでいる商品名・値段だけ使う)。

  1. 鑑定 : 行の商品が PSA10 なのに、仕入元の商品名が PSA10 でない → 売切と同じ扱い
  2. 名前 : 初めて見た時の商品名から、カード番号か鑑定の数字が消えた・変わった → 売切と同じ扱い + 目視
  3. 値段 : 前回の M 列より 4 割以上安い (M が無い行は ほかの在庫あり仕入元の中央値より) → M を前回のまま据え置く + 目視
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
STREAK_PATH = DECISION_LOG_DIR / "supply_price_streak.json"

PRICE_DROP_RATIO = 0.6          # 基準の 60% 未満 (= 4 割以上安い) で外す
PRICE_STREAK_ADOPT = 2          # 同じ値段帯の急落が この回数続いたら M に採る (2026-10-12 ブラボー GO B-20261012-001)
PRICE_STREAK_BAND = 0.10        # 「同じ値段帯」= 前回の急落値の ±10%

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
    """急落なら理由。基準が無い / 問題なし → "".

    前回 M がある行は **前回 M との比較だけ** (今までの値段から急に落ちた = 新しい異常)。
    ほかの仕入元の中央値と比べるのは 前回 M が無い時だけ。
    ★ 10/09 初回の巡回: 中央値で比べると、PSA は仕入元ごとの値幅が大きく、既に M になっている
      正しい安値 (例 ¥10,999 vs 中央値 ¥35,000) を 180 行で 8 件拾った。拾うと M が据え置かれ、
      その安値が上がっても M が追いつかない (= eBay で安売りの危険) ので、既に採っている値段は見ない。
    """
    if not isinstance(price, int) or price <= 0:
        return ""
    if isinstance(prev_m, int) and prev_m > 0:
        if price < prev_m * PRICE_DROP_RATIO:
            return f"前回の仕入値 ¥{prev_m:,} より 4 割以上安い ¥{price:,}"
        return ""
    if other_prices:
        med = statistics.median(other_prices)
        if price < med * PRICE_DROP_RATIO:
            return f"ほかの仕入元 (中央値 ¥{int(med):,}) より 4 割以上安い ¥{price:,}"
    return ""


class PriceStreak:
    """URL → 急落と出た値段と、続けて出た回数。2 回続けて同じ値段帯なら M に採る.

    ★ 2026-10-12 (B-20261012-001): 急落で M を据え置くと、目視する人がいないので M が古い高値のまま凍った
      (3 日で 16 行。例 ハンコック M ¥38,999 のまま、仕入元は相場に近い ¥13,000)。シャワーズ型の入替え直後は
      1 回目で止まり、続けて同じ値段が出る正しい安値だけ採れる (復活の 2 回確認と同じ考え)。
    """

    def __init__(self, path: Path = STREAK_PATH):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.touched: dict = {}

    def bump(self, url: str, price: int) -> int:
        """急落と出た。同じ値段帯が続いていれば回数 +1、違えば 1 からやり直し。今の回数を返す."""
        prev = self.data.get(url) or {}
        p0 = prev.get("price")
        same = isinstance(p0, int) and p0 > 0 and abs(price - p0) <= p0 * PRICE_STREAK_BAND
        ent = {"price": price, "count": (prev.get("count", 0) + 1) if same else 1,
               "ts": datetime.now().isoformat(timespec="seconds")}
        self.data[url] = ent
        self.touched[url] = ent
        return ent["count"]

    def clear(self, url: str) -> None:
        if url in self.data:
            self.data.pop(url, None)
            self.touched[url] = None

    def save(self) -> None:
        if not self.touched:
            return
        try:
            cur = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = {}
        for k, v in self.touched.items():          # 自分が触った URL だけ上書き (ほかの巡回の分は残す)
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        self.touched = {}


_STREAK: Optional[PriceStreak] = None


def streak() -> PriceStreak:
    global _STREAK
    if _STREAK is None:
        _STREAK = PriceStreak()
        atexit.register(_STREAK.save)
    return _STREAK


def parse_jpy(s) -> Optional[int]:
    try:
        v = int(str(s).replace(",", "").replace("¥", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# ── 集計 + 目視の控え ────────────────────────────────────────────────────
COUNTS = {"read": 0, "grade": 0, "name": 0, "price": 0, "price_adopted": 0}
_REVIEWED_THIS_RUN: set = set()
_READ_URLS: set = set()


def count_read(url: str) -> None:
    """商品名を読んだ仕入元の本数 (同じ URL の読み直しは 1 本)."""
    if url not in _READ_URLS:
        _READ_URLS.add(url)
        COUNTS["read"] += 1


_ALREADY_LOGGED: Optional[set] = None


def _already_logged() -> set:
    """前の巡回までに目視の控えに載せた (種類, 行)。二度見せないため、同じ行・同じ種類は載せ直さない.

    ★ 2026-10-12: 旧版は理由の文 (値段入り) で見ていたので、値段が少し動くたびに同じ行が載り直った (16 行で 58 件)。
    行は itemID で見る (行番号は行の削除でずれる)。
    """
    global _ALREADY_LOGGED
    if _ALREADY_LOGGED is None:
        _ALREADY_LOGGED = set()
        try:
            for line in REVIEW_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    _ALREADY_LOGGED.add((d.get("kind"), _row_key(d)))
                except ValueError:
                    continue
        except OSError:
            pass
    return _ALREADY_LOGGED


def _row_key(d: dict) -> str:
    return str(d.get("item_id") or "").strip() or f"row{d.get('row_index')}"


def record_review(kind: str, url: str, row: dict, reason: str, name: str = "", price=None) -> None:
    """目視に回す物を控える。件数は毎回数える (今の状態) が、控えのファイルには初めての物だけ足す."""
    key = (kind, url)
    if key in _REVIEWED_THIS_RUN:
        return
    _REVIEWED_THIS_RUN.add(key)
    COUNTS[kind] += 1
    seen = _already_logged()
    if (kind, _row_key(row)) in seen:
        return
    seen.add((kind, _row_key(row)))
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
            f"値段が急落: {COUNTS['price']}本 (商品名を読んだ {COUNTS['read']}本のうち)"
            f" / 急落を2回続けて採った {COUNTS['price_adopted']}本 / 据え置き {COUNTS['price']}本")
