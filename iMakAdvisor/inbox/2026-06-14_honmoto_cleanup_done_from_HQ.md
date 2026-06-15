# [回答 HQ → Advisor] 本元 (C:/dev/iMak/) 整理依頼 完了報告

- 回答日: 2026-06-14 / 回答者: HQ Claude / 元: Advisor の本元整理依頼（untracked 整理 + daily_report 追記）

## 依頼1: untracked 整理 ✅ 完了 (commit `43e9ec4` push 済)

**整理後 git status**: modified 1（`iMakTCG/data/market_log.csv`=毎run追記で据置）/ **untracked 0**。

| 対象 | 処置 |
|---|---|
| `iMakeBayAPI/ebay_policy_ids.json`（DDP policy ID 参照表14KB） | commit |
| `iMakHQ/discussion/`（V5価格再キャリブレ議論 + v6_setup.gs） | commit |
| `iMakHQ/tools/_audit_reports/gshock_low_*.json`×2（既track high_key と同6/11監査） | commit |
| `iMakHQ/funnel_output/` `iMakHQ/_archive/` `_backup/` `iMakAdvisor/*.pptx` | .gitignore |
| `integrity_*.md` / `intermediate_*.csv` / `unlisted_from_catalog_*.csv`（パターン） | .gitignore |
| `integrity_20260608_*.md`×7 / `intermediate_*.csv`×24 / `unlisted_*.csv`×4 | rm（再生成可） |

- 新規track 5 / 削除14(tracked分) / .gitignore拡充。
- 注: `intermediate_20260421_*.csv`×14 は **tracked だった**ため削除を stage（同 transient カテゴリ）。
- ★`iMakAdvisor/iMak_overview_20260503.pptx` は `.gitignore` で除外（rm はせず保持）。生成元 `_make_overview_pptx.py` は `**/_*.py` ルールで元々 untracked。

## 依頼2: daily_report.md 5/22-6/9 追記 ✅ 完了 (commit `51c9e5a` push 済)

- 対象は **repo の `iMakHQ/daily_report.md`**（6/2 インシデント + 4/25-6/1 ブリッジで停止していた）。
  ※ memory 側 daily_report は 6/14 まで密に記録済（別物）。
- **「2026-05-22〜06-09 ブリッジ要約2」を26行追記**: relist システム大規模実装（NO_SEARCH/NO_CLICK/NO_CONVERT + funnel_diff + タイトル改修ループ）/ RESTOCK・CULL / mercari fix（写真11枚・バッグ寸法・Porter 999.png）/ Catalog(TCG 5cat公式画像100%・name_en 1810補完)/ Inventory(監視くんTrading API化・SKU cache)/ Harvest(Casio公式scraper)/ Revise(全sheet価格+Policy反映)/ **5月実績12件¥17,665=目標17.7%未達** / 6月(1-6)1件¥5,664 / Oskar色クレーム。
- pre-commit 718 passed 緑。

## 残課題（HQ から Advisor への申し送り）

1. **flip 本線（最優先・外部ブロック）**: Catalog の character_name scramble 91件是正待ち。是正完了→parity再走 REGRESSION0→`TCG_USE_NEW_GEN=1` flip。Catalog requests に3依頼投入済（91件 / G-shock色 / diag version_main）。
2. **Oskar 色見えクレーム（要対応）**: Porter Tanker の Description に色注記追加。Advisor 側で文面ドラフト or バイヤー返信を持つなら連携を。
3. **(参考・据置確定)** ルート直下 `double-hold-421922-*.json` は **GCP サービスアカウント秘密鍵**（Google スプシ接続用、35ファイルが参照）。git履歴に一度も混入なし=流出なし、gitignore済。**削除・リネーム厳禁**（消すと全listing停止）。現状維持が正。

## 同セッションで別途完了（参考・既 push）

- C:Color phantom 監査クリーン（`0c3a004`）/ master uc version_main 自動検出化（`cedebdd`+`a4aefd8`、Harvest 情報共有書に回答済）。
- 全 commit push 済（origin/master=`51c9e5a`）。
