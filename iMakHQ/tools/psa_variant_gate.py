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
              "MANGA", "SPECIAL CARD", "-SP", " SP CARD",
              # ★2026-10-07 ボックストッパーは通常と別の絵柄 (OP02-059 ハンコック: カタログは _p1)。
              #   無いと刷りの確認が通常版 OP02-059 に「直して」いた
              "BOX TOPPER",
              # ★2026-10-07 EB02 (アニメ25周年) は PSA が「CARROT SPECIAL」のように SPECIAL とだけ書く (別絵柄)
              " SPECIAL ")
# SP カード (WANTED 手配書柄など)。ALTERNATE ART だけのスラブは SP ではない
_SP_WORDS = ("WANTED", "SPECIAL CARD", "SPECIAL ALTERNATE", "SPECIAL ALT", "-SP", " SP CARD")
_ALT_PID_RE = re.compile(r"_(p\d*|SP)(_|$)")  # 小文字 p=パラレル / 大文字 P=プロモ (別物)
# 大会賞品・プロモ。PSA の Brand は元のセット (例 STARTER DECK ST01) でも、現物はプロモ行
# (例 ST01-007_P_win = STANDARD BATTLE WINNER)。セット記号で見ると正しい行を外してしまう
_PROMO_WORDS = ("WINNER", "PROMO", "FLAGSHIP", "CHAMPIONSHIP", "TOURNAMENT", "BATTLE", "EVENT",
                "PRIZE", "JUMP", "CAMPAIGN", "GIFT", "PRE-RELEASE", "PRERELEASE", "FINALIST")
_MIRROR_WORDS = ("MASTER BALL", "POKE BALL", "POKEBALL", "POKÉ BALL", "ROCKET REVERSE HOLO")


def mirror_text(text):
    """ラベル / 行の版の表記 → 揃えた形 ("MASTER BALL REVERSE HOLO" 等)。版の印が無ければ ""。純関数。

    ★2026-10-07 カタログが版ごとの行 (<通常版>_mb / _pb / _rk・specs.variant_psa_text) を持つようになった
      (catalog 回答 2026-10-07_pokemon_mirror_variants_need_own_rows_response.md)。ラベルと行の版を
      この形で突き合わせる。版名なしの REVERSE HOLO はここでは見ない (まだ行が無い・従来どおり通常の行で出す)。
    """
    u = " ".join(str(text or "").upper().replace("POKÉ", "POKE").replace("POKEBALL", "POKE BALL").split())
    for w in ("MASTER BALL", "POKE BALL", "ROCKET"):
        if w + " REVERSE HOLO" in u:
            return w + " REVERSE HOLO"
    # ★2026-10-10 (ブラボー B-20261010-001 / 残務 №388): ボールの名前の無い「REVERSE HOLO」も**ミラー**。
    #   通常版として通していたため、ブラッキー (UMBREON REVERSE HOLO・10/07) とレックウザ (RAYQUAZA REVERSE HOLO・10/09)
    #   が通常版の KEY で出品された。どのミラーかはラベルで決まらないので、ミラーの行が1つだけの時に限りそれを使う
    if "REVERSE HOLO" in u:
        return "REVERSE HOLO"
    return ""
_ALT_TYPES = ("alt_art", "parallel", "sp", "super_parallel", "manga")


_GD_RARITY_RE = re.compile(r"(LEGEND RARE\+?|RARE\+?|COMMON\+?|UNCOMMON|LR\+?|R\+|C\+)(?=\s|$)")


def label_text(psa):
    """PSA データから ラベルの文字 (Subject + Variety + 除かれたレアリティ) をまとめる。純関数。"""
    psa = psa or {}
    return " ".join(str(psa.get(k) or "") for k in ("Subject", "Variety", "LabelRarity")).strip()


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


