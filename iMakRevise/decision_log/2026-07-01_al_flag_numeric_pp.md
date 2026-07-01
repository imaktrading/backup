# 2026-07-01 AL列(値下FLG)を数値pp化 — 読取ロジック更新

## 概要
HQ がユーザー要望で AL列「値下FLG」を **文字列 "値下5pp" → 数値pp** に変更
(既定"5"、人手で"8"等に上書き可)。リバイスくんの読取を数値対応し、AL値を
`apply_pricedown_override(..., cut_pct=float(AL))` に渡す。

## 記録
- 決定: AL列が **正の数値** の行を対象 (かつ D≠○)、その値を cut_pct に渡す (5→5% / 8→8%)。
  過大値 (gate=10 以下でない) は関数が ValueError → 既存 fail-safe で標準据置 = 赤字出さない。
- 決定: 移行期の安全のため **旧文字列 "値下5pp" も 5.0 として拾う後方互換** を追加
  (noconvert の数値化 sync が未走の間も値下げが止まらないよう。実シートは本実装時点でまだ "値下5pp")。
- 変更: [revise/price_revise.py](../revise/price_revise.py)
  - `parse_pricedown_pp(flag)` 追加: 正の数値→float / 空・非数値・≤0→None / 旧"値下Npp"→N。
  - compute_new_usd: `PRICEDOWN_FLG_VALUE == 判定` を廃し、`cut_pp=parse_pricedown_pp(...)` が
    非Noneなら `cut_pct=cut_pp` で override 呼出。
  - サマリー件数も parse ベースに変更。`import re` 追加。
- 変更: [tests/test_price_revise.py](../tests/test_price_revise.py)
  - AL="5"→5% / "8"→8%(5%より安) / "10"→gate ValueError で標準据置 / 空・0・負・非数値→非対象 /
    旧"値下5pp"→5%互換 / parse_pricedown_pp 単体 を追加。
- 検証: 全88テスト pass。
- 検証(本番統合): 実HIGH/LOW(現状 "値下5pp") dry-run で「flag 193件中190件に値下げ適用」を確認
  = legacy 互換で移行期も途切れない。

## HQ へ共有
- 実シートの AL列は本実装時点でまだ旧 "値下5pp"。数値化 sync (noconvert) を走らせれば "5"/"8" 等になり
  そのまま動く (legacy 互換もあるので順序不問)。
