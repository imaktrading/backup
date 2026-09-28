# -*- coding: utf-8 -*-
"""PSA のラベルとカタログの行が「同じ刷り」かを見る (2026-09-28)。

なぜ要るか:
    9/27〜9/28 の自動出品で 8件が PSA ラベルと違う刷りで出た (全部 手で Revise した)。
      - PRB01 のスラブ → OP05-119 (OP-05 の通常版) の行
      - ALTERNATE ART / WANTED のスラブ → Features の無い通常行
      - MASTER BALL (ミラー) のスラブ → 通常の Uncommon の行
    どれも PSA ラベルに **セット記号** と **刷りの印** が書いてあるのに、
    行を決める所がそれを見ていなかった。目視の答えを覚える所 (psa_label_learned) も
    間違った答えをそのまま覚え、翌日も同じ行で出した。

見るもの (PSA ラベル = 現物に付いた唯一の外の事実):
    1. セット記号 (ワンピのみ): Brand の OP09 / PRB01 / EB04 / ST22 …
       → 行のセット (set_name / set_name_official / get_info) に同じ記号が在ること
    2. 刷りの印 (ワンピのみ): Subject の ALTERNATE ART / WANTED / PARALLEL / SP …
       → 印が在れば行も別絵柄 (variant_type=alt_art 等 or Features=Alternative Art)
       → 印が無ければ行は別絵柄でないこと
    3. ミラー (ポケモン): Subject の MASTER BALL / POKE BALL
       → カタログにミラーの行は無いので、通常の行に当てない

使い方:
    conflict(category, brand, subject, row) → 合わない理由 (合えば "")
    pick(category, brand, subject, card_number, current_pid) → (使う product_id, 理由)
        current_pid が合えばそのまま。合わなければ 同じ番号の行から合う物を探し、
        **1つに絞れた時だけ** それを返す。絞れなければ ("", 理由) = 出品しない。
"""
from __future__ import annotations

import json
import re
import sqlite3

CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"

_OP_SET_RE = re.compile(r"\b(OP|ST|EB|PRB)-?(\d{2})\b")
_ALT_WORDS = ("ALTERNATE ART", "ALT.ART", "ALT. ART", "ALT ART", "PARALLEL", "WANTED",
              "MANGA", "SPECIAL CARD", "-SP", " SP CARD")
# SP カード (WANTED 手配書柄など)。ALTERNATE ART だけのスラブは SP ではない
_SP_WORDS = ("WANTED", "SPECIAL CARD", "SPECIAL ALTERNATE", "SPECIAL ALT", "-SP", " SP CARD")
_ALT_PID_RE = re.compile(r"_(p\d*|SP)(_|$)")  # 小文字 p=パラレル / 大文字 P=プロモ (別物)
# 大会賞品・プロモ。PSA の Brand は元のセット (例 STARTER DECK ST01) でも、現物はプロモ行
# (例 ST01-007_P_win = STANDARD BATTLE WINNER)。セット記号で見ると正しい行を外してしまう
_PROMO_WORDS = ("WINNER", "PROMO", "FLAGSHIP", "CHAMPIONSHIP", "TOURNAMENT", "BATTLE", "EVENT",
                "PRIZE", "JUMP", "CAMPAIGN", "GIFT", "PRE-RELEASE", "PRERELEASE", "FINALIST")
_MIRROR_WORDS = ("MASTER BALL", "POKE BALL", "POKEBALL", "POKÉ BALL")
_ALT_TYPES = ("alt_art", "parallel", "sp", "super_parallel", "manga")


def _norm(s):
    return re.sub(r"[\s\-_]", "", str(s or "").upper())


def op_set_code(brand):
    """ワンピの Brand からセット記号 (OP09 / PRB01 …)。無ければ ""。純関数。"""
    m = _OP_SET_RE.search(str(brand or "").upper())
    return (m.group(1) + m.group(2)) if m else ""


def has_alt_mark(subject):
    s = " " + str(subject or "").upper() + " "
    return any(w in s for w in _ALT_WORDS)


def has_sp_mark(subject):
    s = " " + str(subject or "").upper() + " "
    return any(w in s for w in _SP_WORDS)


def has_mirror_mark(subject):
    s = str(subject or "").upper()
    return any(w in s for w in _MIRROR_WORDS)


def _specs(row):
    s = row.get("specs")
    if isinstance(s, str):
        try:
            s = json.loads(s)
        except ValueError:
            s = {}
    return s or {}


def row_is_alt(row):
    sp = _specs(row)
    vt = str(sp.get("variant_type") or "").lower()
    fe = sp.get("features_ebay")
    fe = " ".join(fe) if isinstance(fe, list) else str(fe or "")
    return (vt in _ALT_TYPES or "Alternative Art" in fe or row_is_sp(row)
            or bool(_ALT_PID_RE.search(str(row.get("product_id") or ""))))


def row_is_sp(row):
    sp = _specs(row)
    return ("SP" in str(sp.get("rarity") or "").upper()
            or bool(re.search(r"_SP(_|$)", str(row.get("product_id") or ""), re.I)))


def _row_set_text(row):
    sp = _specs(row)
    return " ".join(str(x or "") for x in (row.get("set_name"), row.get("set_name_official"),
                                           sp.get("get_info")))


