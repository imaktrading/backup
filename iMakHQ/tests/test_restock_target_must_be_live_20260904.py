# -*- coding: utf-8 -*-
"""再仕入れの対象は「出品中 かつ 在庫なし」(2026-09-04 ユーザー確定)。

> 再仕入れ対象の基準がおかしいよな？出品中で在庫がなくて・・・でしょ？

## 何が起きていたか
③確認が毎回「⏳入稿待ち = 要対応」と言い続け、押しても減らなかった (実測5件)。
中身を見たら、5件とも **eBay の出品が既に終了**していて、商品管理シートの B列にも
その itemID が無かった。再仕入れ (revise) は **生きている出品の数量を戻す**機能なので、
終了済は何度やっても戻せない。

## 入口が2つあり、片方だけ基準を満たしていなかった
  ファネル経路 … eBay の出品中レポートが元 → 「出品中」を満たす ✅
  待ち台帳経路 … 過去に供給が無かった行を毎回再探索する仕組み。
                 出品が終了すると funnel からは消えるが **台帳は持ち続ける** ため、
                 終了済がよみがえって毎回 RESTOCK確定 に入っていた ❌

CULL (取下げボタン) で落とした分も混ざっていたが、**原因は取下げの基準ではない**。
取下げと再仕入れは別の軸で、揃える必要は無い。揃えるべきは「出品が在るか」。

## 直し方
台帳から合流させる時に出品の生死を見る。終了済は対象にせず、台帳には
「終了済」として残す (行は消さない = 需要の記録は資産)。
分からない時 (取得失敗) は従来どおり合流させる = fail-closed。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_restock_wait as prw                                 # noqa: E402


def _row(iid, status):
    return {"初出日": "2026-08-01", "最終確認日": "2026-09-01", "status": status,
            "再チェック回数": "5", "itemID": iid, "KEY": "k", "card_no": "c",
            "title": "t" + iid, "ebay_url": "https://www.ebay.com/itm/" + iid}


def test_ended_rows_are_not_rechecked():
    """終了済は再探索しない。供給が出ても戻す先が無い。"""
    led = [_row("1", prw.ST_WAIT), _row("2", prw.ST_ENDED),
           _row("3", prw.ST_UNKNOWN), _row("4", prw.ST_REVIVED)]
    got = [t["itemID"] for t in prw.recheck_targets(led)]
    assert got == ["1", "3"]


def test_mark_ended_keeps_the_row():
    """行は消さない。『この出品は終わった』も需要の記録も資産。"""
    led = [_row("1", prw.ST_WAIT), _row("2", prw.ST_WAIT)]
    out, n = prw.mark_ended(led, ["2"], "2026-09-04")
    assert n == 1 and len(out) == 2
    assert out[1]["status"] == prw.ST_ENDED
    assert out[1]["最終確認日"] == "2026-09-04"
    assert out[1]["title"] == "t2"          # 中身は失わない
    assert out[0]["status"] == prw.ST_WAIT  # 他の行は触らない


def test_mark_ended_is_idempotent():
    led = [_row("1", prw.ST_ENDED)]
    out, n = prw.mark_ended(led, ["1"], "2026-09-04")
    assert n == 0 and out[0]["status"] == prw.ST_ENDED


def test_the_gate_checks_the_listing_before_merging():
    """合流の前に出品の生死を見ていること。分からない時は合流させる (fail-closed)。"""
    import io as _io
    src = _io.open(os.path.join(_TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()
    i = src.index("再仕入れ待ち台帳の End候補 を再チェックに合流")
    seg = src[i:i + 2600]
    assert "fetch_listing_status" in seg, "出品の生死を見ていない"
    assert 'st is not None and st != "Active"' in seg, "不明を終了扱いにしている"
    assert "mark_ended" in seg, "台帳に終了済を書き戻していない"
