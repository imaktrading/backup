# CSV 出力 保管ポリシー (2026-08-11 制定)

## 絶対ルール — 削除しない

`iMakHQ/csv_output/*_upload_YYYYMMDD_HHMMSS.csv` および同 basename の
サイドカー (`*_cost.json` / `*.canonical.json` 等) は **削除しない**。

## Why

契約 v1.2 (2026-08-10 co-sign) で確定した SSOT 契約:
出品時点のスナップショット原本は
「入稿 CSV + eBay GetItem 現在値」の**2点セット**で再構築する運用にした。

- 別台帳 (出品時点 snapshot DB) は**作らない** (二重管理を避ける)
- 代わりに、生成 CSV = **不変の原本**として保管する

CSV を消すと「その時点で何を出したか」を復元できなくなる。特に:
- 出品後の SNAD クレーム調査 (出品時 spec と実物の照合)
- rarity/set 表記の retroactive 監査
- pricing/shipping 判定の再計算 (v8_GS 変更前後の diff)
- Item Specifics ゲート (canonical PID / master 突合) の regression 追跡

いずれも入稿時 CSV が消えると根拠を失う。

## 例外 (削除してよいもの)

- `*_TEST_*.csv` — 手元動作確認用の一時ファイル (レビュー完了後)
- `*_debug_*.csv` — デバッグ出力 (原本ではない)
- **上記 2 パターン以外は絶対に削除しない**

## Do

- 容量が気になる → **圧縮**する (`*.zip` にする)。削除しない。
- OneDrive/git-lfs へ移す → OK (原本が残るなら)。
- 古い CSV を年月別サブフォルダに整理する → OK (削除でなく移動)。

## Don't

- `rm iMakHQ/csv_output/*_upload_*.csv` — **禁止**
- 「もう入稿済だし要らない」→ **禁止** (SNAD/監査で後から遡る)
- Excel で開いて上書き保存 → **禁止**
  (ScheduleTime 形式破壊 + cp932 化で ErrorCode 37 全件失敗。memory
  `never_open_csv_with_excel.md` 参照)

## 契約参照

- `C:\dev\iMak_data\hq\requests\2026-08-10_ssot_contract_cosign_snapshot_on_listing_response.md`
  §「CSV は削除しない を運用 policy として明文化してください。スナップショット原本になるため」
- `C:\dev\iMak_data\hq\requests\2026-08-10_catalog_tcg_ssot_interface_contract_all_categories_response.md`
