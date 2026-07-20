# 2026-07-21 日次メール改善 + スプシ読込リトライ

## 背景
ユーザーから「日次リバイスが定期で走ってるか / メールが来ない」との指摘。
直近ログ調査 → タスク自体は毎日04:30稼働も、(1)メール未達 (2)散発的な当日中止 の2問題が判明。

## 対応1: 日次結果メールに価格変動 Top10 追加
- 決定: 結果メール本文に「価格変動 大きい順 上位10件 (旧→新/差額)」を追加
- 変更: revise/run_daily.py:_build_summary_body (delta>=0.01 のみ、送料profileのみ変更=delta0は除外)
- 検証: --dry-run で描画確認。価格変動ゼロの日は「(本日は価格変動なし=送料profile変更のみ)」表示
- commit: e6fc233 / 38dc08d

## 対応2: xlsx 添付廃止 (メール未達の真因)
- 決定: 日次メールの review.xlsx 添付を廃止。本文のみに
- 変更: revise/run_daily.py:_send_summary (add_attachment 削除)、本文に revise内訳追加
- 検証: A/B/C/D/E/F テスト送信で切分け。プレーンは届く/xlsx添付は丸ごと未達/添付外した実本文(F)は届く
       → Gmail が「自分宛て+xlsx添付」を silent 破棄と確定
- commit: 38dc08d
- memory: gmail_self_send_xlsx_attachment_blocked.md 追加

## 対応3: スプシ読込に transient リトライ
- 決定: Google Sheets API 503 でその日の revise がまるごと中止する取りこぼしを自己回復させる
- 変更: revise/price_revise.py:_gspread_retry 新設 → open_by_key/worksheet/get_values をラップ
       (5xx/429/接続断を 30s×3回 backoff、恒久エラーは従来通り FATAL)
- 検証: syntax OK + --dry-run で全3sheet読込・revise=561 完了確認 (リトライ経路はコード検査)
- 根拠: 07/16・07/18 の日次中止が APIError [503] 起因 (daily_revise.log)
- commit: 5d292b5

## 直近5回の稼働状況 (調査結果)
- 07/17 ✅ revise=625 / 07/18 ❌ 503中止 / 07/19 ✅ 604 / 07/20 ✅ 563 / 07/21 ✅ 568
- 4/5 正常。残り1件は対応3で今後自己回復見込み

## 未対応メモ
- 直近の revise はほぼ全件「送料profileのみ変更(policy_change)」。DDP送料テーブルの
  閾値が行き来してる可能性 → 別途調査候補 (今回スコープ外)
