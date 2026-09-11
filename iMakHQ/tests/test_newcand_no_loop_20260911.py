# -*- coding: utf-8 -*-
"""🌱 捨てた候補→新規出品の種 が **押しても件数が減らない** ループを断つ (2026-09-11)。

ユーザー「ヒントテキストの件数がおかしい」(1件 → 1件)。実例は
「【PSA10】ドン!!カード(ハンニャバル)(スーパーパラレル)」で、人が打った番号が
**`PRB02` (セット名だけ)** だった:

  1. `catalog_variants("PRB02")` が前方一致で `PRB02-001`〜`-012` の **別カード12枚**を返す
  2. 「入力番号で catalog に在った → 依頼せず次回に候補を出す」
  3. 次回その12枚を見せる → 人が「無い」 → 2 に戻る (無限ループ)

直したのは2つ:
  ① `-` で続く product_id は **別の番号** (版は `_` で続く。catalog 実測: 9,233件すべて `_`)
  ② **その番号の候補を人がもう見ている**なら、「無い」は人の結論。再チェックで戻さない
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import newcand_confirm as N     # noqa: E402


def test_セット名だけだと別カードを版として拾わない():
    assert N._is_other_card("PRB02-001", "PRB02") is True
    assert N._is_other_card("BW1-Bb-001", "BW1") is True


def test_本物の番号の版はそのまま():
    assert N._is_other_card("OP05-002", "OP05-002") is False           # 同じもの
    assert N._is_other_card("OP05-002_p1", "OP05-002") is False
    assert N._is_other_card("OP05-002_EB02_LF", "OP05-002") is False
    assert N._is_other_card("EB02-052_OP15-EB04_p2", "EB02-052") is False  # 途中の - は関係ない


def test_数字で続くのは従来どおり別カード():
    assert N._is_other_card("OP05-0021", "OP05-002") is True


def _src():
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tools", "newcand_confirm.py"), encoding="utf-8").read()


def test_候補を見せた後の無いは再チェックで戻さない():
    """再チェック(=次回また候補を出す) は、まだ候補を見せていない時だけ。"""
    src = _src()
    blk = src[src.index("for i in res[\"catalog_reqs\"]:"):]
    blk = blk[:blk.index("creqs.append(")]
    assert "_seen = bool(it.get(\"variants\"))" in blk
    # 2つの再チェック分岐の両方が _seen で止まる
    assert "if not _seen and typed.get(i) and catalog_variants(typed[i]):" in blk
    assert "if not _seen and not typed.get(i) and it[\"card_no\"] and any(" in blk
