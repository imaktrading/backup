# -*- coding: utf-8 -*-
"""「違う」を全部 検索の事故 として騒がない (2026-09-03)。

## 何が起きていたか
再仕入れの目視で「違う」を押すたびに
`🚨 違う即対応 N件 — 検索が別カードを拾った=精度事故。生成(検索)を今すぐ直す`
と出て、専用タブに積まれていた。だが候補は **カード番号で引いている**ので、番号が
合っている候補を人が外すのは **同じ番号の別の絵柄**を弾いただけで、直す先が無い。

実測 2026-09-03: 「違う」10件は全部これ (SV3A-074 / SB02-053 / S12A-126 …)。
毎回「今すぐ直せ」と出るが直しようがなく、警告が意味を失っていた。

## 直し方
本当に直すべきなのは **番号で引けなかった枠** (`number_ok=False` = 名前一致だけで
積んだ候補)。そこが別カードを掴んだ時だけ 🚨 を出す。絵柄違いは一行の記録に留める
(候補NG台帳には従来どおり貯めるので、同じ候補は次回出ない)。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import psa_resource_gate as G  # noqa: E402


def _cands():
    return [{"channel": "mercari", "url": "https://m/num", "variant_ok": True},
            {"channel": "mercari", "url": "https://m/loose",
             "variant_ok": False, "number_ok": False}]


CANDS = [{"card_no": "S12A-126", "title": "PSA 10 ...", "candidates": _cands()}]


def test_number_matched_reject_is_art_not_a_bug():
    """番号で引けた候補を外した = 絵柄違い。検索の事故に数えない。"""
    bug, art = G.split_diffs_by_number_match([{"idx": 0, "url": "https://m/num"}], CANDS)
    assert bug == []
    assert len(art) == 1


def test_name_only_candidate_reject_is_a_search_bug():
    """番号で引けなかった枠が別カードを掴んだら、それは検索の事故。"""
    bug, art = G.split_diffs_by_number_match([{"idx": 0, "url": "https://m/loose"}], CANDS)
    assert len(bug) == 1
    assert art == []


def test_unknown_candidate_is_treated_as_art():
    """候補が見つからない (古いcache等) 時は騒がない。"""
    bug, art = G.split_diffs_by_number_match([{"idx": 0, "url": "https://m/gone"}], CANDS)
    assert bug == []
    assert len(art) == 1


def test_bad_index_does_not_crash():
    bug, art = G.split_diffs_by_number_match([{"idx": 99, "url": "x"}, {"url": "y"}], CANDS)
    assert len(bug) == 0 and len(art) == 2
