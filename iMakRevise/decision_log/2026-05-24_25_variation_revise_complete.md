# Revise Daily Report — 2026-05-24 / 2026-05-25

HQ ルール準拠 (決定 / 変更 / 検証 の 3 点セット)。

---

## 2026-05-24 — variation revise CSV format 確立 + V8 表記統一

### 決定事項
- 決定1: variation revise CSV は eBay 公式 doc 準拠 v4 (= Item row + Variation rows、 SKU 不要、 RelationshipDetails 必須) を採用
- 決定2: is_variation 判定を SKU OR Size OR Color に拡張 (= 監視くん SKU UUID 巡回前でも variation 認識可)
- 決定3: 混在 case (SKU 有/空欄共存) は SKU 空欄行を orphan として skip (= 21916664 防止)
- 決定4: 公式 sheet 全 size 同価格 case は snapshot 全 variation を同 new_usd で展開
- 決定5: スプシ P 列空欄でも title 推定でカテゴリ補完 (公式 default = Tシャツ(UT))
- 決定6: V7 → V8 表記統一 (print/log/skip-reason/import 関数名/test ファイル名)

### 変更
- 変更: revise/price_revise.py:725-737 — REVISE_VARIATION_PRICE_CSV_HEADER 5列化 (Action/ItemID/Relationship/RelationshipDetails/*StartPrice)
- 変更: revise/price_revise.py:741-816 — write_revise_variation_csv に variations_map 引数追加、 公式 mode + orphan skip 実装
- 変更: revise/price_revise.py:527-531 — is_variation 判定拡張 (SKU OR Size OR Color)
- 変更: revise/price_revise.py:1108-1122 — fail-closed (snapshot variation + スプシ row 不在 → skip with variation_no_sku_in_spreadsheet)
- 変更: revise/price_revise.py:1136-1142 — Step5 current_usd fallback (SKU空欄 + snapshot variation → 1つ目採用)
- 変更: revise/price_revise.py:300-318 — _infer_official_category_from_title 新規 (title→category 推定)
- 変更: revise/price_revise.py 全域 — V7→V8 rename (_import_v7_pricing → _import_v8_pricing、 v7_calc_failed → v8_calc_failed 等)
- 変更: tests/test_v7_smoke.py → tests/test_v8_smoke.py rename + 内容更新
- 変更: tests/test_variation_revise.py — 公式形式 v4 対応 + orphan skip テスト追加

### 検証
- 検証✅: pytest tests/ → 125 passed
- 検証✅: 本番 upload 19:18 → price 25 ItemID + shipping 25 ItemID、 Failure 0、 21916618=0
- 検証✅: 19:35 再 upload → price 51 (前回4件Failure→今回 Warning反映済) + shipping 51、 Failure 0
- 検証✅: 21:35 公式 spreadsheet SKU 追加後 dry-run → 366 variation 行生成

---

## 2026-05-25 — 公式在庫 + 前期価格 + 反映検証

### 決定事項
- 決定1: 公式 I 列 (仕入元在庫) ✕ なら revise 対象から除外 (= 在庫切れ商品の価格更新は不要、 売れたら欠品 = Defect Rate 直撃 回避)
- 決定2: 公式 Q 列 (前期仕入元価格) を AH 相当に流し、 HIGH/LOW と同じ仕入変動検出 logic で処理
- 決定3: 監視くんに Trading API GetSellerList 利用方法を依頼書経由で共有 (= sys.path import 推奨)

### 変更
- 変更: revise/price_revise.py:122 — COL_OFFICIAL_STOCK = 8 (I 列) 追加
- 変更: revise/price_revise.py:124 — COL_OFFICIAL_PREV_COST = 16 (Q 列) 追加
- 変更: revise/price_revise.py:286-301 — _normalize_official_row に stock=✕→sold_flag 流し + prev_cost→AH 流し追加
- 変更 (外部): C:/dev/iMak_data/inventory/requests/2026-05-25_ebay_active_listings_csv_dl_method.md — 監視くんへの依頼書投入

### 検証
- 検証✅: 公式 dry-run eligible 508 → 375 (= I=✕ で 133 件除外)
- 検証✅: 14:30 本番 upload → combined 321 + variation price 46 + variation shipping 46、 Failure 0
- 検証✅: 14:50 fresh snapshot (4257 listings) 取得 → upload 内容と突合 全件一致 (single 321/321 + variation 46/46)
- 検証✅: 21916618 = 0、 21916664 = 0、 Critical Failure = 0
