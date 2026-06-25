# 2026-06-25 異常delta判定に RESTOCK 整合照合を追加

## 概要
RESTOCK 時に監視くん側で既に値上げ反映済みの行が、リバイスくんの abnormal_delta guard で
毎 cycle 誤 alert + skip されていた問題を解消。eBay 実価格が N 計算値と一致するなら整合済
(aligned) として静かに通し、不一致のときだけ従来通り scrape 誤り疑いで alert する。

## 発端
- 6/25 dry-run で item 358719842131 (一番くじ) が AH=¥1,380 → N=¥17,000 (+1132%) で
  abnormal_delta 判定 → skip + alert。
- ユーザー確認: ¥17,000 は実在の仕入価格 (RESTOCK で別ソースに切替)。eBay は $231.98 で出品中。
- V8 照合: compute_listing_price_v6(17000, 一番くじ) = **$231.98** = eBay 実価格と完全一致。
  = RESTOCK 時に監視くんが既に正しく値上げ済。リバイスくんが触る必要なし。
- 問題: 旧ロジックは AH↔N の急騰しか見ず「eBay 価格が既に N 計算値で整合している」事実を
  照合していなかった → 毎週この行を誤 alert + skip し続ける (= ユーザー指摘の「RESTOCK revise
  との不整合」)。

## 記録
- 決定: abnormal_delta は「skip 確定」ではなく「eBay 実価格 vs N 計算値の照合」に変更。
  一致 → aligned (RESTOCK 反映済、alert 不要)。不一致 → abnormal_delta (scrape 誤り疑い、従来通り alert)。
  guard は弱めない (fail-closed: 整合確認できなければ abnormal のまま)。
- 変更: [revise/price_revise.py](../revise/price_revise.py)
  - `should_revise`: 異常 delta 検出時に RESTOCK 整合 reconciliation を追加 (一致→aligned / 不一致→abnormal_delta)。
  - `detect_candidates`: 異常行の `skip_reason` 付与を廃止 (None に) → V8/snapshot まで流す。
  - Step2 pre-filter 撤去: 異常行も V8 計算 + snapshot 取得を経て should_revise で振り分け。
  - Step5: should_revise の `is_abnormal` を candidate に反映、reason=abnormal_delta のみ result.abnormal へ。
  - alert log: skip_reason 依存の文言を固定文言化。
- 変更: [tests/test_price_revise.py](../tests/test_price_revise.py)
  - test_abnormal_delta を 3 ケースに分割: mismatch→abnormal / reconciled→aligned / not_in_snapshot→abnormal(fail-closed)。
- 検証: 全 71 price_revise テスト pass。
- 検証: 実 dry-run (HIGH, 既存 snapshot 利用) → item 358719842131 が aligned に分類、
  abnormal_delta=0、新規 alert ログ非生成を確認。
- 検証: test_v8_smoke の 3 失敗は本変更前から存在 (git stash で確認) = V8 価格 yaml 更新由来の
  参照値ズレで本変更とは無関係 (別途要 reference 更新)。

## 補足 (既知・別対応)
- test_v8_smoke.py の参照価格 3 件が本元 V8 yaml (duty/tier) 更新で陳腐化。別 cycle で reference 更新要。
