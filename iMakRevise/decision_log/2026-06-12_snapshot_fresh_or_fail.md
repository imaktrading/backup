# Revise Daily Report — 2026-06-12

HQ ルール準拠 (決定 / 変更 / 検証 の 3 点セット)。

---

## 2026-06-12 — snapshot fresh-or-fail 化 (= fail-OPEN 解消) + clean 再走

### 決定事項
- 決定1: snapshot DL 失敗時の silent stale fallback (= 古い CSV で続行) を廃止、 fresh-or-fail 化
- 決定2: DL 失敗時 `ipconfig /flushdns` + retry 3 回 (= DNS hiccup 自動復旧)、 尽きたら `SnapshotFetchError` で run 中止
- 決定3: 採用 snapshot の mtime > 6h なら拒否 + 警告 + 中止 (= 二重防御、 既存 snapshot 経由でも stale を使わせない)
- 決定4: cron 開始の段取りは User 判断保留、 Revise から勝手に仕掛けない (HQ 完了報告通り)

### 変更
- 変更: revise/price_revise.py:41-49 — `subprocess` / `time` import 追加
- 変更: revise/price_revise.py:981-983 — `SNAPSHOT_DL_RETRIES=3` / `SNAPSHOT_DL_RETRY_INTERVAL_SEC=2.0` / `SNAPSHOT_FRESHNESS_MAX_AGE_SEC=21600` 定数
- 変更: revise/price_revise.py:986-987 — `SnapshotFetchError` 例外定義 (= run 中止 sentinel)
- 変更: revise/price_revise.py:990-1003 — `_flush_dns_cache()` 新規 (Windows ipconfig /flushdns)
- 変更: revise/price_revise.py:1006-1057 — `fetch_and_save_snapshot()` 改修 (retry + raise、 silent return None 廃止)
- 変更: revise/price_revise.py:1060-1078 — `_check_snapshot_freshness()` 新規 (mtime ガード)
- 変更: revise/price_revise.py:1198-1207 — 既存 snapshot 採用経路で mtime チェック + missing/stale で即中止
- 新規: tests/test_snapshot_fresh_or_fail.py (6 case)

### 検証
- 検証✅: pytest tests/test_snapshot_fresh_or_fail.py → 6/6 pass
  - case1 DL 成功 → 正常 path 返却
  - case2 retry 復旧 (call_count=2 で確認)
  - case3 retry 尽き → SnapshotFetchError raise (= "3 回 retry 尽き" メッセージ確認)
  - case4 stale (mtime 7h 前) → SnapshotFetchError raise (= "7." h 報告確認)
- 検証✅: fresh snapshot で再走 → revisable 805 / aligned 103 / policy_change 437 / price_diff 368 / not_in_snapshot 106 (古い 5/29 比 -134、 真の乖離 +82)
- 検証✅: 利益¥ 805 件 全件黒字、 中央値 ¥2,200、 最小 ¥300、 最大 ¥6,776
- 検証✅: HQ 独立検証 + user 手動 UP → FileExchange 結果 805 件 Error 0 / Failure 0 で完全反映
- 検証✅: policy 警告 21920363 / 21920362 は Revise 側原因なし (= 出品くん側 Return/Payment policy のマッピング)、 HQ 検証で撤回確定

---

## 残課題 (= 別 cycle 低優先)
- normalize 旧→新 Policy alias 解決 (DDP-39 ↔ DDP-A-P05) — 旧 format 残 listing が revise されるのは意図通り
- 公式 168 件 cost 不明 — 監視くん巡回不足
- v8_calc_failed 3 件 — yaml category 未マッピング
- cron 開始時刻 / モード — HQ↔User 段取り確定後着手