def row_alias_alt(row):
    """カタログが別名でまとめた先 (本体) が別絵柄の行か。再録の行に多い (OP09-020_PRB02 → OP09-020_p2)。

    ★2026-10-07: 名前に _p が無いので通常と見て、もう一つの PRB02 の別絵柄 (_PRB02_p1 = 別の絵) に「直して」いた。
      ただし再録先では通常として刷られ、PSA が別絵柄の印を書かないこともある (ST18 のルフィ = OP05-060_p3 の絵)。
      → この行は「別絵柄の印があっても無くても合う」扱いにする
    """
    return bool(_ALT_PID_RE.search(str(row.get("alias_of") or "")))


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
        if alt and not (row_is_alt(row) or row_alias_alt(row)):
            return "PSA は別絵柄 (%s) だが行は通常" % subject
        if not alt and row_is_alt(row):
            return "PSA は通常だが行は別絵柄"
        if alt and has_sp_mark(subject) != row_is_sp(row):
            return "SP の有無が違う (PSA=%s)" % subject
    elif category == "gundam_tcg":
        # 「+」がパラレルの印 (RARE+ / LR+ / C+)。ラベルにレアリティが読めない時は判断しない
        m = _GD_RARITY_RE.search(" " + str(subject or "").upper() + " ")
        if m:
            plus = "+" in m.group(1)
            sp = _specs(row)
            is_para = (str(sp.get("variant_type") or "").lower() in _ALT_TYPES
                       or str(sp.get("rarity") or "").endswith("+")
                       or bool(re.search(r"_(para|p\d+)(_|$)", str(row.get("product_id") or ""))))
            if plus and not is_para:
                return "PSA はパラレル (%s) だが行は通常" % m.group(1)
            if not plus and is_para:
                return "PSA は通常 (%s) だが行はパラレル" % m.group(1)
    elif category == "pokemon_tcg":
        lab, row_v = mirror_text(subject), mirror_text(_specs(row).get("variant_psa_text"))
        if lab == "REVERSE HOLO" and row_v:
            return ""                                          # 名前の無いミラー: どのミラーの行でも合う (1つに絞れた時だけ使われる)
        if lab != row_v:
            return "PSA は %s だが行は %s" % (lab or "通常", row_v or "通常")
    return ""


_COLS = ("product_id", "set_name", "set_name_official", "specs", "source")


def _extra_cols(con):
    """alias_of / language のうち、この DB に在る列 (試験の最小 DB には無い)。"""
    try:
        have = {r[1] for r in con.execute("pragma table_info(products)")}
    except sqlite3.Error:
        return ()
    return tuple(c for c in ("alias_of", "language") if c in have)


def _alias_cols(con):
    return "alias_of" in _extra_cols(con)


def _row(con, category, pid):
    ex = _extra_cols(con)
    al = "".join(", " + c for c in ex)
    r = con.execute("select product_id, set_name, set_name_official, specs, source%s from products "
                    "where category=? and product_id=?" % al, (category, pid)).fetchone()
    return dict(zip(_COLS + ex, r)) if r else None


def _siblings(con, category, base):
    ex = _extra_cols(con)
    al = "".join(", " + c for c in ex)
    rows = con.execute("select product_id, set_name, set_name_official, specs, source%s from products "
                       "where category=? and (product_id=? or product_id like ?)" % al,
                       (category, base, base + "_%")).fetchall()
    cols = _COLS + ex
    # like の _ は1文字の何でもにも当たるので、自分で確かめ直す
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if d["product_id"] == base or d["product_id"].startswith(base + "_"):
            if "dummy" not in d["product_id"].lower():
                out.append(d)
    return out


def narrow_gundam_plus(brand, subject, good, ok):
    """ガンダムの「+」(パラレル) のラベルで合う行が複数ある時に1つに絞る。絞れなければ ok のまま。純関数。

    ★2026-10-07 cert 122484177 (ST04-010 キラ・ヤマト COMMON+): 公式サイトのパラレル行 _p1〜_p7 は
      レアリティが「C」のままで、どれが C+ か行からは分からない → 8件で決められず、目視で何度 OK しても
      出品の手前で落ち、毎回目視に戻っていた (5回)。レアリティに「+」と書いてあるのは別の取り込み元の
      _bp (英語) / _bp_JP (日本語) で、_bp_JP はカタログが本体 _p1 にまとめている (alias_of)。
      → 「+」と書いた行 → ラベルの言語 (JAPANESE) → 別名の本体 の順で絞る
    """
    m = _GD_RARITY_RE.search(" " + str(subject or "").upper() + " ")
    if not m or "+" not in m.group(1):
        return ok
    plus = [r for r in good if str(_specs(r).get("rarity") or "").endswith("+")]
    if "JAPANESE" in str(brand or "").upper():
        plus = [r for r in plus if str(r.get("language") or "").lower() in ("ja", "both", "")]
    picked = []
    for r in plus:
        body = str(r.get("alias_of") or "")
        pid = body if body in ok else r["product_id"]
        if pid not in picked:
            picked.append(pid)
    return picked if len(picked) == 1 else ok


