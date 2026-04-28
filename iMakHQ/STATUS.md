# iMak Trading Japan - 現在のステータス

**最終更新**: 2026-04-27 セッション

---

## 全体の稼働状況

| プロジェクト | 価格計算 | CSV出力 | 品質チェック | スプシ連携 | 公式DB |
|---|---|---|---|---|---|
| iMakTCG | ✅ SSOT | ✅ 中央 | ✅ + 3AI | certs.txt | ✅ iMakCatalog (One Piece) / Pokemon DB |
| iMakG-shock | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 | - |
| iMak_ichibankuji | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 | - |
| iMakMercari / Tshirt | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 | - |
| iMakMercari / Montbell | ✅ SSOT | ✅ 中央 | ✅ | ✅ スプシN列 | - |
| iMakMercari / 汎用 | ✅ SSOT | ✅ 中央 | ✅ | 商品管理シートCSV | - |
| **iMakCatalog** | - | - | - | - | ✅ Phase 0 完了 / Phase 1 (One Piece) 稼働中 |
| **iMakAudit** | - | - | - | - | 独立実装監査部隊 (Claude + Gemini 2段) |
| **iMakAdvisor** | - | - | - | - | 相談相手 (バイヤー対応・雑談・アイディア) 2026-04-26 開設 |

## 主要ファイル配置

- **SSOT（価格）**: `iMakeBayAPI/pricing_engine.py` (TIER_PARAMS / 市場乖離率) ← `iMakeBayAPI/config/global.yaml` (手数料率・為替・送料)
- **SSOT（旧形式）**: `iMakeBayAPI/profit_params.py` ← `iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx`
- **共通基盤（CSV/PDF）**: `iMakeBayAPI/listing_core.py`
- **品質チェック**: 各プロジェクト `listing_validator.py` (3AI = Claude/Gemini/Groq 議論)
- **CSV出力先**: `iMakHQ/csv_output/`
- **監査ログ**: `iMakAudit/audit_logs/`
- **マトリクス**: `iMakHQ/sheets/プロジェクト処理マトリクス_20260415.xlsx` (随時更新)
- **decision_log**: 各プロジェクト `data/decision_log/*.jsonl` (Step 8 で全実装)
- **iMakCatalog DB**: `iMakCatalog/db/catalog.db` (SQLite)
- **iMakCatalog adapter**: `iMakCatalog/integrations/psa_to_csv.py` (旧 bandai_jp 形式に変換)

## 直近の重要決定事項（2026-04-15 〜 2026-04-27）

### 戦略・運用
- 戦略前提は **2026-04-15 確定版** (project_ebay_strategy.md) を維持
- KPI を**段階目標**に修正 (2026-04-27): 当面 月利益10万 / 中期 月利益30万 / 拡大しない
- Tシャツ/モンベルは自社ロジックのみで価格決定（eBay Active中央値を参照しない）
- タイトル生成時はカテゴリ別PDFキーワードを必ず参照
- Item Specificsは公式HPベース、TOPセラー参照、推測禁止
- 監査は「監査して」の一声でClaude + Gemini 2段実行
- **HQ ↔ Advisor 役割分離 (2026-04-26)**: HQ=実行屋、Advisor=相談屋

### 構造変更（Step 3-8 / 2026-04-25 制定）
- **Step 3-7 SSOT 抽象化完了**: pricing_engine.py / global.yaml / 4 check_csv の hardcode 撲滅
- **Step 4 ゴールデンテスト本番化**: byte一致 golden test を 4プロジェクト横断
- **Step 6 AI協調プロトコル明文化**: 3つの呪文 + バグ＝テスト追加運用
- **Step 6.5 pre-commit hook 物理強制**: テスト失敗で commit 拒否
- **Step 7 SSOT 抽象化拡張**: 4 check_csv の hardcode 完全殲滅
- **Step 8 decision_log 全実装**: 全 listing scriptで決定根拠を構造化記録

### 防御・補正レイヤー（既存ロジック非破壊で追加）
- **`card_identifier.py`**: PSA cert 画像 → Vision で「特定」(推測禁止、Finish 決定論)
- **`card_identification_agent.py`**: PSA / Vision / iMakCatalog の多角検証で card# 補正 (Phase 1-3)
- **`title_generation_agent.py`** (2026-04-26): NG語フィルタ + character 補完 + SEO スコアリング (Phase 1+2+3)
- **`catalog_authority_context.py`** (2026-04-26): iMakCatalog hit 時に 3AI へ catalog 信頼コンテキスト注入
- **`cert_overrides.json`**: 物理確認 or webfetch 確定済の手動補完 (skip / value-fill 両対応、現在 14 件)

### 直近の Bug fix
- **2026-04-26 cert #143570665**: canonical map 拡張で SNAD 防止強化 (PRB02-005 vs ST16-005 別カード誤マッチ事故)
- **2026-04-26 P-112 Nami "Pk Set"**: title_generation_agent NG語フィルタで Error 240 回避
- **2026-04-26 Bonney "#35"**: title_generation_agent #NN 剥がしで selfcheck PASS

## 進行中／要対応

### 高優先
- [ ] iMakCatalog Phase 1 拡充: One Piece TCG 全カード網羅 (現在 OP07-019 等で名前不一致 reject 残存)
- [ ] cert_overrides.json skip 5件の物理確認 → value-fill 化 (Shirahoshi SP / Chopper / Rebecca SP / Nami SP / Luffy PRB02)
- [ ] OP-14 set_name 表記揺れ問題の最終確認 (catalog 更新で自然解決済か実走で要検証)

### 中優先
- [ ] iMakCatalog Phase 2-4 着手 (Pokemon / DBSCG / Gundam)
- [ ] Hancock #142833357 価格 GATE 緩和 or 出品見送り判断
- [ ] スプシN列の実列名確認（想定「仕入れ価格（円）」）

### 低優先 / 整理
- [ ] 実出品での回帰テスト（1件流して旧出力と比較）
- [ ] 旧バックアップファイル（`*_pre_restructure.py`）の整理判断
- [ ] Fishing カテゴリをスプシv2に正式追加（現在ヴィンテージ玩具で代用中）
- [ ] 旧 OneDrive 系統 archive フォルダ群の最終削除判断 (2系統 archive 済)

## 最新の動作確認 (2026-04-27)

- iMakTCG PSA 走査: 16件 → 4件 CSV成功 (Bonney 2件救済 + Hancock タイトル修正成功)
- title_generation_agent: 3ケース全て期待通り改変 (CLI test + 実走 PASS)
- memory 統合完了: 旧3系統 → canonical 1系統 (`C--dev-iMak-iMakHQ/memory/`) 56 .md
- Gemini二次監査: 直近 DISPUTE 0件 / 虚偽申告なし

---

**操作**:
- 「監査して」 → Claude + Gemini 2段監査 (Step 1: implementation-auditor / Step 2: gemini_verifier.py)
- 「出品する」 → 各プロジェクトの listing script 実行（別途指示）
- 「進捗は？」 → このファイル + `memory/MEMORY.md` を読んで現状把握
- 「相談したい」 → iMakAdvisor で別セッション起動推奨 (`デスクトップ\iMakAdvisor 相談相手.lnk`)
