# iMak Trading Japan - 現在のステータス

**最終更新**: 2026-04-15 セッション

---

## 全体の稼働状況

| プロジェクト | 価格計算 | CSV出力 | 品質チェック | スプシ連携 |
|---|---|---|---|---|
| iMakTCG | ✅ SSOT | ✅ 中央 | ✅ | certs.txt |
| iMakG-shock | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 |
| iMak_ichibankuji | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 |
| iMakMercari / Tshirt | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 |
| iMakMercari / Montbell | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 |
| iMakMercari / 汎用 | ✅ SSOT | ✅ 中央 | ✅ | 商品管理シートCSV |

## 主要ファイル配置

- **SSOT（価格）**: `iMakeBayAPI/profit_params.py` ← `iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx`
- **共通基盤（CSV/PDF）**: `iMakeBayAPI/listing_core.py`
- **品質チェック**: 各プロジェクト `listing_validator.py`
- **CSV出力先**: `iMakHQ/csv_output/`
- **監査ログ**: `iMakAudit/audit_logs/`
- **マトリクス**: `iMakHQ/sheets/プロジェクト処理マトリクス_20260415.xlsx`

## 直近の重要決定事項

- Tシャツ/モンベルは自社ロジックのみで価格決定（eBay Active中央値を参照しない）
- タイトル生成時はカテゴリ別PDFキーワードを必ず参照
- Item Specificsは公式HPベース、TOPセラー参照、推測禁止
- 監査は「監査して」の一声でClaude + Gemini 2段実行

## 進行中／要対応

- [ ] 実出品での回帰テスト（1件流して旧出力と比較）
- [ ] スプシN列の実列名確認（想定「仕入れ価格（円）」）
- [ ] 旧バックアップファイル（`*_pre_restructure.py`）の整理判断
- [ ] Fishing カテゴリをスプシv2に正式追加（現在ヴィンテージ玩具で代用中）

## 最新の動作確認 (2026-04-15)

- 12スクリプト全てのimport OK
- profit_params SSOT: 21カテゴリ読込、全カテゴリ min_price 計算OK
- Gemini二次監査: DISPUTE 0件 / 虚偽申告なし

---

**操作**:
- 「監査して」 → Claude + Gemini 2段監査
- 「出品する」 → 各プロジェクトの listing script 実行（別途指示）
- 「進捗は？」 → このファイルを読んで現状把握