def pick(category, brand, subject, current_pid, db=CATALOG_DB, con=None):
    """(使う product_id, 理由)。合わない時は同じ番号の行から1つに絞れた物だけ返す。"""
    pid = str(current_pid or "").split(":", 1)[-1]
    if not pid:
        return "", ""
    own = con is None
    con = con or sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        row = _row(con, category, pid)
        why = conflict(category, brand, subject, row)
        if not why:
            # ★2026-10-07 カタログの別名なら、本体もラベルと合う時は本体を返す (同じ現物は1つの ID に)
            body = str((row or {}).get("alias_of") or "")
            if body and body != pid and not conflict(category, brand, subject, _row(con, category, body)):
                return body, "%s はカタログで %s にまとめられている" % (pid, body)
            return pid, ""
        if category not in ("one_piece_tcg", "gundam_tcg", "pokemon_tcg"):
            return "", why
        base = re.sub(r"_.*$", "", pid)
        good = [r for r in _siblings(con, category, base) if not conflict(category, brand, subject, r)]
        ok = [r["product_id"] for r in good]
        # 同じ刷りが2つの取り込み元に入っている (2026-09-28 カタログ回答: 正は公式サイト側)
        official = [r["product_id"] for r in good if "official" in str(r.get("source") or "")]
        if len(ok) > 1 and len(official) == 1:
            ok = official
        if len(ok) > 1 and category == "gundam_tcg":
            ok = narrow_gundam_plus(brand, subject, good, ok)
        if len(ok) == 1:
            return ok[0], "%s → %s に直した" % (why, ok[0])
        return "", "%s / 合う行が%d件で決められない%s" % (
            why, len(ok), (" (" + ", ".join(ok[:4]) + ")") if ok else "")
    finally:
        if own:
            con.close()


def _alias_body(pid, con):
    """カタログで alias_of が付いた行なら、その本体の product_id。無ければ ""。"""
    try:
        r = con.execute("select alias_of from products where product_id=? limit 1", (pid,)).fetchone()
    except sqlite3.Error:
        return ""
    return (r[0] or "").strip() if r else ""


def _merge_pick(bag, old, new):
    """picks / not の old を new に足し込んで消す (回数・鑑定番号を引き継ぐ)。"""
    v = bag.pop(old)
    tgt = bag.setdefault(new, {"times": 0, "certs": []})
    tgt["times"] = tgt.get("times", 0) + v.get("times", 0)
    tgt["certs"] = sorted(set(tgt.get("certs", [])) | set(v.get("certs", [])))
    tgt["last_at"] = max(str(tgt.get("last_at") or ""), str(v.get("last_at") or ""))


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
            # ★2026-10-07 カタログが同じ現物の2行を alias_of でまとめた分は、本体の ID に寄せる
            #   (寄せないと、同じスラブに2つの ID が付いて「答えが割れた」に見え、ラベルが効かなくなっていた: 9ラベル)
            _nots = (ent or {}).get("not") or {}
            for pid in list(_nots):
                body = _alias_body(pid, con)
                if body and body != pid:
                    _merge_pick(_nots, pid, body)
            for pid in list(picks):
                out["checked"] += 1
                new, why = pick(category, brand, subject, pid, con=con)
                # ★2026-10-07 選んだ行がカタログの別名なら本体へ。ただし本体もラベルと合う時だけ
                #   (PRB02 の再録行の本体 OP09-020_p2 にはセット記号 PRB02 が無い → 寄せると外れてしまう)
                if new:
                    body = _alias_body(new, con)
                    if body and body != new and not conflict(category, brand, subject, _row(con, category, body)):
                        new = body
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
            if not picks and not (ent or {}).get("not"):
                data.pop(label, None)
    finally:
        con.close()
    if write and (out["fixed"] or out["dropped"]):
        PLL.save(data, path)
    return out