def conflict(category, brand, subject, row):
    """PSA ラベルと行が合わない理由。合えば ""。純関数。"""
    if not row:
        return "カタログの行が無い"
    if category == "one_piece_tcg":
        code = op_set_code(brand)
        if any(w in str(subject or "").upper() for w in _PROMO_WORDS):
            return ""
        if not code:
            # PROMOS / 記念セット / ストレージボックス等は PSA が刷りの印を書かないことがある
            # (人が選んだ正しい答え 3件を消しかけた 2026-09-28)。セット記号のあるパックだけ見る
            return ""
        if code not in _norm(_row_set_text(row)):
            return "セット記号が違う (PSA=%s / 行=%s)" % (code, _row_set_text(row).strip()[:40])
        alt = has_alt_mark(subject)
        if alt and not row_is_alt(row):
            return "PSA は別絵柄 (%s) だが行は通常" % subject
        if not alt and row_is_alt(row):
            return "PSA は通常だが行は別絵柄"
        if alt and has_sp_mark(subject) != row_is_sp(row):
            return "SP の有無が違う (PSA=%s)" % subject
    elif category == "pokemon_tcg":
        if has_mirror_mark(subject):
            return "PSA はミラー (%s) だがカタログにミラーの行は無い" % subject
    return ""


_COLS = ("product_id", "set_name", "set_name_official", "specs", "source")


def _row(con, category, pid):
    r = con.execute("select product_id, set_name, set_name_official, specs, source from products "
                    "where category=? and product_id=?", (category, pid)).fetchone()
    return dict(zip(_COLS, r)) if r else None


def _siblings(con, category, base):
    rows = con.execute("select product_id, set_name, set_name_official, specs, source from products "
                       "where category=? and (product_id=? or product_id like ?)",
                       (category, base, base + "_%")).fetchall()
    # like の _ は1文字の何でもにも当たるので、自分で確かめ直す
    out = []
    for r in rows:
        d = dict(zip(_COLS, r))
        if d["product_id"] == base or d["product_id"].startswith(base + "_"):
            if "dummy" not in d["product_id"].lower():
                out.append(d)
    return out


def pick(category, brand, subject, current_pid, db=CATALOG_DB, con=None):
    """(使う product_id, 理由)。合わない時は同じ番号の行から1つに絞れた物だけ返す。"""
    pid = str(current_pid or "").split(":", 1)[-1]
    if not pid:
        return "", ""
    own = con is None
    con = con or sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        why = conflict(category, brand, subject, _row(con, category, pid))
        if not why:
            return pid, ""
        if category != "one_piece_tcg":
            return "", why
        base = re.sub(r"_.*$", "", pid)
        good = [r for r in _siblings(con, category, base) if not conflict(category, brand, subject, r)]
        ok = [r["product_id"] for r in good]
        # 同じ刷りが2つの取り込み元に入っている (2026-09-28 カタログ回答: 正は公式サイト側)
        official = [r["product_id"] for r in good if "opcg_official" in str(r.get("source") or "")]
        if len(ok) > 1 and len(official) == 1:
            ok = official
        if len(ok) == 1:
            return ok[0], "%s → %s に直した" % (why, ok[0])
        return "", "%s / 合う行が%d件で決められない%s" % (
            why, len(ok), (" (" + ", ".join(ok[:4]) + ")") if ok else "")
    finally:
        if own:
            con.close()


def sweep_learned(path=None, db=CATALOG_DB, write=True):
    """目視で覚えた答え (psa_label_learned.json) のうち、ラベルの刷りと合わない物を直す/消す。

    ★2026-09-28: 覚えた答えは翌日以降の既定値になる。前の決まりで覚えた分を洗い直さないと、
      同じ誤りが毎日出る (グローバル規約 追記⑤)。
    戻り: {"checked": 件数, "fixed": [(label, 旧, 新)], "dropped": [(label, 旧, 理由)]}
    """
    import psa_label_learned as PLL
    path = path or PLL.PATH
    data = PLL.load(path)
    out = {"checked": 0, "fixed": [], "dropped": []}
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        for label, ent in list(data.items()):
            parts = label.split("|")
            if len(parts) < 4:
                continue
            category, brand, _num, subject = parts[0].lower(), parts[1], parts[2], "|".join(parts[3:])
            picks = (ent or {}).get("picks") or {}
            for pid in list(picks):
                out["checked"] += 1
                new, why = pick(category, brand, subject, pid, con=con)
                if new == pid:
                    continue
                v = picks.pop(pid)
                if new:
                    tgt = picks.setdefault(new, {"times": 0, "certs": []})
                    tgt["times"] = tgt.get("times", 0) + v.get("times", 0)
                    tgt["certs"] = sorted(set(tgt.get("certs", [])) | set(v.get("certs", [])))
                    tgt["last_at"] = max(str(tgt.get("last_at") or ""), str(v.get("last_at") or ""))
                    out["fixed"].append((label, pid, new))
                else:
                    out["dropped"].append((label, pid, why))
            if not picks:
                data.pop(label, None)
    finally:
        con.close()
    if write and (out["fixed"] or out["dropped"]):
        PLL.save(data, path)
    return out
