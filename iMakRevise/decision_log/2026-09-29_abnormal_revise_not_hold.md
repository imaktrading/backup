# 2026-09-29 急騰(abnormal_delta)を「保留」から「価格更新+要目視alert」に変更

## 背景
- ユーザー指摘: 急騰を skip+hold すると、**旧(安い)価格のまま出続け、売れると赤字**。
  「本物かどうかはさておき、価格が修正されていないのが問題」。
- 実例: シャンクス SEC (820041238478) が AH ¥8,780 → N ¥29,999 (+242%) で 2日連続保留、
  安値で live のままだった。

## 変更 (commit 5a65b66f)
- `should_revise`: 急騰でも **価格更新する** (revise_yes=True)。
  - snapshot不在/在庫0/現価格取得不能 → 従来どおり skip (revise先が無い)
  - eBay価格 = N計算値 → aligned (更新不要)
  - それ以外 → 価格更新 + `is_abnormal=True` で要目視alert
- 主フロー: 急騰revise は `revisable`(UP対象) と `abnormal`(alert) の両方に載る。
- `run_daily` レポート文言: 「異常保留 UPせず」→「急騰で値上げ 価格更新済・要目視」。

## なぜ安全か
- 誤検知(scrape誤り)でも「高く出て売れない = 損なし・翌日戻る」。
  放置(安値で売れて赤字) より倒す向きとして安全。alert は残すので人が後で確認可。

## テスト
- test_abnormal_delta_mismatch / _not_in_snapshot / _takes_priority_over_diff を新挙動に更新。
- test_abnormal_revise_yes_when_price_stale 新規。全199 pass。

## 残
- シャンクス SEC: 9/29 09:54 に日次を手動実行 → GetItem で $132.98 → $366.98 / DDP-A-P22 反映を確認済。
