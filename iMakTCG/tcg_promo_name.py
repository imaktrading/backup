"""tcg_promo_name — PSA Subject から「何のプロモか」(配布元説明) を抽出し casing 安全に整形する。

背景: 一番くじ/7-Eleven 等のプロモカードは catalog が配布元を持たず(set_name="Other Product Card")、
新コアのタイトルが generic で短くなる。配布元の唯一の実ソースは PSA ラベルの Subject
(例 "MONKEY D. LUFFY ICHIBAN KUJI PURCHASE BONUS")。

ただし Subject は鑑定者表記でブレ得る + ALLCAPS なので、
  1. extract_residual: Subject から「キャラ名/カード番号」を除いた残差 = 配布元説明 を取り出す
  2. normalize_promo: ALLCAPS を「崩さず」整形 (GX/EX/FB02/25TH/7-Eleven 等は保持、語は Title Case)
を分離。確証なく綺麗にできない残差は **空文字** を返す (fail-closed = 捏造せず付けない)。

この純関数の出力を「下書き」として人がレビューHTMLで承認/編集/削除し、確定値を
HQ所有の per-card override に焼く想定 (catalog は公式のみ=触らない / catalog_official_only)。
"""
from __future__ import annotations

import re

# 整形時に「大文字のまま保持」する既知トークン (語ではなく記号/略号)。
_KEEP_UPPER = {
    "GX", "EX", "V", "VMAX", "VSTAR", "SP", "SR", "UR", "HR", "RR", "AR",
    "TCG", "CCG", "DA", "FA", "BS", "II", "III", "IV",
}
# 略語 → 展開 (タイトルで意味が通る形に)。
_ABBREV = {
    "COLL": "Collection", "COLL.": "Collection",
    "ANNIV": "Anniversary", "ANNIV.": "Anniversary",
    "CHAMP": "Championship", "CHAMP.": "Championship",
    "ED": "Edition", "ED.": "Edition",
}
# set code: 英字1-3 + 数字2桁以上 (FB02 / EB01 / OP12 / SV9 等) → 大文字保持。
_SETCODE = re.compile(r"^[A-Z]{1,3}\d{2,}[A-Z]?$")
# 序数 (25TH / 1ST / 2ND / 3RD) → 数字+小文字 suffix。
_ORDINAL = re.compile(r"^(\d+)(ST|ND|RD|TH)$", re.I)
# 配布元として無意味なアート種別 prefix (catalog Features 管轄。promo 説明には不要)。
_ART_NOISE = {"FA", "AA"}


def _char_tokens(character_name: str) -> set:
    """キャラ名を比較用トークン集合に。'Monkey.D.Luffy' / 'Monkey D. Luffy' 両対応。
    中間イニシャル(D 等の1文字)も除去対象に含める (= 残差に名前の破片を残さない)。"""
    if not character_name:
        return set()
    return {t for t in re.split(r"[\s.\-/]+", character_name.upper()) if t}


def extract_residual(subject: str, character_name: str = "", card_number: str = "") -> str:
    """Subject から キャラ名/カード番号 を除いた残差 (= 配布元説明 raw, ALLCAPS) を返す。

    残差が無ければ '' (= Subject がキャラ名だけ等)。整形は normalize_promo が担当。
    '/' 区切り (FA/PIKACHU, 232/SV-P) もトークン分割し、ハイフン語 (7-ELEVEN/H2-CELL) は温存。
    """
    if not subject:
        return ""
    s = subject.upper().strip()
    cnum = (card_number or "").upper().strip()
    if cnum:                       # カード番号は分割前に丸ごと除去 (232/SV-P 等の '/' を守る)
        s = s.replace(cnum, " ")
    chars = _char_tokens(character_name)
    out = []
    for tok in re.split(r"[\s/]+", s):     # 空白 + '/' で分割 (ハイフンは温存)
        base = tok.strip(".,:;()[]")
        if not base or base in chars:
            continue
        out.append(tok)
    return " ".join(out).strip(" /.-,:;").strip()


def _norm_token(tok: str) -> str:
    """1トークンを casing 安全に整形。保持すべき大文字は崩さない。"""
    base = tok.strip(".,:;()[]")
    up = base.upper()
    if up in _ABBREV:
        return _ABBREV[up]
    if up in _KEEP_UPPER:
        return up
    if _SETCODE.match(up):
        return up
    m = _ORDINAL.match(base)
    if m:
        return m.group(1) + m.group(2).lower()    # 25TH -> 25th
    # ハイフン語は各片を整形 (7-ELEVEN -> 7-Eleven / H2-CELL -> H2-Cell)
    if "-" in base:
        return "-".join(_norm_token(p) for p in base.split("-") if p != "")
    # 数字始まり (7 等) はそのまま、英字語は Title Case
    return base[:1].upper() + base[1:].lower() if base else base


def normalize_promo(raw: str) -> str:
    """残差(ALLCAPS) を casing 安全な promo 名に。綺麗にできなければ '' (fail-closed)。

    - 既知の大文字トークン/set code/序数 は崩さない
    - アート種別 prefix (FA/AA) のみの残差は promo でない → ''
    - 整形後に英数字が無い/記号だけ なら '' (捏造しない)
    """
    if not raw:
        return ""
    toks = [t for t in re.split(r"\s+", raw.strip()) if t.strip(".,:;()[]/-")]
    if not toks:
        return ""
    # 先頭がアート種別 prefix だけのノイズなら落とす (FA / AA)。複数語あるうちの prefix のみ対象。
    while len(toks) > 1 and toks[0].strip(".,:;()[]/").upper() in _ART_NOISE:
        toks = toks[1:]
    # 残りがアート種別単独 (= 配布元説明でない) なら付けない
    if len(toks) == 1 and toks[0].strip(".,:;()[]/").upper() in _ART_NOISE:
        return ""
    normed = [_norm_token(t) for t in toks]
    normed = [n for n in normed if n]
    out = " ".join(normed).strip()
    # 英数字を含まなければ捏造とみなし空
    if not re.search(r"[A-Za-z0-9]", out):
        return ""
    return out


def propose_promo(subject: str, character_name: str = "", card_number: str = "") -> str:
    """Subject → promo名 下書き (抽出+整形)。人のレビュー前提の draft。綺麗にできなければ ''。"""
    return normalize_promo(extract_residual(subject, character_name, card_number))
