# -*- coding: utf-8 -*-
"""PSA ラベル(Subject)に **明記されている** finish だけを取り出す (2026-07-28).

方針: 推測しない。PSA が現物を鑑定して打った文字だけを転記する。
  - 画像の光り方から判定しない (スラブ越し・光源依存で Holo と Reverse Holo を取り違える)
  - rarity から類推しない ("Alternate Art" は Foil を意味しない)
  - ラベルに何も書いていなければ **空** (= 従来どおり C:Finish 空欄)

Holo と Reverse Holo は別物 (絵柄が光る / 地の部分が光る) で価格も違うため、
取り違えは SNAD クレーム直結。だからラベル記載以外の根拠は使わない。

実測 (2026-07-28 / psa_cache.json 823 cert): 明記があるのは 32件 = 3.9%。
  -HOLO 16 / REV.FOIL 7 / REVERSE HOLO 7 / HOLOFOIL 1 / SPARKLE FOIL 1
"""
import re

# eBay の C:Finish 正規値 (フィルタのドロップダウン値と一致させる)。
HOLO = "Holo"
REVERSE_HOLO = "Reverse Holo"
FOIL = "Foil"

# ★2026-10-15 (B-20261015-024): Reverse Holo の読み方 (REV.FOIL / REVERSE FOIL 等の略記) は **ここ1か所**。
#   psa_variant_gate.mirror_text もこれを呼ぶ (2か所に書いて食い違い、REV.FOIL が通常版で出品された)
REVERSE_HOLO_RE = re.compile(r"REVERSE\s*HOLO|REV\.?\s*FOIL|REVERSE\s*FOIL", re.I)


def normalize_reverse_holo(text):
    """ラベルの Reverse Holo の略記を "REVERSE HOLO" に揃える (純関数)。"""
    return REVERSE_HOLO_RE.sub("REVERSE HOLO", str(text or ""))


# ★順序が意味を持つ: REVERSE 系を先に判定する。
#   'HO-OH-REV.FOIL' を FOIL パターンで先に拾うと Reverse Holo を Foil と誤記する。
_RULES = [
    (REVERSE_HOLO_RE, REVERSE_HOLO),
    (re.compile(r"HOLOFOIL|(?<![A-Z])HOLO(?![A-Z])", re.I), HOLO),
    (re.compile(r"(?<![A-Z])FOIL(?![A-Z])", re.I), FOIL),
]


def finish_from_psa_label(subject):
    """PSA ラベルの Subject → eBay C:Finish 値。明記が無ければ "" (純関数)。

    'SNORLAX-HOLO'                  → 'Holo'
    'HO-OH-REV.FOIL 25TH ANNIV...'  → 'Reverse Holo'
    'MONKEY D. LUFFY SPARKLE FOIL'  → 'Foil'
    'GENGAR-HOLO SHINY STAR V'      → 'Holo'   (SHINY STAR V はセット名。finish ではない)
    'PIKACHU VMAX'                  → ''       (明記なし = 空欄が正)
    """
    s = str(subject or "")
    if not s.strip():
        return ""
    for pat, val in _RULES:
        if pat.search(s):
            return val
    return ""
