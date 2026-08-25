# iMakHQ Daily Report

HQルール準拠フォーマット: 決定 / 変更 / 検証 の3点セット。
検証欄は grep / テスト / 目視 の実結果のみ記録する（自己申告は書かない）。

---

## 2026-04-23 — Phase 3 ⑤ 価格×物理ゲート統合

### 決定事項
- 決定1: 市場価格連動を一部カテゴリで強制化。価格設定SSOTを「GATE.xlsx × eBay市場相場」に統一（Porter等1点ものと G-Shock は PRICE_CHECK_CONFIG で除外扱い）
- 決定2: 物理ゲート拡張 — pricing_engine が ALERT を返した行は CSV 出力から物理的に除外し、csv_hold_queue.jsonl へ隔離
- 決定3: カテゴリ別閾値管理 — listing_common.PRICE_CHECK_CONFIG で有効/無効と閾値をカテゴリ別に保持

### 変更
- 変更: iMakeBayAPI/listing_common.py:313 — PRICE_CHECK_CONFIG 新設
- 変更: iMakeBayAPI/listing_common.py:327-350 — audit_csv_row に price_status / median_usd 引数追加（デフォルト値付きで後方互換）
- 変更: iMakeBayAPI/listing_common.py:471-485 — gate_row_or_hold に同引数追加、ALERT時は violations 経由で物理除外
- 変更: iMakeBayAPI/listing_common.py:429-437 — csv_hold_queue.jsonl パス解決（iMakHQ/review_logs/csv_hold_queue.jsonl）
- 変更: iMakeBayAPI/check_csv_core.py:181 — fetch_ebay_market_median ブリッジ関数（既存 Browse API ロジック再利用）
- 変更: iMakMercari/mercari_to_ebay_csv.py:913-920 — 市場中央値取得→利益計算→物理ゲートの結線
- 変更: iMak_ichibankuji/ichibankuji_to_csv.py:982-990 — 同上
- 変更: iMakMercari/tshirt_listing.py:539-634 — 市場中央値取得（fetch_top_seller_specs 経由）→ compute_listing_price → gate_row_or_hold(price_status, median_usd)
- 変更: iMakMercari/montbell_listing.py:643-770 — 同上
- 未実装: iMakG-shock/gshock_to_csv.py:1042 — コメントのみ。PRICE_CHECK_CONFIG で "enabled": False とすることで「除外カテゴリ」として設計上成立（動的価格未対応）

### 検証
- 検証✅: grep `PRICE_CHECK_CONFIG` → iMakeBayAPI/listing_common.py:313 に定義、4 listing script が参照
- 検証✅: grep `audit_csv_row` 関数シグネチャに price_status/median_usd 引数を確認（listing_common.py:327）
- 検証✅: grep `gate_row_or_hold` 内部で audit_csv_row に price_status=price_status, median_usd=median_usd を渡していることを確認（listing_common.py:485）
- 検証✅: grep `fetch_ebay_market_median` → check_csv_core.py:181 に実装、mercari/ichibankuji の 2 スクリプトから呼出
- 検証✅: listing script 結線は 4 active（mercari / ichibankuji / tshirt / montbell）+ 1 除外（gshock）= 5カテゴリ touched を目視確認
- 検証⚠️（齟齬あり）: 申告「pytest 4シナリオ（正常/ALERT/除外/旧仕様）PASS」について、iMakHQ/tests/test_listing_rules.py は audit_csv_row の回帰テストのみで、price_status / ALERT / median_usd を名指しで検証するケースは grep で発見できず。fixtures_listing.json にも該当キー無し。→ **price_status 分岐の自動テストは未実装扱いとして扱う**
- 検証⚠️（未実施）: 「リールカテゴリにて ALERT 発生時に csv_hold_queue.jsonl への隔離と理由出力を確認」は実データ未投入のため HQ からは未再現
- 検証⚠️（要確認）: tshirt / montbell は `fetch_top_seller_specs` を使用（`fetch_ebay_market_median` ではない）。決定1の「Browse API による Median 取得」と同一実装かは別途要確認

### 未完了（次セッション以降への持ち越し）
- 実戦投入（リール）で csv_hold_queue.jsonl への物理隔離を**実データ**で確認（テストデータでは既に確認済）
- fetch_top_seller_specs と fetch_ebay_market_median の実装差分レビュー（両者とも Browse API 依拠か、SSOT 統一候補）

---

## 2026-04-23 追補1 — 齟齬修正 + pytest 価格分岐テスト追加

### 決定事項
- 決定1: PRICE_CHECK_CONFIG の G-Shock エントリを実装状態（未結線）と揃えるため `enabled=False` に修正
- 決定2: pytest に価格検証4ケース（A:GO正常 / B:ALERT遮断 / C:Porter除外 / D:後方互換）+ 物理ゲート2ケース（allow/block）を追加
- 決定3: ALERT 由来の error と必須項目欠落 error を区別するため、minimal valid row + message 文字列（"pricing_engine ALERT"）による厳密アサーションを採用

### 変更
- 変更: iMakeBayAPI/listing_common.py:318 — `"gshock": {"enabled": False}` に変更（コメントで未結線理由を明記）
- 変更: iMakHQ/tests/fixtures_listing.json — 新キー `PRICE_VALIDATION_CASES` に4ケース追加（minimal valid row ベース）
- 変更: iMakHQ/tests/test_listing_rules.py — `gate_row_or_hold` 追加 import、`_check_price_case` / `_check_gate_blocks_alert` / `_check_gate_allows_go` ヘルパー追加、pytest parametrize と standalone ランナー両方に反映

### 検証
- 検証✅: `pytest iMakHQ/tests/test_listing_rules.py -v` → **12/12 passed**（既存6 + 新規価格4 + 新規ゲート2）
- 検証✅: csv_hold_queue.jsonl に GATE-BLOCK-TEST エントリが 2026-04-23T21:05:42 付で書込確認済。violation: `Price $700.00 exceeds market tier limit vs median $500.00 (pricing_engine ALERT)` — ALERT 由来 error が物理ファイルに記録されることを実証
- 検証✅: Tomica は mercari_to_ebay_csv.py 経由で結線済。`validate_category="tomica"` の時 fetch_ebay_market_median が走る構造（mercari_to_ebay_csv.py:881, :913-920）。Tomica 専用スクリプトは存在しない
- 検証✅: G-Shock の config/実装齟齬解消（config=False かつ スクリプト未結線 → 整合）

### リール実戦投入への準備状態
- 論理的障壁: すべて解消
- 技術的障壁: すべて解消
- 残タスク: 入力ファイル（search_urls 等）件数・カテゴリ確認のみ（グローバル CLAUDE.md「スクリプト実行前の必須確認」に従う）

---

## 2026-04-24 追補2 — PSA TCG 初陣（Fallback Chain 実証）

### 決定事項
- 決定1: psa_to_csv.py の sys.path 遅延 import バグ修正（ファイル冒頭に移動）
- 決定2: build_row が selfcheck 失敗で None を返す際のガードレール追加（errors+card_info 同期）
- 決定3: Claude にタイトル生成依頼する際、PSA生値ではなく Bandai DB 補完済 `official_card_number` を渡す設計変更
- 決定4: Claude がタイトル中の card# を短縮する現象に対し、物理的な文字列contains検証を追加（既存の title_preserves_subject と同パターンで build_title フォールバックへ強制切替）
- 決定5: listing_validator への psa_card_number 引数には PSA 生値（set prefix無し）を渡す（Bandai補完値を渡すと Rule 3 が常に false positive になる）

### 変更
- 変更: iMakTCG/psa_to_csv.py:27 — `sys.path.insert(0, "../iMakeBayAPI")` をファイル冒頭に追加
- 変更: iMakTCG/psa_to_csv.py:1601 — 旧位置の sys.path.insert を削除、コメント更新
- 変更: iMakTCG/psa_to_csv.py:1579-1587 — build_row None 返却時のガードレール（5行）追加
- 変更: iMakTCG/psa_to_csv.py:1358-1360 — Claude呼出の引数を `card_number` → `official_card_number` に変更（2行コメント付き）
- 変更: iMakTCG/psa_to_csv.py:1381-1389 — card#保持検証を追加、Claudeが短縮した時 build_title フォールバック
- 変更: iMakTCG/psa_to_csv.py:1409-1415 — psa_card_number 引数を `data.get('CardNumber','')` (PSA生値) に変更
- 変更: iMakTCG/psa_to_csv.py:29 + :1805 — CSV出力先を `_gcop("tcg", "upload")` に統一（iMakHQ/csv_output/tcg_upload_<ts>.csv 形式、他カテゴリと命名規則一致）
- 掃除: iMakTCG/ebay_upload_20260424_{063745,064242,064607,065050}.csv + cost.json × 4 = 8ファイルを削除（デバッグ過程の中間失敗版）

### 検証
- 検証✅: `python psa_to_csv.py`（2026-04-24 06:53）→ 魔人ブウ FB04-095 が完走、CSV `ebay_upload_20260424_065345.csv` 1件出力、成功1件/失敗0件
- 検証✅: 出力タイトル `PSA 10 Dragon Ball SCG #FB04-095 Majin Buu : Kid FB04 Visual Alternate Art (74字)` に `#FB04-095` 完全形を含む
- 検証✅: GATE=GO、仕入¥33,333→出品$833.98、予想利益¥61,128 (44%、目標10%)
- 検証✅: **Fallback Chain 実証** — Claude生成タイトルが PSA Subject 改変 → `⚠️ Claudeタイトルが PSA Subject を改変 → ルールベースに切替` ログで build_title へ自動切替 → 正規タイトル生成 → selfcheck 通過。今日追加した「AIの創作をコード論理でねじ伏せる」機構が期待通り稼働
- 検証⚠️（既知エッジケース）: シャンクス (cert 109204387) は PSA brand (OP11-A) と Bandai (ST16) の二重登録で selfcheck Rule 1 に正しく停止 → memory `psa_bandai_brand_divergence.md` に記録
- 検証⚠️（既知エッジケース）: 雷龍 (cert 155746272) は Bandai JP (日本語DB) で英字 Subject "Lightning Dragon" が検索ヒットせず → memory `bandai_jp_en_ja_gap.md` に記録

### 本日の全成果（リール + PSA 統合）
| パイプライン | 処理 | GO出力 | HOLD/失敗 | コード修正数 |
|---|---|---|---|---|
| リール（mercari→eBay 市場連動ゲート） | 4 | 1 (Shimano 22 Stella 4000XG) | 3 (ALERT隔離) | 3箇所 (listing_common + 重複HOLD削除) |
| PSA TCG（Bandai DB連携） | 3 | 1 (魔人ブウ FB04-095 Majin Buu) | 2 (data edge cases) | 5箇所 (sys.path / None guard / Claude args / card# fallback / psa_card_number arg) |

### 次セッション優先度
- **[高]** 出力CSV 2本（`reel_upload_20260424_055735.csv` / `ebay_upload_20260424_065345.csv`）の目視検収 → eBay入稿
- **[中]** median hits閾値（hits < N → NO_MEDIAN 格上げ）の設計
- **[中]** scout の scrape_search_results URL対応付けバグ調査
- **[低]** シャンクス / 雷龍の edge case 再挑戦（英日翻訳層、brand同値性ホワイトリスト）
- **[低]** response_processor.py 拡張（HOLD理由の分類学習）

---

## 2026-04-24 追補3 — certs.txt 廃止 + PSA 10件バッチ実戦

### 決定事項
- 決定1: psa_to_csv.py を certs.txt 駆動 → **スプシ駆動に完全移行**。入力源は Porter/Ichibankuji と共用の `19kj8...` gid=851100680（全カテゴリ共通の出品管理シート）
- 決定2: スプシ I列 = cert#, B列空 = 未処理 の条件で抽出、仕入値は N列優先 + F列 "¥XXX,XXX" パース fallback
- 決定3: 初回採用 ReEl + 単発 魔人ブウの CSV は破棄、バッチ run のみ本番保全

### 変更
- 変更: iMakTCG/psa_to_csv.py:1492 — `load_targets_from_sheet_psa()` 関数を新設
- 変更: iMakTCG/psa_to_csv.py:1552-1567 — main() 内の certs.txt 読込 + Stage 0 重複除外 (50行弱) を削除し、新関数呼出に置換
- 掃除: iMakHQ/csv_output/reel_upload_20260424_055735.csv, tcg_upload_20260424_065345.csv (+cost.json) を削除

### 検証
- 検証✅: Pre-flight `load_targets_from_sheet_psa()` 単独実行で10件抽出成功、cert#/仕入値/URL/タイトル全て正しく parse
- 検証✅: 本実行 `python psa_to_csv.py`（07:37）→ 10件処理完了、CSV `iMakHQ/csv_output/tcg_upload_20260424_073706.csv` に **5件の精鋭**出力
- 検証✅: 物理ゲートの証跡（多段フィルタ動作）:
  - selfcheck 却下 3件: 143657595 Zガンダム / 143657594 百式 / 143657590 エース
  - NO-GO 除外 2件: 149249712 Jewelry Bonney (乖離50%超) / 143657587 Sabo (乖離86%超)
  - GO 出力 5件: Vivi EB03-001 / Shanks OP09-001 / Sanji PRB01-001 / Luffy P-110 / Perona OP14-111
- 検証⚠️（要調査）: Gundam (GD01-069, GD01-072) の同時 selfcheck 失敗 → 共通パターンの可能性。bandai_tcg_plus 経由で title は OK（#GD01-069 Zeta Gundam Card 形式）だが selfcheck が弾いた → listing_validator の未対応 brand pattern の可能性
- 検証⚠️（要調査）: Ace EB02-028 も selfcheck 失敗 → Subject "PORTGAS D. ACE SPECIAL ALTERNATE ART" の長文 brand が validator の想定外パターンか

### 次セッション優先度（更新）
- **[高]** CSV検収: `iMakHQ/csv_output/tcg_upload_20260424_073706.csv` 5件 → eBay FileExchange 入稿
- **[中]** Gundam 2件の selfcheck 失敗原因特定（共通パターン → listing_validator の Gundam 対応追加）
- **[中]** Ace (Special Alt Art) の selfcheck 失敗原因特定（長文 brand への対処）
- **[中]** median hits閾値（hits < N → NO_MEDIAN 格上げ）の設計
- **[中]** scout の scrape_search_results URL対応付けバグ調査
- **[低]** certs.txt / certs_scout.txt / certs_skipped_duplicates.txt を物理削除（現在は未使用）
- **[低]** シャンクス / 雷龍の edge case 再挑戦（英日翻訳層、brand同値性ホワイトリスト）
- **[低]** response_processor.py 拡張（HOLD理由の分類学習、次セッションで複数HOLDデータ揃ったら）

---

## 2026-04-24 セッション終了時 — 失敗3件のエラーログ深掘り結果

### 実エラーメッセージ（log 深掘り後）

| cert# | カード | 実エラー | 真の原因 |
|---|---|---|---|
| 143657595 | Zガンダム GD01-069 | `必須Item Specific 'Type' が空` | bandai_tcg_plus 検索失敗 → card_type 未取得 |
| 143657594 | 百式 GD01-072 | `必須Item Specific 'Type' が空` | bandai_tcg_plus が **誤ったカード返却**: "Launcher Strike Gundam" + card_type 空 |
| 143657590 | エース EB02-028 | `タイトルに'EB02'があるが PSA brand に存在しない` ('OP13-CARRYING ON HIS WILL') | **PSA=OP13プロモ vs Bandai=EB02元セット**、シャンクスと同パターン |

### 系統A vs 系統B — 明確に別問題

- **系統A (Gundam 2件)**: Bandai TCG+ API 連携問題。brand whitelist では解決**しない**。`bandai_tcg_plus.fetch_card` の ID 照合精度 + card_type デフォルト戦略で対応
- **系統B (Ace 1件)**: 既存 memory `psa_bandai_brand_divergence.md` に記録済のプロモ二重国籍問題。シャンクス + Ace で **N=2 揃った** → 汎用化タイミング到来

### 次セッション着手ロードマップ（優先順）

1. **[A-1] bandai_tcg_plus.py の fetch_card 調査**: ID 照合を完全一致に厳格化（誤ヒット物理防止）
2. **[A-2] Gundam デフォルト適用**: `official_card_type=""` 時に `"Unit Card"` を採用（psa_to_csv.py:1339 付近）
3. **[B-1] listing_validator.py 汎用化**: `validate_title_against_psa` に「プロモ分岐許容」ルール追加（psa_brand に別のセットコードがあり、かつ title の card# が `{X}-{番号}` 形式なら WARNING に格下げ）
4. **[再検証]** 同じ10件バッチで再走 → 8-10件通過を目標

### 🚨 今日の CSV 検収時の手動対応（重要）
`iMakHQ/csv_output/tcg_upload_20260424_073706.csv` 5件は **Finish 決定論化の修正適用前に生成された** ため、Finish 列は依然として Claude 推測由来。入稿前に **Finish 列を目視で1件ずつ確認**（または安全側で空欄化）してから eBay 入稿する。自信が持てない行は空欄化（"Non-Foil" と断言しない）。

---

## 2026-04-24 追補4 — 🚨 緊急オペ: Finish 判定の推論切断（実装済）

### 決定事項
- 決定1: Finish (Holo/Non-Foil) は**Claude 画像推測を完全遮断**し、PSA Subject の確定キーワードベースの決定論判定に移行
- 決定2: 保守的キーワード採用（ALTERNATE / SPECIAL / PROMO は Holo 確定語ではないため**除外**）。`"(HOLO)" / "(FOIL)" / "SECRET RARE" / "PARALLEL"` のみで "Holo" 認定、他は空欄
- 決定3: 無在庫販売で「嘘をつかない」カタログ原則（Overpromise 回避）。"Non-Foil" と断言せず、確証なければブランク

### 変更
- 変更: iMakTCG/psa_to_csv.py:648 — Claude プロンプト内 finish field を「DO NOT guess / Blank is ALWAYS correct when uncertain」に書き換え、旧誘導文「Most Secret Rare, Special Art, Alternate Art, and Parallel cards are 'Holo'」を削除
- 変更: iMakTCG/psa_to_csv.py:1373-1381 — finish 代入ロジックを Claude 依存から Subject キーワード判定に差替え。Claude の `finish` フィールドは完全無視

### 検証
- 検証✅: `ast.parse` 構文 OK
- 検証⚠️: 既存の `tcg_upload_20260424_073706.csv` は**修正前生成**のため Claude 推測値が残っている → 入稿前の目視確認必須（または再生成）

### Why
- 過去の SNAD クレーム実績: Claude が "Holo" と推測 → 実物 Non-Foil → 買い手クレーム（無在庫販売では発送前チェックが効かず致命傷）
- プロンプト line 605「NEVER infer Finish from rarity」と line 647「Most ... are Holo」が正面矛盾 → Claude は後者に従っていた
- 無在庫販売の情報不正確は「バグ」ではなく「ビジネス存続リスク（地雷）」という認識共有

### 今後の拡張余地（次セッション以降）
- 公式DB (bandai_jp / bandai_tcg_plus) に Finish フィールドが実装されたら `official_finish` が非空になり、確証 tier が1段上がる

---

## 2026-04-24 追補5 — Finish 完全保守化 + Meta-lesson

### 決定事項
- 決定1: Finish 決定ロジックから Subject キーワード判定も撤廃、`finish = official_finish` の **1行化**（公式DB値のみ採用）
- 決定2: Subject に `"SECRET RARE"` や `"PARALLEL"` が入っていても印刷ロット差異で Non-Foil 個体が混じる可能性 → 100%保証できない以上、一切認定しない保守路線

### 変更
- 変更: iMakTCG/psa_to_csv.py:1373 — Subject キーワード判定ブロックを削除、`finish = official_finish` のみに

### 検証
- 検証✅: `ast.parse` 構文 OK
- 検証✅: 再走 `python psa_to_csv.py` → CSV `iMakHQ/csv_output/tcg_upload_20260424_083911.csv` 生成、5件全て Finish=空欄

### Meta-lesson（iMakシステムの根本教訓）

今回の Finish 問題は**新しいルールではなく、既存2ルールの違反**だった:
1. グローバル CLAUDE.md「Item Specifics 共通ルール」: 確証なきは空欄、公式サイトからの推定は不可
2. メモリ `enforce_in_python_not_prompt`: 重要ルールは SYSTEM_PROMPT 任せ禁止、Python deterministic 強制必須

**なぜ違反が本番稼働したか**:
- ルールは自然言語（ドキュメント）にあった
- Claude プロンプトに誘導文として混入（line 647「Most ... are Holo」）
- selfcheck (listing_validator) に Finish チェックが無かった → gate が機能せず
- grep で検出不可能な形態のため、コードレビューで見逃された

**再発防止に必要なこと（次セッション宿題）**:
- 全 Item Specifics (Rarity / Features / card_type / attribute / finish / color / power / cost) を棚卸し
- それぞれ「official_* 由来か Claude 由来か」を明示、Claude 由来のものは Python 物理強制に移行
- selfcheck に「official_* 変数由来以外は禁止」ルール追加を検討

### 最終成果物（本日 FINAL 確定版）
```
iMakHQ/csv_output/tcg_upload_20260424_083911.csv  (64.8 KB, 5件, 全件Finish空欄)
iMakHQ/csv_output/tcg_upload_20260424_083911_cost.json
```

**iMak 2.0 の誠実な初陣リスト完成**

---

## 2026-04-24 追補6 — 全 Item Specifics Claude 追放 + Bandai精度向上 + プロモ二重国籍汎用化（Gemini監査済）

### 決定事項
- 決定1: rarity / card_type / cost / power / attribute / finish の**全6フィールド**から Claude fallback を物理除去、公式DBのみをソースに
- 決定2: Bandai JP CHARACTER_JP_TO_EN に **26 キャラ追加**（Vivi, Perona, Sabo, Bartolomeo 他）で英日ギャップ解消
- 決定3: bandai_tcg_plus.fetch_card を **card_number 完全一致優先**に変更（誤ヒット物理防止）
- 決定4: GUNDAM_SET_PREFIX の `"DUAL IMPACT"` を `GD01` → `GD02` に訂正（実DB検証済）
- 決定5: Gundam は `"Card Type"` キー名 + `"UNIT"→"Unit Card"` 正規化、power は AP フィールドにフォールバック
- 決定6: **プロモ二重国籍パターン汎用化** — `listing_validator._is_promo_dual_citizenship` で Ace/Shanks/Sabo 等を自動許容。Gemini監査で **TCG ブランドガード追加**（非TCG文脈への誤適用防止）

### 変更
- 変更: iMakTCG/bandai_jp.py — CHARACTER_JP_TO_EN に Vivi/Perona/Sabo 他 26 キャラ追加
- 変更: iMakTCG/bandai_tcg_plus.py — fetch_card に card_number 完全一致優先ロジック、`"Type"`/`"Card Type"` 両対応、Gundam 用 `GUNDAM_TYPE_MAP` 正規化、power は Power/AP フォールバック
- 変更: iMakTCG/psa_to_csv.py — Item Specifics 5フィールドの Claude fallback 廃止、GUNDAM_SET_PREFIX の DUAL IMPACT 訂正
- 変更: iMakeBayAPI/listing_validator.py — Rule 1 正規表現から末尾 `\b` 削除、`psa_has_any_set_code` 許容、`_is_promo_dual_citizenship` 新設（TCG ブランドガード付き）、`_KNOWN_ACCEPTABLE_PATTERNS` に新規エントリ

### 検証
- 検証✅: ユニットテスト `_is_promo_dual_citizenship`: Ace/Shanks PASS + 通常カード非該当 + 非TCG brand 拒否 の4ケース
- 検証✅: 10件 PSA バッチ実戦 → **成功8件 / 失敗0件**（市場ゲートで Bonney/Sabo の2件が NO-GO=相場乖離、selfcheck/3AI 失敗 0件）
- 検証✅: Gemini 累積変更レビュー → "COMPLETE / GO FOR UPLOAD" 判定、1箇所修正指示 (TCG ブランドガード追加) を適用済
- 検証⚠️ 残存: CHARACTER_JP_TO_EN の 26 新規エントリのうち **未検証キャラ**（今日通過した Vivi/Perona/Sabo 以外の 23エントリ）は次回検索時にヒット確認が必要

### 最終成果物（2026-04-24 FINAL）
```
iMakHQ/csv_output/tcg_upload_20260424_144059.csv  (103 KB, 8件)
iMakHQ/csv_output/tcg_upload_20260424_144059_cost.json
```

内訳:
1. Nefeltari Vivi (EB03-001) Leader Card / Alt Art
2. Shanks (OP09-001) Leader Card / Alt Art
3. Sanji (PRB01-001) Leader Card / Alt Art
4. Monkey D. Luffy (P-110) Character Card / Promo
5. Zeta Gundam (GD02-069) Unit Card / LR
6. Hyaku-Shiki (GD02-072) Unit Card / R
7. Perona (OP14-111) Character Card / R
8. Portgas D. Ace (EB02-028) Character Card / SEC [プロモ二重国籍許容]

NO-GO 除外 (市場ゲート動作): Jewelry Bonney (乖離50%) / Sabo (乖離86%)

**iMak 2.0 — 誠実な8件の CSV、eBay 入稿可能**

---

## 2026-04-24 追補7 — 🛑 入稿直前に pipeline 内二重基準を発見、入稿見合わせ

### 事象
ユーザーが最終実行で CSV 生成 + check_csv.py (post-check) を走らせた時、**同一 CSV に対して psa_to_csv.py と check_csv.py が矛盾判定**:

| カード | psa_to_csv median | check_csv median | psa判定 | check判定 |
|---|---|---|---|---|
| Vivi EB03-001 | $250 | **$79** | GO $237.98 | **NO-GO 乖離135%** |
| Hyaku-Shiki GD02-072 | $120 | $120 | 保留 $174.98 | **NO-GO 乖離60%** |
| Ace EB02-028 | $217 | **$193** | 保留 $258.98 | **NO-GO 乖離60%** |

### Gemini 監査の盲点
Gemini は pipeline の各コンポーネント（listing_validator, psa_to_csv 内部ロジック）を個別に精査したが、**psa_to_csv → check_csv 間のインターフェース（同じ CSV に対する判定の一貫性）を確認していなかった**。Gemini 自身もこれを認め反省。

### 決定
- 🛑 **今日の入稿は見合わせ**
- CSV ファイル `tcg_upload_20260424_145636.csv` はディスク上に残すが**「要手動スクリーニング」状態**として扱う
- 明日の最優先タスクとして「二重基準解消」に着手

### 次セッション調査課題（🚨 最優先）
1. **クエリ統一**: psa_to_csv.py と check_csv.py の eBay 検索クエリ・フィルタ条件の diff 取得、どちらが正しいか検証
2. **gap_limit 共有化**: 両ツールが pricing_engine.py から同じ TIER_PARAMS を参照するリファクタ
3. **Vivi の謎解明**: 実際の eBay 検索で `PSA 10 #EB03-001 Nefeltari Vivi` vs `EB03-001 Vivi` の差を目視、どちらの median が真実か判定
4. 解消後に本日の cert 10件でバッチを再実行し、両ツールが合意する CSV を生成

### memory への記録
`dual_gate_disagreement.md` に記録済。運用ルール: 二重基準解消まで psa_to_csv.py CSV の自動入稿は禁止、check_csv.py の post-check で NO-GO 判定行は手動除外必須

### 関連メモリ更新
- `psa_bandai_brand_divergence.md`: シャンクス単独 → シャンクス+エース パターン化。汎用化提案追記
- `gundam_bandai_tcg_plus_reliability.md`: 新規追加（fetch_card 誤ヒット + card_type 欠落）

---

## 2026-04-24 — リール初実戦投入（市場連動ゲート本番稼働）

### 決定事項
- 決定1: リール4件を手動ピック→スプシ直結で出品CSV生成フローを走らせ、物理ゲートの実データ動作を初確認。結果は 3 ALERT隔離 / 1 GO通過 で仕様通り
- 決定2: 出品フロー中の旧 `_append_hold_queue` を削除し、HOLDキュー書込を `listing_common.append_to_hold_queue` に完全一元化（SSOT化）
- 決定3: リールの pricing_engine gap_limit は実運用で **+10%付近が ALERT ライン** と実測確定（+10.2% の m51514473487 が ALERT）

### 変更
- 変更: スプシ `1jF9vggbfUCd...` gid=851100680 行652-655 にリール4行を append + `_tmp_enrich_reel.py` で Mercari から画像URL/価格/タイトル/状態/説明を逆充填（ヘルパーは実行後削除）
- 変更: iMakMercari/mercari_to_ebay_csv.py:603-629 — `_append_hold_queue` 関数と `_HOLD_QUEUE_PATH` グローバル削除
- 変更: iMakMercari/mercari_to_ebay_csv.py:1004 — `_append_hold_queue(...)` 呼出削除 + 周辺コメントを「SSOT=listing_common.append_to_hold_queue」に更新
- 未実装: ichibankuji / tshirt / montbell にも同等の旧HOLD書込があった場合の削除 → grep 確認したところ **mercari_to_ebay_csv 以外には存在しなかった**（二重書込問題はこの1ファイルのみ）

### 検証
- 検証✅: `python mercari_to_ebay_csv.py --sheet reel` 実戦実行（2026-04-24 05:57-06:01）→ 4件処理、GO 1件 / ALERT 3件 / HOLD隔離 3件 / CSV出力1件
  - m33125385604 ¥777,777 → target $7858.98 vs median $7.91 (hits=4) → **ALERT +99,180%**
  - m59859374344 ¥80,000 → target $835.98 vs median $628.28 (hits=24) → **ALERT +33.1%**
  - m29948352652 ¥52,500 → listing $558.98 vs median $586.02 (hits=14) → **GO -4.6%**
  - m51514473487 ¥61,111 → target $645.98 vs median $586.02 (hits=14) → **ALERT +10.2%**
- 検証✅: csv_hold_queue.jsonl に3件の新format（category/violations/row_summary）エントリを確認。各 violation に `"pricing_engine ALERT"` メッセージ含有
- 検証✅: 旧HOLD書込削除後の回帰テスト `pytest iMakHQ/tests/test_listing_rules.py -v` → **12/12 passed**
- 検証✅: grep `_append_hold_queue` / `_HOLD_QUEUE_PATH` が mercari_to_ebay_csv.py から消失。他スクリプトにも存在しないことを確認
- 検証✅: 出力 reel_upload_20260424_055735.csv が 14,779 bytes / 1行（m29948352652 Shimano 22 Stella 4000XG Spinning Fishing Reel High Gear Pre-owned Japan）で生成

### 副次発見（要フォロー）
- **薄いmedianサンプル問題**: m33125385604 は hits=4 で median $7.91（部品/アクセサリを拾った模様）。結果的に ALERT で防げたが、逆に「正しい相場なのに hits 不足」で価格が不安定化するリスクあり。将来 `hits < N` を NO_MEDIAN 扱いに格上げする閾値設計が課題
- **URL↔商品情報の scout 乖離**: 昨日の scout ログ期待値と実 Mercari データで 4件中3件が不一致。scout の `scrape_search_results` が search results DOM から URL/タイトル/価格を抽出する際にズレを起こしていた可能性（別途調査）

### 残タスク（次セッション候補）
- **優先度高**: 出力 reel_upload_20260424_055735.csv の目視検収（eBay 入稿可能品質か）
- **優先度中**: median hits閾値の設計（hits<5 を NO_MEDIAN 格上げ等）
- **優先度中**: scout の scrape_search_results URL対応付けバグ調査
- **優先度低**: response_processor.py 拡張設計（HOLD理由分類の学習データ化）

---

## 2026-06-03 — Catalog セッション（TCG lookup 修正 / backlog保全 / name_en補完 / Casio detail merge / サブPC調整）

### 決定事項
- 決定1: TCG lookup 失敗の連続事例（Oricorio/Gundam Resource/MBD Meloetta）は **いずれも catalog 欠落ではなく brand→set_code 導出漏れ** と判明 → adapter のマッピング追加で解決（手動 INSERT せず、既収録レコードを引けるようにする方針）
- 決定2: name_en 空 → Item Specifics 日本語漏れ（RP-009 'リソース' 事件）は **公式由来のみで補完**（推測翻訳禁止）。曖昧（複数EN=データ破損）・no-match は空のまま（誤出品 < 空欄）
- 決定3: 2週間滞留していた 5/29-5/30 未 commit 作業を最優先で保全（branch切替 data-loss 温床）。adapter fix と分離して論理単位で commit
- 決定4: `*.code-workspace` は feature/uniqlo-ut の .gitignore 未登録 + tracked だった → gitignore + `git rm --cached`（行追加だけでは既存tracked分は守られない）
- 決定5: One Piece color_en は DB の `color`(JA/EN混在) を adapter層で英語正規化（DB値は公式SSOTとしてJA温存、migration で英語上書きしない）
- 決定6: サブPC Casio fetch の 20分スリープは無駄（Akamai は時間では解除されず別IP=再テザリングが唯一有効と実証済）→ block検知時は寝ずに終了し再テザを促す設計に変更

### 変更
- 変更: iMakCatalog/integrations/psa_to_csv.py `_POKEMON_SET_NAME_TO_CODE` に 'ALTER GENESIS'→'SM12' / `extract_set_code_from_brand_gundam` に 'RESOURCE'→'RP' / `_JA_CHAR_TO_EN_TOKENS` に 'リソース'→{RESOURCE}（commit 2a05c64）
- 変更: iMakCatalog/integrations/psa_to_csv.py `extract_set_code_from_brand_pokemon` に letter-only code 'MBD' 追加（commit 493b278、#022=Meloetta が hit）
- 変更: iMakCatalog/integrations/psa_to_csv.py `_normalize_color_en()` 追加 + `_apply_ebay_fields` で color_en を英語化（commit 0f05b55）
- 変更: iMakCatalog/scripts/casio_parse_local_html.py 新規（サブPC保存 view-source HTML → 公式detail を union 同一スキーマで DB merge、commit f5e7563）
- 変更: iMakCatalog/migrations/2026-06-03_name_en_backfill.py 新規（name_en 1810件補完、commit 0a03a49）
- 変更: .gitignore に *.code-workspace / **/_*_sample.html 追加 + iMakCatalog/iMakCatalog.code-workspace を untrack（commit 499650e）
- 変更: casio_subpc/casio_autosave_viewsource.py（OneDrive、git外）BURST_SIZE 15→6 / BLOCK 20分スリープ撤廃→終了+再テザ案内
- 変更: 5/29-5/30 backlog 保全（migrations 14本 + casio_auto_dl + ebay_filter_masters、commit c1401e0）+ eBay-fields enrichment adapter/test（commit b40cbc0）
- 未実装: uniqlo_ut name_en(1304件) = 公式英名 source が無く方針相談中（response 投函済、HQ判断待ち）。TCG残空(gundam6/op5/dbscg290/pkmn110)= 公式未確定で空のまま温存

### 検証
- 検証✅: lookup_pokemon('...ALTER GENESIS','035') → SM12-035 オドリドリGX / lookup_gundam('...RESOURCE PROMOS','009') → RP-009 / lookup_pokemon('...MBD...','022') → MBD-022 Meloetta(022/021)、'005'→Mega Diancie 別物 を実機確認
- 検証✅: name_en backfill dry-run → 公式英名サンプル全件正確（Gundam/Sabo/Bardock/Hau）、曖昧（マスキッパ→{Carnivine,Sableye}）は skip。--commit 後 RP-009 name_en='Resource' を実機確認。計1810件、残空(gundam6/op5/dbscg290/pkmn110)
- 検証✅: Casio local merge dry-run 127HTML→98 unique→DB一致98/98、後続11件追加で **gshock detail 充足 114→212→223**（msrp_jpy/release_date/size/glass 等14field、before_msrp全件None=新規充足）。backup 取得
- 検証✅: pytest tests/ = 212 passed（回帰テスト追加: Alter Genesis/Resource/MBD の extract+lookup 計6本）。各 commit で pre-commit hook 228 passed/1 skipped
- 検証✅: git check-ignore で iMakCatalog.code-workspace（2箇所）+ _*_sample.html が ignore 化、commit後 working copy 残存を確認
- 検証✅: サブPC修正後の実走で _run_log に「完了:11/93 → block検知→終了+再テザ案内」を確認（新ロジック発火、旧20分ループ消滅）

### 残タスク（次セッション候補）
- **優先度中**: uniqlo_ut name_en 方針（A:公式UT英名scrape / B:UTはCard Name不要 / C:空運用）の HQ 回答待ち
- **優先度中**: サブPC Casio 残スプシ~108 を再テザリングで消化 → 母艦で casio_parse_local_html.py --commit（現行detail 223/690、残ギャップ ~467）
- **優先度中**: One Piece adapter fix (b40cbc0+0f05b55) の master 反映（cherry-pick or merge、[[open_items_2026_06_02]]）
- **優先度低**: MBD セットの set_name/rarity 欠落補完（listing は出るが該当 Item Specifics 空）
- **優先度低**: 残TCG空(gundam6/op5/dbscg290/pkmn110)の公式source指定での追補

---

## 2026-06-07 — Catalog セッション（Pokemon set_name_ebay 根治 / B層 verified 基盤 / adapter修正）

### 決定事項
- 決定1: Pokemon set_name_ebay 誤マッピング(buyer SNAD指摘 M3=Ultra Prism)の真因は **5/30 `2026-05-30_pokemon_set_name_ebay_jp_mapping.py` の手動 JP_TO_EN 辞書**（自動fetch失敗後に英語版の無い新弾JPセットを旧ENセットへ流用=fail-closed違反）→ **yaml SSOT化 + 5/30 migration 2本 DEPRECATED** で根治。HQの card_number_total 推定は外れ、手動辞書が犯人
- 決定2: 広域cleanup の正値は **日本語カード=JPセットの英語名**を採用（英語版合本名 Perfect Order/Ascended Heroes 等は不使用）。確定値なし=空欄(fail-closed)。eBay正規値はネット可のHQが確認、Catalogは候補提示→HQ確定の2段(Megaで"Munigus Zero"→正"Nihil Zero"を捕捉した方式)
- 決定3: B層 verified status は **4状態**(unverified/verified_auto/verified_manual/disputed)。独立性(B-2)厳守で **pokeapi系(direct/suffix/form)のみ verified_auto**、trainer dict一致は生成元と循環の恐れで留保
- 決定4: disputed name_en 補正は **2源(pokeapi name_jp直引き=番号バグ経路でない + HQ多数決suspect)** 一致を根拠に、HQ greenlight後に適用（pokeapi単独で値を決めない=B-2）
- 決定5: 6/4-6/6 auto-add で「未登録/要スクレイプ」とした Legendary Heartbeat(S3a)/Peerless Fighters(S5a)/Alter Genesis(SM12) は **全て catalog 実在(投入不要)**。検索ミスの自己訂正。真因は PSA→product_id adapter

### 変更
- 変更: migrations/2026-06-07_pokemon_mega_set_name_ebay_fix.py 新規（Mega系 M2/M2a/M3/M4 = 603件、commit d08ac95）+ ebay_filter_map/pokemon.yaml SSOT訂正 + 5/30 migration 2本 DEPRECATED
- 変更: migrations/2026-06-07_pokemon_broad_set_name_ebay_cleanup.py + _round2/_round3_blank/_round4_ds_xy（広域cleanup 33→+18→+blank→DS/XY、commit 15b6110/4f386e5/5194f8f）。クロス世代1058→0/subset取違46→0/監査[1][2][3]=0
- 変更: ebay_filter_map/{one_piece,dragonball}.yaml に OP-16="The Time of Battle"/FB10="Cross Force" 追記+loader反映（新弾保守、commit 4f386e5）
- 変更: integrations/psa_to_csv.py `_POKEMON_SET_NAME_TO_CODE` に ALTER GENESIS→SM12 等19キーワード追加（既存カードの未収録誤判定根治、commit 4f386e5）
- 変更: migrations/2026-06-07_b_layer_status_schema.py 新規＝`b_layer_status` テーブル(4状態) + pokemon backfill（commit e53371d）。api.py に field_status()/is_listable() 追加
- 変更: migrations/2026-06-07_b_layer_status_name_en_v2_rule.py＝name_en を Tier1-3 rule oracle で再分類（commit 9b6c523）
- 未実装(greenlight待ち): migrations/2026-06-07_pokemon_name_en_disputed_fix.py（dry-run既定、disputed 64件補正、commit d193a5e）

### 検証
- 検証✅: 監査 `iMakHQ/tools/catalog_set_audit.py` → **[1]0 / [2]0 / [3]0**（cross-gen/subset 完全解消。Sun&Moon=HQ whitelist, cardID=HQ skip）
- 検証✅: api.lookup（listing経路）で M3-097='Nihil Zero' / DS-001='Dragon Vault' / XY-003='The Best of XY' total='171' / 各値一致
- 検証✅: lookup_pokemon('SUN & MOON ALTER GENESIS','035') → SM12-035 オドリドリGX hit / FAIRY RISE→SM7b
- 検証✅: b_layer_status backfill — name_en verified_auto 15,233 / disputed 67 / unverified 6,693、set_name_ebay verified_manual 4,482 / unverified 11,421
- 検証✅: Q4 name_en POC（独立Oracle=ローカルpokeapi種族1025、ネット不要）→ 種族exact 12,727中不一致48、systematic-by-species=0、誤りは SA/DPs/MG/XY/SCS の5セット番号オフセット+M-P壊滅に集中。チコリータ=12 Chikorita+1 Durant で検証
- 検証✅: 各commit pre-commit hook 228 passed/1 skipped。work tree clean（uncommitted ゼロ）

### 残タスク（次セッション）
- **HQ greenlight待ち**: disputed 64件 name_en 補正（ピカチュウ→"Waitress" 等の壊滅corruption根治、migration準備済→--commitで即適用）
- **HQ側**: name_en multi-Oracle(suspect132)突合 / ゲート強制(新規・relist穴)配線=昇格後に有効化
- **Catalog自走候補**: trainer/Tier3 独立Oracle設計（残 unverified name_en 6,693昇格）/ set_name_ebay unverified 11,421 の独立監査（SV系正規値PJと同根）/ adapter長期データ駆動化(B層整備度依存=統合)
- 既存保留: uniqlo_ut name_en / One Piece adapter fix master反映 / サブPC Casio 残スクレイプ

---

## 2026-06-07 (続) — Catalog: disputed 64件 HQ突合資料化 / set_name_ebay 独立監査POC

### 決定事項
- 決定1: disputed name_en 64件補正は HQ greenlight 必須(B-2)。HQ の suspect132 突合用に全64件リスト(name_jp｜現値誤｜提案正｜product_id)を materialize して相談文書化(ユーザー指示=「HQに相談」)
- 決定2: set_name_ebay unverified 11,421 の独立監査 = Catalogは候補提示まで、eBay正規値確定はネット可のHQ(CLAUDE.md 2段規約)。yamlは72/75値が対象外で2源にならず → HQ突合が唯一の昇格経路
- 決定3: set_name_ebay 'Special Item'(SI-xxx,293件)/'Movie Commemoration'(MC-xxx,766件)はJPセット名直訳でeBay Setフィルタに無い疑い → 要精査フラグ(空欄化 or 再マップをHQ判断)

### 変更
- 変更: requests/2026-06-07_name_en_disputed_64_fixlist_for_hq_crosscheck.md 新規(全64件表+greenlight依頼、共有data領域)
- 変更: requests/2026-06-07_set_name_ebay_unverified_audit_poc.md 新規(75 distinct値の監査結果+HQ確認依頼、共有data領域)
- 変更: iMakCatalog/migrations/2026-06-07_pokemon_set_name_ebay_promote.py 新規(HQ承認値リスト駆動でunverified→verified_manual昇格、dry-run既定・typo検出付き)
- 未適用(greenlight待ち): disputed 64件補正(d193a5e) / set_name_ebay 昇格(承認リスト待ち)

### 検証
- 検証✅: disputed fix dry-run → pokeapi系64/対象外3(trainer)。全64件をDBから抽出しmaterialize(ピカチュウ→Waitress等M-P壊滅corruption含む)
- 検証✅: set_name_ebay 三分類 — unverified 11,421=75 distinct値/空欄0/HQ確認済53値と重複0(transitivity不可)/72値がyaml SSOT外
- 検証✅: 昇格migration dry-run(承認2値+typo1)→ 593件一致(Lost Thunder426+Best of XY167)/typo'NONEXISTENT VALUE'検出/DB無変更

## 2026-06-08 — Catalog: disputed 64件 name_en 補正 適用(HQ greenlight後)

### 決定事項
- 決定1: HQ greenlight(suspect132突合=60件完全2源一致+6件空欄fill安全+trainer1除外済)を受け、disputed 64件 name_en 補正を --commit で適用
- 決定2: is_listable ゲート有効化は未着手のまま据え置き(set_name_ebay unverified 11,421未昇格で全ブロック回避、⑤sequencing=HQ指示遵守)

### 変更
- 変更: products.sqlite name_en 64件補正 + b_layer_status status verified_auto 昇格(migration 2026-06-07_pokemon_name_en_disputed_fix.py --commit、DB変更=git外)
- 変更: requests/2026-06-07_name_en_tier23_poc_and_disputed_fix_proposal_greenlight_done.md 新規(完了報告+before/after10件、共有data領域)

### 検証
- 検証✅: disputed 67→3(残=trainer SA-021ビート/XY-036 N/362-SM-P エリカ のみ) / verified_auto 15,233→15,297(+64)
- 検証✅: backup products.sqlite.pre_nameenfix_20260608_045839 取得確認
- 検証✅: 抜粋10件 補正確認 — 020/M-P ピカチュウ Waitress→Pikachu / 022/M-P リオル Judge→Riolu / 017/M-P ニャオハ Pokémon Catcher→Sprigatito / SCS-003 Zweilous→Victini / 064/XY-P None→Pikachu、全て verified_auto

## 2026-06-08 (続) — Catalog: set_name_ebay ⚠️2値空欄化 + cardID promo feasibility回答

### 決定事項
- 決定1: HQ回答(flagged2)を受け、Movie Commemoration/Special Item は誤ラベルでeBay facet該当なし → 両方 fail-closed 空欄化(remap不可、可逆な空欄が正)
- 決定2: 残73値(標準英語セット名)はHQ保留指示を遵守、昇格migration非実行(JP↔英語セット1対1でなく機械承認は誤認リスク)
- 決定3(feasibility回答): cardID promo の 'Japanese Promo' 判定は regulation_mark がDB未保存のため再fetch必須。energy/prize 519件は is_non_card フラグ推奨、Trainer 120は機械promo付与せず(汎用札の誤ラベルリスク)

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_pokemon_void_mc_si_set_name_ebay.py 新規 + --commit適用(MC766/SI293=1059件 specs.set_name_ebay→"" / source=hq_voided_flagged2_20260608、b_layer unverified据え置き)
- 変更: requests/2026-06-07_set_name_ebay_unverified_audit_poc_hq_reply_flagged2_done.md 新規(空欄化完了報告)
- 変更: requests/2026-06-08_pokemon_cardid_promo_set_name_feasibility_response.md 新規(4問回答、実装着手NG了解)

### 検証
- 検証✅: void dry-run 1059件(MC766+SI293)=HQ申告一致 → --commit後 残存MC/SI値=0 / MC-001,SI-001 set_name_ebay='' source='hq_voided_flagged2_20260608' / b_layer=unverified維持
- 検証✅: backup products.sqlite.pre_voidmcsi_20260608_052729 取得確認
- 検証✅: cardID-NNNNN 実測 1,560件 / set_name_ebay空831 = energy390+prize129+その他312(Pokémon192+Trainer120) / regulation_mark 全件specs未保存を確認(feasibility根拠)

## 2026-06-08 (続2) — Catalog: set_name_ebay round1-6 反映 (承認7,998昇格 / 修正24はHQ確認待ち)

### 決定事項
- 決定1: HQ round1-6検証を JPセット名(set_name「」内core)キーで分類反映。承認(現値正=HQ確認済)+era-promo=7,998件を verified_manual 昇格
- 決定2: 修正24セット(1,908件)は適用保留。理由=HQ目標値が略記で eBay facet接頭辞の有無(例 Ultra Prism vs Sun & Moon—Ultra Prism)が私には検証不可。round3で"Prismatic Evolutions"接頭辞なし確定の一方DB承認値はem-dash接頭辞ありで、セット毎に異なる→推測適用は誤facet化リスク=fail-closed保留しHQに正確文字列を確認依頼
- 決定3: JP限定427(TAG TEAM/THE BEST OF XY/ウルトラフォース等)はunverified据置。UNCOVERED18(verdict未割当の旧期小セット)も据置

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_apply_rounds.py 新規 + --commit(承認+promo 7,998件 verified_manual昇格、oracle=hq_confirmed_rounds_20260608)
- 変更: requests/2026-06-08_set_name_ebay_jp_en_mapping_corrections_round6_final_done.md 新規(完了報告+修正24セットのeBay正確文字列確認依頼)

### 検証
- 検証✅: dry-run分類 approve7001+promo997+correct1908+failclosed427+skip1070+uncovered18 → 昇格対象7998
- 検証✅: --commit後 verified_manual 4,482→12,480(+7,998) / unverified 11,421→3,423
- 検証✅: backup products.sqlite.pre_sneapply_20260608_060654 取得確認
- 検証✅: SM8b(GXウルトラシャイニー)現値'Lost Thunder'が誤=correct対象として保留され昇格対象外(誤値の昇格阻止を確認)

## 2026-06-08 (続3) — Catalog: set_name_ebay 修正24セット適用 → 検証完結

### 決定事項
- 決定1: HQ確定 eBay facet 完全形(em-dash era接頭辞統一、略記撤回)で修正24セット+UNCOVERED確定分を訂正昇格。接頭辞conventionはem-dash era prefixで内部統一
- 決定2: stray promo 5件(real set下のpromo値)+リミックスバウト(JP限定)は据置(fail-closed)。光を喰らう闇はDB該当0件
- 決定3: set_name_ebay検証完結。残unverified 1,516は全て正当なfail-closed対象(void1059+JP限定421+端数特殊~36)

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_corrections.py 新規 + --commit(1,907件訂正+verified_manual昇格、oracle=hq_confirmed_facet_20260608)
- 変更: requests/..._round6_final_done_hq_facet_strings_done.md 新規(完了報告)

### 検証
- 検証✅: dry-run 1907件/25(set,old,new) stray promo5除外 → --commit後 verified_manual 12,480→14,387(+1,907)/unverified 3,423→1,516
- 検証✅: 破天の怒り 'Sword & Shield—Battle Styles'(大誤)→XY—BREAKpoint / GXウルトラシャイニー Lost Thunder→Hidden Fates 等の誤facet訂正を確認
- 検証✅: backup products.sqlite.pre_snecorr_20260608_061708 取得確認
- 検証✅: 残unverified内訳=void1059+TAG TEAM193+THE BEST OF XY173+ウルトラフォース55+端数 を実機確認(全てfail-closed正当)

## 2026-06-08 (続4) — Catalog: Dragonball filter_map FB04-08 誤set名 根治

### 決定事項
- 決定1: api.lookup set_name誤値の真因=DB表ebay_filter_map set_code FB04-08が誤。一段深い真因=yaml(正)修正後にloader.py未実行でDB表が古いまま=yaml↔DB乖離。DB表をyaml同期で根治
- 決定2: product行書換不要(api.lookupはlive変換、map修正で約600件自動正値化)。dead/誤setエントリ6件削除+実在英語raw5件追加
- 決定3: FS系はraw mismatchあるが「JP↔EN名称差」の可能性(FS04 FRIEZA=Frieza一致/FS01 SON GOKU=Saiyan Genesis)で誤判定回避のため未修正。HQに英語スターター正式名を確認依頼

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_dragonball_filter_map_fb04_08_fix.py 新規 + --commit(set_code FB04-08訂正 + set表 dead6削除/raw5追加)
- 変更: iMakCatalog/ebay_filter_map/dragonball.yaml に EN raw set エントリ5件追記(SSOT同期)
- 変更: requests/2026-06-08_dragonball_filter_map_fb04_08_wrong_names_done.md 新規(完了報告+FS確認依頼+loader運用提起)

### 検証
- 検証✅: 修正前 api.lookup FB04-001=Fusion Surge等の誤値を再現 → 修正後 FB04=Ultra Limit/FB05=New Adventure/FB06=Rivals Clash/FB07=Wish for Shenron/FB08=Saiyan's Pride
- 検証✅: 純粋FBxx-NNN(variant無) 全コード単一正値に収束(FB04 Ultra Limit 130件 等)
- 検証✅: 各コード内の少数他値=正当な再録variant(product_id=FB06-010_SB02_dummy_s1 は set_official=SB02=正)+promo を実機確認(誤りでない)
- 検証✅: backup products.sqlite.pre_dbfmfix_20260608_* 取得確認

## 2026-06-08 (続5) — Catalog: DBSCG FS訂正 + loader真因(IGNORE)修正 + name_en disputed 0達成

### 決定事項
- 決定1: FS01/02/03/05/06/07/08 をrawキャラ名へ訂正(FBと同型、map theme名は誤)。FS04/09-12は正で維持
- 決定2: yaml↔DB乖離の真因は loader未実行でなく api.register_filter_map が INSERT OR IGNORE(既存キー更新せず)。upsert化で実効化=FB/FS両バグの根本対策
- 決定3: name_en disputed残3 trainer(ビート→Bede/N→N/エリカ→Erika)をverified_manual昇格、disputed 3→0達成

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_dragonball_filter_map_fs_fix.py 新規+--commit(FS set_code 7訂正+dead set7削除)
- 変更: iMakCatalog/migrations/2026-06-08_pokemon_name_en_disputed_trainers_fix.py 新規+--commit(trainer3件)
- 変更: iMakCatalog/api.py register_filter_map を INSERT OR IGNORE → ON CONFLICT DO UPDATE(upsert、created_at保持)
- 変更: iMakCatalog/tests/test_dragonball_filter_map.py 新規(set_code公式名一致/旧誤値逆戻り防止/upsert検証 3件)
- 変更: requests/ に FS done / trainer done 報告2件

### 検証
- 検証✅: FS純粋FSxx-NNN全コード単一正値収束(FS01 Son Goku/FS05 Bardock/FS06 Son Goku (Mini)/FS08 Vegeta (Mini) Super Saiyan 3)
- 検証✅: name_en disputed 0(SA-021 Bede/XY-036 N/362-SM-P Erika をverified_manual、実機COUNT=0)
- 検証✅: pytest tests/test_dragonball_filter_map.py 3 passed(upsert動作=TEST_SENTINEL更新→復元 含む)
- 検証✅: backup pre_fsfix/pre_trainerfix 取得確認

## 2026-06-08 (続6) — Catalog: set_name_ebay literal twin残(XY11/BW8/BW3) 訂正

### 決定事項
- 決定1: XY11/BW8/BW3 の literal twin直訳→確定em-dash値に訂正(XY—Steam Siege/Black & White—Plasma Freeze/Black & White—Next Destinies)。既verified_manualでround1-6(unverified駆動)が取りこぼした別経路分
- 決定2: 監査ツールはHQ worktree側で参照不可→自前全走査。set_code割れ(twin signature)はこの3つのみ、修正後0。単一値literal~4000(Eevee Heroes/Star Birth等JP限定英名)は割れでなく対象外(eBay facet正当の可能性、HQ判断で別タスク)

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_literal_twin_fix.py 新規+--commit(312件 specs.set_name_ebay訂正、verified_manual維持)
- 変更: requests/2026-06-08_set_name_ebay_literal_residual_xy11_bw8_bw3_done.md 新規(完了報告+単一literal気づき)

### 検証
- 検証✅: XY11→XY—Steam Siege(106)/BW8→Black & White—Plasma Freeze(102)/BW3→Black & White—Next Destinies(104) 単一収束
- 検証✅: 全verified set_name_ebay の set_code割れ=0(cardID疑似割れ除く)を自前走査で確認
- 検証✅: backup pre_twinfix_20260608_* 取得確認

## 2026-06-08 (続7) — Catalog: OP/DB/Gundam clean set_name_ebay保存 + b_layer拡張 (arch1)

### 決定事項
- 決定1: SSOT方針に沿い OP/DB/Gundam の specs.set_name_ebay に clean eBay facet名を確定保存(filter_mapで一度だけ変換、出品は参照のみへ)。導出順=api._row_to_dictと同一
- 決定2: filter_map miss=空欄(fail-closed)、raw degradeさせない。b_layer_status を OP/DB/Gundam に拡張(clean=verified_manual/miss=unverified)
- 決定3: 再録は set_official が再録先booster名のため①一致で自動的に再録先clean名(suffix専用パース不要)

### 変更
- 変更: iMakCatalog/migrations/2026-06-08_opdbgundam_clean_set_name_ebay.py 新規+--commit(16,418件 specs.set_name_ebay clean化 + b_layer INSERT/upsert)
- 変更: requests/2026-06-08_arch1_..._done.md 新規(完了報告+scraper側別途のfeasibility回答)

### 検証
- 検証✅: OP clean8175/blank447, DB clean5414/blank163, Gundam clean2180/blank39。OP01-001='Romance Dawn'(旧raw)を実機確認
- 検証✅: 純粋code-NNNで set_code単一clean値収束(割れは短prefix/再録由来の見かけのみ)
- 検証✅: blankは全てnon-facet JP限定品(ファミリーデッキ/エナジーマーカー/限定商品)=fail-closed正当
- 検証✅: b_layer set_name_ebay = pokemon14387/1516 + op8175/447 + db5414/163 + gundam2180/39

## 2026-06-08 (続8) — Catalog: Pokemon name_en 取り込み fail-closed resolver (arch2)

### 決定事項
- 決定1: name_enはscraper upsertでなく翻訳/backfillで付与。Durant/Waitressの真因は旧図鑑番号計算で、translate_by_rule(name_jp直引き)は正→「番号計算廃止、rule独立一致+自己整合のみ採用、確証なし空欄」が解
- 決定2: resolve_name_en()を実装(源参照→自己整合→fail-closed)。call-site配線(backfill/run該当~10-20行)は残・次段

### 変更
- 変更: iMakCatalog/scrapers/pokemon_name_translation.py に resolve_name_en() 追加(verified_en_by_jp源参照 + rule独立一致 + disputed/blank fail-closed)
- 変更: iMakCatalog/tests/test_name_en_failclosed_resolve.py 新規(5件、Durant/Waitressクラス阻止を実証)
- 変更: requests/2026-06-08_arch2_..._response.md 新規(設計+feasibility回答)

### 検証
- 検証✅: pytest tests/test_name_en_failclosed_resolve.py 5 passed
- 検証✅: ピカチュウ verified=Waitress(誤) vs rule=Pikachu → disputed(None)=番号バグ混入を構造的に遮断 / ビート(非独立)→空欄 / チコリータ→Chikorita(独立採用)

## 2026-06-08 (続9) — Catalog: name_en 32件訂正 + arch2配線 + arch1 scraper配線

### 決定事項
- 決定1: name_en散発誤り32件(item/trainer Durant型残)を確定値に訂正→verified_manual。name_en自己整合suspectほぼ0へ
- 決定2: ~4,000単一literal set名はHQ判定どおり現状維持(JP限定の正当findable名、set_code割れでない)。em-dash寄せは別タスク低優先
- 決定3: arch2=pokemon_name_translation.run()をresolve_name_en経由に配線(verified源参照/disputed空欄/API単独=unverified)。arch1=api.derive_set_name_ebay共通helper新設+3 scraper配線

### 変更
- 変更: migrations/2026-06-08_pokemon_name_en_tier3_singlecard_fix.py 新規+--commit(32件)
- 変更: api.py derive_set_name_ebay() 新設(filter_map clean導出 共通helper)
- 変更: scrapers/{one_piece_tcg,dragonball_scg,gundam_tcg}.py build_and_upsert に clean set_name_ebay保存配線
- 変更: scrapers/pokemon_name_translation.py run() を resolve_name_en経由に(verified源構築+disputed/unverified b_layer書込)

### 検証
- 検証✅: name_en 32/32訂正(ポケモンいれかえ→Switch等)、verified_manual昇格
- 検証✅: derive_set_name_ebay smoke(OP-01→Romance Dawn/FB04→Ultra Limit/miss→空欄)、3 scraper import OK
- 検証✅: run() dry-run smoke(rule_only) 成功=verified源1,866構築・独立rule一致のみaccept(fail-closed発火)
- 検証✅: pytest 220 passed(回帰なし)

## 2026-06-09 — Catalog: PSA catalog miss 2件 = mapping/scoring 修正

### 決定事項
- 決定1: S5a-024 set_name_ebay は2026-06-08 round反映で既に'Sword & Shield—Battle Styles'充足済=追加不要。PSA brand 'PEERLESS FIGHTERS'→set_code S5a 認識を追加
- 決定2: OP10-049 Sabo は promo scoring が日本語set_name'ベストセレクション vol.4'を拾えず _P('Promotion Card')に負けて fail-closed reject。BEST SELECTION vol JP一致に+250でrule6追加し本命_p1を最優先化
- 決定3: OP premium ベストセレクション vol.1-6(72件)の set_name_ebay を free-text findability 値で充足(vol.4=HQ確定、他vol同パターン外挿、eBay facet無=CLAUDE.md自由文字列規約)

### 変更
- 変更: integrations/psa_to_csv.py `_POKEMON_SET_NAME_TO_CODE` に PEERLESS FIGHTERS→S5a / `_promo_score` rule6(BEST SELECTION vol JP一致+250)
- 変更: migrations/2026-06-09_op_premium_best_selection_set_name_ebay.py 新規+--commit(72件 re-derive + filter_map 6登録、backup取得)
- 変更: tests/test_psa_setmap_promo_scoring.py 新規(3件)
- 変更: requests/2026-06-09_psa_miss_setmap_promo_scoring_done.md

### 検証
- 検証✅: extract_set_code_from_brand_pokemon('...PEERLESS FIGHTERS')→S5a
- 検証✅: _search_one_piece_promo_by_number('049','SABO',brand='...BEST SELECTION VOL.4-')→OP10-049_p1(score=258、従来220同点reject是正)
- 検証✅: api.lookup('OP10-049_p1').set_name='Premium Card Collection - Best Selection vol.4'(72件充足)
- 検証✅: pytest 新規3 passed + 全体 pass

## 2026-06-09 (続) — Catalog: PSA SwSh setmap 2件 + auto-add投入不要 + KEY再設計feasibility

### 決定事項
- 決定1: PSA brand "FUSION ARTS"→S8 / "REBELLION CRASH"→S2 を _POKEMON_SET_NAME_TO_CODE に追加(PEERLESSと同型、両カードS8-035/S2-076は既存・set_name_ebay充足済)
- 決定2: auto_catalog_add 2件=同一カードで既存=投入不要。真因はadapter mapping欠落(決定1で解消)
- 決定3: SwSh全弾一括整備はfeasible だが PSA brand実文字列(Fusion Arts≠公式Fusion Strike)の確証source前提=データ駆動で都度追加を推奨
- 決定4(KEY再設計feasibility): resolver集約は新規開発でなくリファクタ(lookup_*/extract_*/promo-scoring は既にpsa_to_csv 33関数に在る)→catalog coreにfacade移設。中2-4日。前提=lookup_one_piece brand bug(5/28)先行修正+variant網羅真値source。配置はiMakCatalog(SSOT)賛成

### 変更
- 変更: integrations/psa_to_csv.py _POKEMON_SET_NAME_TO_CODE に FUSION ARTS→S8 / REBELLION CRASH→S2
- 変更: tests/test_psa_setmap_promo_scoring.py に test_swsh_brand_set_code_mappings 追加
- 変更: requests/ に psa_setmap done / auto-add processed / KEY再設計 feasibility回答

### 検証
- 検証✅: extract_set_code_from_brand_pokemon FUSION ARTS→S8 / REBELLION CRASH→S2、lookup hit
- 検証✅: pytest tests/test_psa_setmap_promo_scoring.py 4 passed

## 2026-06-10 — Catalog: KEY再設計 Step1 POC (go) + 着手可否GO

### 決定事項
- 決定1: KEY再設計 phase1 着手可否=GO、ユーザー判断1-4(iMakCatalog配置/KEY2 ARCHIVED/ハイブリッドbackfill/strict義務化)異議なし
- 決定2: Step1 POC=GO(resolver_poc.py 4/4)。固有variant→OP10-049_p1 / bare→base(誤除外なし) / 判別不能→"" を実証
- 決定3(設計判断浮上): (a)bare policy=base解決推奨(base実在時、""でなく。誤除外なし)。(b)variant scoring網羅はStep3で拡充要(_p2=3周年treasure未到達)
- 決定4: Step2(lookup_one_piece brand bug 5/28/614同型)を独立POC再現→修正してからStep3 facade(順序厳守)

### 変更
- 変更: iMakCatalog/resolver_poc.py 新規(Step1 POC、再走可・committed証跡)
- 変更: requests/2026-06-09_key_redesign_BUILD_greenlight_phase1_step1_poc.md(POC結果+着手可否+設計判断2点)

### 検証
- 検証✅: python resolver_poc.py → 4/4 OK (① OP10-049_p1 / ② OP10-049 base / ③ "" / ④ "")

## 2026-06-10 (続) — Catalog: KEY再設計 Step2 lookup_one_piece promo brand-class bug修正

### 決定事項
- 決定1: HQ 3再現ケースで現状確認 — B Marco(OP08-002_P_LF)/C Sabo(OP10-049_p1)は既存修正で既にPASS。残差はA Chopperのみ(EB01-006_P_treasureとST01-006_P/_P_pが220同点reject)
- 決定2: _promo_score に rule7(brand英語↔日本語set_name照合 PREMIUM CARD COLLECTION↔プレミアムカードコレクション等) + rule8(cross-set防止: MEMORIAL非明示時EB由来promo-40)追加。報告された誤マッチ(EB01 cross-set)を根治
- 決定3: A は generic brand で ST01-006_P vs _P_p 判別不能→None(fail-closed=誤出品せず)。正hit化はedition語有無/canonical指定をHQ確認(無理に当てない=大前提順守)

### 変更
- 変更: integrations/psa_to_csv.py _promo_score に rule7/rule8 追加
- 変更: tests/test_lookup_one_piece_promo_scoring.py 新規(A=EB01選ばない+ST01系orNone / B=OP08-002_P_LF / C=OP10-049_p1)
- 変更: requests/2026-06-09_key_redesign_BUILD_greenlight_phase1_step2_done.md

### 検証
- 検証✅: 修正後 A=EB01-006_P_treasure 220→180降格(top排除)、top=ST01-006系220同点→None / B=OP08-002_P_LF / C=OP10-049_p1(298)
- 検証✅: pytest Step2 3件 + adapter4件 pass、全体224 passed(回帰なし)

## 2026-06-10 (続2) — Catalog: Step2 tiebreak反映 A Chopper=ST01-006_p1 一意解決

### 決定事項
- 決定1: HQ実機確定(実brand=25TH ANNIVERSARY)で A は tie でなく一意解。ST01-006_p1は候補に居たがscore130で_P220に負けていた(索引が正項目に届いてなかった)
- 決定2: _promo_score を edition双方一致(brand↔official)の一般照合+250に統一(BEST SELECTION VOL.N/25TH↔25周年/FILM RED)。両方一致必須で別edition暴発防止。rule8(EB cross-set減点)維持

### 変更
- 変更: integrations/psa_to_csv.py _promo_score 統一(旧rule6/loose rule7→edition双方一致+250)
- 変更: tests/test_lookup_one_piece_promo_scoring.py 更新(A実brand=p1/A generic=fail-closed/A暴発guard/B/C=5件)
- 変更: requests/2026-06-09_..._step2_tiebreak_done.md

### 検証
- 検証✅: A実brand(25TH)→ST01-006_p1 / A generic→None / A暴発guard(_p4選ばず) / B=OP08-002_P_LF / C=OP10-049_p1
- 検証✅: pytest Step2 5件 + adapter4件 pass、全体229 passed(回帰なし)

## 2026-06-10 (続3) — Catalog: KEY再設計 Step3 resolver facade 新設

### 決定事項
- 決定1: iMakCatalog/resolver.py 新設。resolve(context)→canonical product_id | 正規化URL | ""(fail-closed)。既存33関数(lookup_*/promo-scoring)を内部dispatch集約(新規ロジックなし)
- 決定2: lookup API key不統一(card_id vs product_id)を facade内で吸収し戻り値product_id統一。判別不能/未対応/名前不一致→""。category alias対応。G-shockは別phase(現状"")
- 決定3: psa_to_csv は未改変(shim併存・循環import無し)。呼び出し側のresolve()切替は順次(無停止移行、HQ協調)

### 変更
- 変更: iMakCatalog/resolver.py 新規(resolve facade)
- 変更: tests/test_resolver_facade.py 新規(8件)
- 変更: requests/2026-06-09_..._step3_done.md

### 検証
- 検証✅: resolve OP Sabo→OP10-049_p1 / Chopper25TH→ST01-006_p1 / Chopper generic→"" / Pokemon FUSION ARTS→S8-035 / alias op→OP01-001 / gshock→"" / 不足signal→"" / mercari url→item:/shops:
- 検証✅: pytest resolver 8件 pass、全体237 passed(回帰なし)
- 検証✅: catalog先行フェーズ Step1(POC)/Step2(lookup bug根治)/Step3(facade) 完了

## 2026-06-10 (続4) — Catalog: JET-BLACK SPIRIT→S6K + SwSh全弾 体系整備

### 決定事項
- 決定1: JET-BLACK SPIRIT→S6K(4件目)追加。S6K-037=こくばバドレックスVMAX確認。3AI誤BLOCK(037=Shadow Lugia幻覚)も解消
- 決定2: もぐら叩き終了。SwSh S系 set_code 全棚卸し→未収録11件をPSA literal英名で一括追加(Bulbapedia/PSA/StockX裏取り)
- 決定3: S1W/S1H(ソード/シールド)は era名"SWORD & SHIELD"衝突で意図的除外(別手段要、該当出たら相談)

### 変更
- 変更: integrations/psa_to_csv.py _POKEMON_SET_NAME_TO_CODE に SwSh 11件追加(INFINITY ZONE/EXPLOSIVE WALKER/LEGENDARY HEARTBEAT/ASTONISHING VOLT TACKLE/SINGLE STRIKE MASTER/RAPID STRIKE MASTER/SILVER LANCE/JET-BLACK SPIRIT/SKYSCRAPING PERFECT/BLUE SKY STREAM/POKEMON GO)
- 変更: tests/test_pokemon_swsh_setmap.py 新規(3件)

### 検証
- 検証✅: 全15(既出4+新11)brand→set_code 正解 + catalog存在 + 衝突なし(EEVEE HEROES=S6a/STAR BIRTH=S9不変)
- 検証✅: SKYSCRAPING PERFECT/PERFECTION 両表記hit
- 検証✅: pytest SwSh 3件 + 全体240 passed(回帰なし)

## 2026-06-10 (続5) — Catalog: 解決不能17件 feasibility調査

### 決定事項
- 決定1(feasibility): 17件中14件は変種がcatalog実在(resolver""はpromo-scoring語彙不足)。2件=category番号衝突(別category実在)、1件(610 box topper)=未収録
- 決定2: 主対応=edition/event matcher拡張(既存25周年/Best Selection双方一致の一般化)。B5件(FILM RED/UTA/ONE PIECE DAY)即解決、A数件(プロモカードセット/スタンダードバトル等)も
- 決定3: category衝突(252 Gundam ST04-013=Hawk of Endymion実在/367 P-024=DB Son Goku)はresolver brand→category検出で分離。多変種ambiguity(Let's Start/Pikachu gym/Storage box)はfail-closed維持

### 変更
- 変更: requests/2026-06-10_op_pkmn_unresolved17_promo_premium_variants_response.md(全17件 解決マップ+実装提案I/II/III/IV)
- ※コード変更なし(feasibility回答のみ、実装はgreenlight後)

### 検証
- 検証✅: 全17件のcert→在るべきproduct_id を実機照会(B5件_pN実在/A OP03-044×3=_p2同変種/252 gundam ST04-013実在/610 box topper未収録 確認)

## 2026-06-10 (続6) — Catalog: unresolved17 (I)(II) + DB/Gundam set-map 実装

### 決定事項
- 決定1(I): _promo_score edition matcher拡張(FILM RED/UTA/ONE PIECE DAY/PROMOTION CARD SET/STANDARD BATTLE 双方一致 + WINNER↔優勝/PREMIUM CARD COLLECTION qualifier)。B5件+A(405/453×3)解決
- 決定2(II): resolver brand→category検出(GUNDAM/DRAGON BALL/ONE PIECE/POKEMON/YGO)。番号衝突252 ST04-013→gundam解決。曖昧→呼出側尊重(fail-closed)
- 決定3(②): gundam(DUAL IMPACT→GD02等)+dragonball(MANGA BOOSTER NN→SBNN/ENERGY MARKER PACK NN→E0N) keyword逆引き。25件解決
- 決定4(副次): name matcher に record.name_en 追加(JP name record も romaji subject照合) + subject tokenizer に :／& 区切り(TRUNKS:FUTURE)。453 Kaya/SB02 解決に必須

### 変更
- 変更: integrations/psa_to_csv.py _promo_score(edition/qualifier拡張) / extract_set_code_from_brand_gundam(keyword逆引き) / extract_set_code_from_brand_dragonball(MANGA BOOSTER/ENERGY MARKER) / _record_name_matches_subject(name_en追加) / _subject_tokens(:／&区切り)
- 変更: resolver.py brand→category検出(_detect_category_from_brand)
- 変更: tests/test_unresolved17_dbgundam_resolve.py 新規(7件)
- 変更: requests/ に unresolved17 done / db_gundam response

### 検証
- 検証✅: B premium 5件(ST01-007_p5等)/405(OP01-016_p6)/453×3(OP03-044_p2)/252(ST04-013 gundam)/GD02-070/GD01-096/SB02-001/SB02-017/E01-03 全resolve。Chopper/Sabo回帰維持
- 検証✅: pytest 新規7件 + 全体247 passed(回帰なし)

## 2026-06-10 (続7) — Catalog: HQ差し戻し修正 (promo subject側照合 + Gundam starter)

### 決定事項
- 決定1(真因): 前回テストが_search直叩きmockで実signal配置未反映。PSAはedition/event語をsubject側に置く(brand=generic PROMOS)→_promo_scoreがbrandのみ照合で実lookup_one_pieceでNone
- 決定2: _promo_score を brand+subject合成 hay で照合(rule1-8/edition/qualifier全)。EVENT PRIZE↔記念品追加。Gundam starter set-map(SEED STRIKE→ST04 + ST01-09公式英名)で252解決
- 決定3: テストを実entry(lookup_one_piece/resolve)に書換(mock廃止)=HQ受入基準。367はDBSCG promo-variant scoring未実装でbare FP-024(正FP-024_p1=ダイマツリ)=follow-up低優先

### 変更
- 変更: integrations/psa_to_csv.py _promo_score(hay=brand+subject照合に統一、EVENT PRIZE↔記念品) / extract_set_code_from_brand_gundam(ST01-09 starter名)
- 変更: tests/test_unresolved17_dbgundam_resolve.py 実entry書換
- 変更: requests/..._followup_..._done.md(実出力添付)

### 検証(実 lookup_one_piece/resolve 実出力)
- 検証✅: 'PROMOS'+subj'KAYA STANDARD BATTLE WINNER'/044→OP03-044_p2 / 'NAMI PROMOTION CARD SET 1'/016→OP01-016_p6 / 'TASHIGI OFFICIAL EVENT PRIZE'/031→OP12-031_p2
- 検証✅: B premium FILM RED/007→ST01-007_p5 (完全形brand) / 252 SEED STRIKE→ST04-013
- 検証✅: Chopper/Sabo回帰維持、pytest 全体246 passed
- 検証⚠️: 367 DB→bare FP-024(正FP-024_p1、DBSCG promo-scoring follow-up)

## 2026-06-10 (続8) — Catalog: SV-P-291 収録 + 367 DBSCG決定 受領

### 決定事項
- 決定1: SV-P-291=ピカチュウ(ジムイベントキャンペーンpromo, Championship Series 2026)を公式複数ソース裏取り→収録(name_en=Pikachu/set_name_ebay='Promo')。cert146003969一致、TCG固有化の最後の1枚
- 決定2: 367 P-024 DBSCG = HQ決定どおり""維持(bare FP-024に解決させない)了解。DBSCG promo-scoringは低優先follow-up(DB出品本格化時)。現resolveはFP-024返すためHQ sweepで367除外周知。broad変更リスク回避で今回コード改変見送り

### 変更
- 変更: products.sqlite に SV-P-291 upsert(name=ピカチュウ/name_en=Pikachu/specs.set_name_ebay='Promo') + b_layer(name_en verified_auto / set_name_ebay verified_manual)。DB変更=git外
- 変更: requests/ に svp291 done / 367 processed

### 検証
- 検証✅: lookup('SV-P-291')→ピカチュウ/Pikachu/Promo。resolve(cert 'SV-P PROMO'+'PIKACHU GYM EVENT CAMPAIGN'+291)→SV-P-291 end-to-end
- 検証✅: 公式裏取り(GameStop PSA 291 Pikachu Gym Event Campaign / 公式campaign news 2025/10配布)

## 2026-06-11 — Catalog: PSA索引 大規模整備（4ゲーム完走 + 脱落fix + HIGH orphan）

### 決定事項
- 決定1(PSA脱落6件): brand→set_code 索引追加で5件解決(records実在)。ULTRA SHINY GX→SM8b/SKY LEGEND→SM10b(依頼のSM7a推測は誤・DB値SM10b正)/START DECK 100→SI。真因=「S PROMO」がgeneric PROMO→Pに落ちP-288誤引き→S PROMO→S-P追加でS-P-288/265 hit。M-P-020(McDonald's Pikachu)のみ新規収録、公式card/48258=ハッピーセット**2025**(依頼の2021-22は誤・HQの"2025"が正)。コメント前提「M-P-020=ウエートレス」も誤(Waitress=MC-700)
- 決定2(Gap-B promo逆順): 逆順product_id `NNN/SM-P`(407)/`NNN/M-P`(81)→正順`XX-P-NNN`に統一(HQ承認)。「promo未収録」の正体=誤キー。resolver `SM PROMO→SM-P`(旧SMP廃止)。489件reachable化
- 決定3(遊戯王): 「resolver不在」はHQ誤認、真因=配線bug。resolve()がcard_idのみ読みlookup_yugioh はproduct_id返すため''落ち。docstring契約通り`card_id or product_id`両対応に修正。0%→94.5%
- 決定4(Gap-A): set_name裏取りのunique名のみkeyword追加(誤マッチ非対称安全=最悪no-op)。High-Class Deck(SGG/SGI)+SM期拡張9件。paired/旧-B/PSA literal未確認は据置(recall-sacrifice許容)
- 決定5(XY収束): outlier(XY-P-NNN5+逆順9)を稼働XYP-NNN(277)へ収束、14重複削除、resolver変更不要
- 決定6(rarity空): M2a-127 Rayquaza=R補填(PSA"reverse holo"=基底弾+カードラッシュ"R仕様"の三角検証)。元SKU m99298510053はstaleでクローズ
- 決定7(SV-P-196衝突): 衝突でなくingest番号誤記(HQ公式裏取り)。`196/SV-P`(Kariya版)→`SV-P-198`再キー。SV-P-196(Susumu Maeya)は維持
- 決定8(HIGH orphan 7件): 6件は既存(正式キー不一致のみ)=GDRES-NNN→R-NNN(Resource)/GDBETA-006→EXBP-006(EX Base)/SM-P-001(Wave2で既収録)。実収録はSM12a-224(Lucario&Melmetal GX UR)1件のみ

### 変更
- 変更: integrations/psa_to_csv.py — _POKEMON_SET_NAME_TO_CODE(ULTRA SHINY GX/SKY LEGEND/START DECK 100/SGG/SGI/SM期拡張9件) + psa_promo_to_catalog(SV PROMO→SV-P, S PROMO→S-P, SM PROMO→SMP→SM-P) + _POKEMON_PROMO_SET_CODES(SMP→SM-P)
- 変更: resolver.py — TCG/DON dispatch を `card_id or product_id` 両対応(yugioh resolve回復)
- 変更(共有DB・git外): SM-P/M-P逆順488 rename+020/M-P重複削除 / XY outlier14削除 / M-P-020・SM12a-224収録 / M2a-127 rarity補填 / 196/SV-P→SV-P-198再キー
- 変更: tests/ — test_psa_dropped_6_setmap_promo.py新規 / test_pokemon_swsh_setmap.py(HighClassDeck) 追加。全252 green
- 変更: backup+対応表 — migrations/{gapB_promo_reorder,xy_promo_converge,svp198_rekey}_20260611.json + products.sqlite.bak_20260611_{gapB,xy,svp198}
- commit: 0ae7531/989f618/9a45ce1/6a3d794/1d9dd5d (feature/uniqlo-ut, push済)

### 検証(実 resolve/lookup 実出力)
- 検証✅(脱落6): cert109940063→SM10b-053/74118843→SM8b-214/139561995→SI-127/131214875→S-P-288/126900241→S-P-265/127272109→M-P-020 全hit
- 検証✅(Gap-B): lookup('SM PROMO','001')→SM-P-001(Snorlax-GX) / ('M-P PROMO','001')→M-P-001。reachable SM-P407+M-P82=489
- 検証✅(遊戯王): synthetic n=201で hit94.5%/fail-closed4.0%/誤マッチ0%(50,098件)
- 検証✅(4ゲーム実測・全誤マッチ0%): yugioh94.5%/one_piece94%/dragonball95%/gundam89%。OP/DB/Gundamは元々clean(HQ正)
- 検証✅(Gap-A9件): SHINING LEGENDS→SM3p-001等9件 全実在レコードhit・回帰なし(約565cards)
- 検証✅(SV-P-198): resolve(Eevee,198)→SV-P-198 / (Eevee,196)→SV-P-196 別キー分離
- 検証✅(HIGH7): R-008/010/013/018=Resource・EXBP-006=EX Base・SM-P-001=Snorlax-GX 既存確認 / SM12a-224収録+resolve(TAG ALL STARS,224)→SM12a-224
- 検証⚠️(据置): pokemon長tail約8,600(旧-B期/deck-promo sub-code 61codes=brand実物待ち) / energy cardID 1,560(低優先)。出品ブロッカーなし
- 検証⚠️(SM12a-224): UR固有画像は公式card id未特定で空欄(fail-closed、RR画像誤流用回避)

---

## 2026-06-11 (続) — Catalog: G-shock dedupe(B案) + pre-flight + Amazon方針 + PSA索引fix

### 決定事項
- 決定1(G-shock hybrid): 公式Akamai block頭打ち→非公式(shockbase/g-central/casiofanmag)hybridを拡充の主経路として正式容認(ユーザー「併用」)。breadthは1,553で停止=A案(人気埋め残しのみ)。ShockBaseが最網羅(721/887件・43年・CMD requests=軽量)
- 決定2(dedupe B案): bare↔suffix同実物重複を「削除」→「別名紐づけ(alias_of)」に切替(HQ+ユーザー)。削除版(a838428)をsupersede。canonical=suffix形/bare=alias/243件alias化(復元+リンク)。round-1誤削除GBX-100-2復元
- 決定3(resolver): lookup_gshock を alias対応fail-closed化。bare(1:1 alias)→canonical解決(recall維持)/真1:N(GW-9400J-1B)→""/海外suffixは除外せず照合。AJF/AJR=色A+JF(地域でない)の罠回避
- 決定4(並行輸入): spec§2「海外SKU除外」緩和(HQ+ユーザー)。並行輸入=出品対象→catalog化可(source=amazon_jp_parallel)。Amazon US merchant出品(B000FPVUJA)は国内仕入不可でreject
- 決定5(Amazon field): catalog=静的マスター。動的データ(価格/在庫数/販売数)は入れずsourcing層へ。catalogはidentity/在庫flag/画像/新規のみ
- 決定6(PSA索引): GAP37の大半は真の未収録でなくresolver索引不備。3 fixで~30 fetch0解消。auto_add11→9投入不要

### 変更
- 変更: integrations/gshock_lookup.py — alias対応lookup(_resolve_alias) + 型番内スペース正規化。api.py — alias_of露出。db/schema.sql — alias_of列
- 変更: integrations/psa_to_csv.py — lookup_pokemon: _set_code_lookup_variants(0↔O) + card_number 3桁0埋め。lookup_dragonball: 早期full-pidチェック ^[A-Z]{1,3}\d*-\w 拡張 + 二重接頭辞ガード(Energy Marker)
- 変更: integrations/gshock_preflight.py 新規(HIT/MISSING/AMBIGUOUS 3分類)
- 変更(共有DB・git外): gshock dedupe round2(104)→alias復元243 / dragonball エナジーマーカー257件 name_en='Energy Marker'投入。bak: baredupe/round2/aliasB/energymarker_nameen
- 変更: tests/ — gshock_lookup_failclosed(alias) / pokemon_set_code_0o / dragonball_energy_marker_resolve 追加
- commit: a838428/10d0d86/fe2f335/be40ff2/5ec6122/e1104ba/52b4da6 (feature/uniqlo-ut)

### 検証(実 resolve/lookup 実出力)
- 検証✅(dedupe B): gshock 1553(alias243含む)、正J-whitelistで bare↔suffix重複=0、dangling alias=0。lookup('GM-700G-9A')→GM-700G-9AJF(alias解決)/('GW-9400J-1B')→None(1:N)
- 検証✅(pre-flight): HQ dump 349件→HIT320(91.7%)/MISSING29/AMBIGUOUS0。MISSING内訳=国内17+海外SKU11(投入対象)+不完全1
- 検証✅(0/O): lookup_pokemon('SV0M-EX...','020')→SVOM-020。S8a等は回帰なし
- 検証✅(Energy Marker): ('ENERGY MARKER','E01-02',ALT ART)→E01-02_p1 / 'E-04'→E-04 / 'E-73'→E-73 / 'FP-024'→FP-024。別キャラsubject→reject
- 検証✅(0埋め): Charizard('SMP2','7')→SMP2-007
- 検証✅(triage): auto_add11→9投入不要(既収録/索引fix済)。真の未収録2(ASIA25th#005/Shining Magikarp#010)
- 検証⚠️(残・次セッション): promo resolver REVIEW4件(S8a-G-005/OP05-067/EB01-006/ST07-008=カード実在・fetch不要・推奨次着手) + 真の未収録fetch~6(Shining Magikarp/ASIA promo/UTA#001/DON×3/CP8)。SM3p-010は別カード(ひかるゲノセクト)
- 検証⚠️(Amazon merge): session5(variant補完)完了後に1回merge予定(ロジック新規実装要)。29 gapはAmazon独立にShockBase backfill必要(Amazon待ちで埋まらない)
- 全231 green(pre-commit)


## 2026-06-12 — Catalog: PSA preflight REVIEW promo resolver 2件確定 / 2件 reject維持

### 決定事項
- 決定1(REVIEW triage): preflight REVIEW 5件を「ブランドで variant が一意に決まるか」で2分。確定2件のみ resolve、曖昧2件は fail-closed reject維持(誤出品防止)。Shining Magikarp #010 は SM3p-010=別カード(ひかるゲノセクト)で前回確定の真の未収録(fetch)。
- 決定2(Zoro OP05-067_p2): edition pair に "COMPLETE GUIDE" 追加。#067候補中 official に "COMPLETE GUIDE" を持つのは _p2(2nd ANNIVERSARY COMPLETE GUIDE 収録特典)のみ=一意。両側一致必須=誤発火不能。
- 決定3(Pikachu V S8a-G-005): GOLDEN BOX→S8a-G(25周年ゴールデンボックス専用15枚)を pokemon set名逆引きに追加。plain S8a-005=Lugia と衝突するため必須振り分け。S8a-G prefix は golden box 専用=over-fire不能。ただし PSA が GOLDEN BOX を subject 側に置く cert では brand単独参照の本pathは no-op(fail-closed・raw cert要確認)。
- 決定4(Chopper EB01-006 / Pudding ST07-008): promo変種が _P/_P_P/_P_treasure・_P/_P_D/_p1/_p3 と複数あり brand で一意化不能 → reject維持が正(誤variant出品回避)。

### 変更
- 変更: integrations/psa_to_csv.py — _search_one_piece_promo_by_number の edition pair に ("COMPLETE GUIDE","COMPLETE GUIDE") 追加 / _POKEMON_SET_NAME_TO_CODE に "GOLDEN BOX":"S8a-G"(25TH ANNIVERSARY COLLECTION より前)追加
- 変更: tests/test_psa_review_promo_resolve.py 新規(7件)。全288 green(pre-commit 231 green)
- 変更: requests/ に preflight REVIEW 処理報告
- commit: 9f51130 (feature/uniqlo-ut)

### 検証(実 resolve 実出力)
- 検証✅(Zoro): _search_one_piece_promo_by_number('067','ZORO JUUROU',brand=...COMPLETE GUIDE)→OP05-067_p2 / brand に COMPLETE GUIDE 無→None(over-fire無)
- 検証✅(Pikachu V): extract(...GOLDEN BOX)→S8a-G / lookup_pokemon(#005)→S8a-G-005 'Pikachu V'。plain 25TH ANNIVERSARY COLLECTION #005→S8a-005 'Lugia'(回帰維持)
- 検証✅(reject維持): Chopper LET'S START→None / Charlotte Pudding→None
- 検証⚠️(残): 真の未収録 fetch ~6(Shining Magikarp#010/ASIA promo/UTA#001/DON×3/CP8)は別工数。Pikachu V Golden Box は PSA brand に GOLDEN BOX が乗っている前提=HQ の raw cert 142931332 で要最終確認(subject側なら no-op)。


## 2026-06-12 (続) — Catalog: preflight 残「fetch ~6件」triage + Shining Magikarp 収録

### 決定事項
- 決定1(triage): 「真の未収録 ~6件」を実機調査。過半は未収録でなく **PSA cert に判別情報が無く resolve 不能**と判明。真の収録 fetch は Pokemon 2 + DBSCG 1 のみ。
- 決定2(DON×3 = reject正): DON-OP13-001/002・DON-OP15-001/002 は **収録済**。PSA「DON!! CARD」に番号もキャラ art も無く variant 判別不能 → fail-closed reject が正(誤variant出品回避)。resolve には image-hash(lookup_don)=PSA image_url が必要。
- 決定3(UTA #001/PRB01): PRB01-001=Sanji(別カード)。UTA promo 多数。対象特定に raw cert 画像/variety 要。
- 決定4(Shining Magikarp 収録): cert77429277 = S8a-P 010/025(ひかるコイキング/プロモカードパック25th ANNIVERSARY edition)を複数ソース裏取り→収録。前回候補 SM3p-010=別カード(ひかるゲノセクト)誤を確定。
- 決定5(raw cert 依頼): set_code 配線(Magikarp)・image照合(DON/UTA)・DBSCG CP8 ID には HQ の PSA raw データ(brand/subject/image_url)が必須(psacard.com 403 で当方取得不可)→ 依頼書起票。

### 変更
- 変更(共有DB・git外): products.sqlite に S8a-P-010 upsert(name=ひかるコイキング/name_en=Shining Magikarp/set_official='プロモカードパック 25th ANNIVERSARY edition'/specs.set_name_ebay='Promo'暫定)。bak: products.sqlite.bak_20260612_s8aP010
- 変更: requests/ に 2026-06-12_psa_preflight_gap6_triage_and_raw_cert_request.md(triage結果+raw cert依頼)
- コード変更: 無し(speculative 配線は raw brand 待ち=推測で入れない fail-closed)

### 検証
- 検証✅(裏取り): cardrush/snkrdunk/magi/amazon.co.jp 一致。S8a-P 010/025 ひかるコイキング(2021-10-22, Water/HP30/holo)
- 検証✅(収録): api.lookup('pokemon_tcg','S8a-P-010')→ひかるコイキング/Shining Magikarp/set_ebay=Promo
- 検証✅(DON 既収録): DON-OP13-001/002・DON-OP15-001/002 実在(name='DON!! Card')。PSA DON!! CARD は判別情報無
- 検証⚠️(Magikarp resolve 未配線): extract_set_code_from_brand_pokemon が当該 brand を S8a-P に落とせる保証無→raw brand 待ち。record は存在させた(groundwork)
- 検証⚠️(set_name_ebay): S8a-P は国際 Celebrations 非対応。'Promo' 暫定=最終 eBay Set 値は要確認


## 2026-06-12 (続2) — Catalog: HQ raw cert dump 受領 → preflight backlog Catalog側 完了

### 決定事項
- 決定1(Magikarp RESOLVED): HQ raw brand=`POKEMON JAPANESE PROMO CARD PACK 25TH ANNIVERSARY EDITION`で set句が brand側と確認→ `_POKEMON_SET_NAME_TO_CODE` に "PROMO CARD PACK 25TH ANNIVERSARY EDITION":"S8a-P" 追加。cert77429277→S8a-P-010 end-to-end解決。
- 決定2(Pikachu V=reject正): HQ指摘どおり ASIA版(brand=ASIA PROMO/GOLDEN BOX は subject側)。追加裏取り(Bulbapedia/TCGplayer/StockX): 25th Golden Boxは JP/繁中/韓/尼が同一S8a-G番号だが言語差。catalog S8a-G-005=日本語のためASIA cert解決はLanguage誤り=出品正確性違反→reject正。brand-path fix(9f51130)はGOLDEN BOXがbrand側に無い本certに構造的no-op=言語誤り回避。
- 決定3(CELL CP8=対象外): brand=DRAGON BALL HEROES 2(2011アーケード)。catalog dragonball_scg(DBSCG2022〜)と別ゲーム→reject/category-unknown。
- 決定4(DON×3=reject確定): 3件ともCardNumber/image_url=None。DON-OP13/OP15-001/002の variant判別材料がPSAに皆無。再scrapeしても不変。
- 決定5(UTA#001=reject正): storage box set UTA=ST16-001_p1/_p2の別アート2枚(共SR/series550801)。cert に variety/画像無で判別不能→Chopper/Pudding同型 fail-closed。
- 決定6(backlog完了): preflight 残の Catalog側対応は完了。解決1(Magikarp)・他4種は誤出品/誤言語/対象外回避でreject正。残ユーザー裁定2件(ASIA言語版収録要否/UTA再scrape要否)は優先度低で保留可。

### 変更
- 変更: integrations/psa_to_csv.py — _POKEMON_SET_NAME_TO_CODE に "PROMO CARD PACK 25TH ANNIVERSARY EDITION":"S8a-P"(brand-path)
- 変更: tests/test_psa_review_promo_resolve.py — +3(PromoCardPack×2/GoldenBoxAsiaReject)。全291 green
- 変更: requests/ に 2026-06-12_..._response_processed.md(7cert最終disposition)
- commit: e08be80 (feature/uniqlo-ut)

### 検証(実出力)
- 検証✅(Magikarp): extract(brand)→S8a-P / lookup #010→S8a-P-010 'Shining Magikarp'。25TH ANNIVERSARY COLLECTION→S8a回帰維持
- 検証✅(Pikachu Asia reject): extract('POKEMON ASIA 25TH ANNIVERSARY PROMO')→P / lookup #005→None
- 検証✅(裏取り言語差): 25th Golden Box JP/繁中/韓/尼 同S8a-G番号・言語別(Bulbapedia/TCGplayer)
- 検証✅(UTA別アート): ST16-001_p1.png/_p2.png 別画像(onepiece-cardgame.com series550801)


## 2026-06-12 (続3) — Catalog: Amazon gshock dump 非直販17 ASIN 除外(Harvest依頼)

### 決定事項
- 決定1(遡及不要): 実機確認で catalog に amazon_available 列無・amazon_jp source 未投入・17 ASIN は catalog に0 hit。=Amazon dump は未merge(ロジック新規実装要のまま)。よって「取込済flag降格」は不要、本件は merge実装時の予防是正として固定。
- 決定2(恒久リスト化・非破壊): _amazon_jp_dumps/exclude_asins.json 新設。将来merge が honor。2層: exclude_entirely(A band4+B AmazonUS4=8件・一切ingestせずvariant子もsourcing外) / exclude_amazon_available_only(C 国内3P 9件=identity可だが直販フラグ抑止)。dump JSON 本体は raw provenance+seller-bug証跡のため物理削除せず温存(可逆・fail-closed)。
- 決定3(variant子): A/B は親の variant_asins 子でも sourcing除外、C は identity残・直販フラグのみ抑止。現dumpでは17 ASIN いずれも他ASINのvariant_asinsに不在=実害なし。

### 変更
- 変更(共有data・git外): C:/dev/iMak_data/catalog/_amazon_jp_dumps/exclude_asins.json 新設(17 ASIN/A-B-C区分/disposition)
- 変更: requests/ に 2026-06-12_amazon_gshock_dump_nondirect_exclusion_response.md
- コード変更: 無し(merge未実装のため。merge実装時に exclude_asins.json をload)

### 検証(実機)
- 検証✅: PRAGMA で amazon_available 列無。gshock source=shockbase/g-central/casiofanmag/casio_official のみ
- 検証✅: 17 ASIN を specs/variants/source_url/source 全 grep → 0 hit(未投入)
- 検証✅(dump裏取り): 4 dump 375件中 16/17 ASIN top-level実在。seller誤判定確認(B0CYLNCYRY等 seller='Amazon.co.jp'=FBA誤検出)。B000FPVUJA のみ現dump不在(no-op、再混入防止で登録)
- 検証✅(JSON): exclude_asins.json valid・17 unique(entirely8+flag_only9)


## 2026-06-12 (続4) — Catalog: Amazon dump レディース51 ASIN を gender タグ化(Harvest依頼)

### 決定事項
- 決定1(別軸管理): 前回の非直販除外(seller軸)と違い、レディース51は「除外でなく gender/scope タグ」。identity保持・amazon_available可・メンズ動線には流さない。依頼どおり exclude_asins.json と別 file で管理。
- 決定2(重複1件の優先): B0CQC3TLRZ(GM-S5600UPG-1JF)は前回 C群(国内3P)にも在り。seller軸(非直販=直販フラグ立てない)が優先、本file は gender=ladies のみ付与。両軸直交で矛盾なく合成。
- 決定3(merge挙動): 将来 Amazon merge は exclude_asins.json(seller軸) と gender_scope_tags.json(gender軸)の両方を読み合わせ、ASINごとに (除外/フラグ) ∧ (scope) を適用。

### 変更
- 変更(共有data・git外): _amazon_jp_dumps/gender_scope_tags.json 新設(51 ASIN/gender=ladies/identity可・amazon_available可・mens_sourcing除外)
- 変更: requests/ に 2026-06-12_amazon_gshock_dump_ladies_tagging_response.md
- コード変更: 無し(merge未実装。実装時に両 file load)

### 検証(実機)
- 検証✅: 51 ASIN を md parse → 全51 が dump 4 file に実在
- 検証✅(重複): exclude_entirely(A/B)と重複0。exclude_amazon_available_only(C)と1件(B0CQC3TLRZ)重複→annotate
- 検証✅(JSON): gender_scope_tags.json valid・51 ASIN


## 2026-06-12 (続5) — Catalog: resolver.py に G-shock dispatch 追加(本実装・売上直結)

### 決定事項
- 決定1(真因配線): G-shock CSV が dedupe で10/10解決不能→入稿0件の真因=resolver.py の G-shock 未配線(旧 line134-136「別phase」後回し)。lookup_gshock(alias対応)は正常動作・配線だけ未実施だった。HQ greenlight で本実装。
- 決定2(実装): resolve() の _TCG_LOOKUP dispatch 直後に cat=="gshock" 分岐。signals["model"]→lookup_gshock→canonical product_id。model無/未収録/真1:N→""(fail-closed)。
- 決定3(import stale罠回避): module-level `import gshock_lookup as _gl`。sys.path[0:2]=自worktree設定済で最新alias版を掴む。resolver._gl.__file__ で自worktree版確認。
- 決定4(spec差分・無害): lookup_gshock は alias内部解決し canonical返す(GM-700G-9A→GM-700G-9AJF/alias_of=None)。spec の `alias_of or product_id` は防御維持だが実質product_id。

### 変更
- 変更: resolver.py:28-31(import _gl) / :128-142(gshock dispatch) / :150-151(旧コメント更新)
- 変更: tests/test_resolver_facade.py +5(canonical自身/bare→alias canonical/真1:N→""/未収録→""/model空→"")。旧 test_unsupported_category→test_gshock_no_model に改名。全296 green
- 変更: requests/ に 完了報告 _response.md
- commit: 1209241 (feature/uniqlo-ut)

### 検証(resolve() 実機出力)
- 検証✅: DW-5600RL-1JF→自身 / GA-V01SKE-6A→自身 / GM-700G-9A→GM-700G-9AJF(alias) / GW-9400J-1B→"" / NONEXIST→"" / model空・キー無→""
- 検証✅: resolver._gl.__file__=C:\dev\iMak_catalog\iMakCatalog\integrations\gshock_lookup.py(自worktree最新)
- 検証✅: 既存 TCG/DON/URL resolve 回帰なし(296 green)
- 検証⚠️(統合): dedupe側B/C(model抽出+gshock category検出)はDedupe担当。両揃って初めてG-shock CSV resolved。統合verifyはDedupe完了後(出品くんCSVで実件数)


## 2026-06-12 (続6) — Catalog: 日本版遊戯王 収録 feasibility 回答(調査のみ)

### 決定事項
- 決定(feasibility 結論): 日本版遊戯王収録は feasible・追い風大。実装着手は再開 greenlight 後(本回答は調査のみ)。推奨=(b) on-demand 部分収録(無在庫+Precision100%最適、低工数)。

### 調査結果(実機)
- yugioh_tcg=50,098行。2層: base passcode 12,150件(日英名+スペック保持) + print variant 37,948件(`{passcode}_{setcode}`)。
- print variant の言語は EN/PT/SE のみ=実質TCG(英語圏)。**JP(-JP) set code variant=0件**(HQ認識どおり)。distinct set code 610(全TCG)。
- **追い風: base 12,150中 11,584件が variants.konami_id + konami_jp_db(JP画像)リンク済**=日本版print取得を konami_id 駆動で回せる下地あり。
- lookup_yugioh は **set codeでなく名前fuzzy match**(subject→name_en LIKE+token一致、同名複数→fail-closed)。=JP set code(TDPP-JP018)を厳密に当てる経路が無い。
- 不足=JP(OCG)print情報のみ。schema/base identity は100%流用可(EN と同じ `{passcode}_{JP-setcode}` 追加)。
- 公式ソース裏取り: db.yugioh-card.com(遊戯王ニューロン)=Konami公式OCG DB、locale=ja・収録パック検索可=JP set codeの権威。YGOPRODeck はTCG専用でJP埋まらず別取得必須。
- 本体作業=① db.yugioh-card.com JP print scraper ② lookup_yugioh に set-code 経路追加。段取り=POC(1-2日, cert140273536 BLUE-EYES TDPP-JP018 で検証)→(b)本実装→必要なら(a)全scrape。

### 変更
- 変更: requests/ に feasibility 回答 _response.md(Q1-Q3)。コード/データ変更なし。


## 2026-06-12 (続7) — Catalog: PSA収録バッチ(S8a-P全25/Admirable Collection/G-shock2) + auto_catalog_add 4件

### 決定事項
- 決定1(S8a-P全25枚): HQ依頼+auto#014。公式pokemon-card.com で番号→名前確定→残24枚投入(010既存)で全25完成。#014=ミュウex/Mew ex(base弾#014=Bulbasaurと別体系)。name_en=catalog同名引き14枚+原典英名(Dark Gyarados等)、#013ロケット団の幹部のみ英名曖昧→空欄(fail-closed)。3AI誤BLOCKをcatalog解決で迂回。
- 決定2(Admirable Collection=多元再録): 原典番号保持(#063→OP12-063 / #068→OP06-068)。旧brand一律OP12固定が#068→Gin誤の原因。OP06-068_AC01+OP12-063_AC01投入、extract を OP12固定→"P"(番号駆動)変更+edition pair に ADMIRABLE 追加。両側一致=誤発火不能。
- 決定3(G-shock 2本): GA-V01CMG-6AJF(COLOR CAMO)/GM-2100LXB-1A9JF(LUXE BLACK)=CASIO公式裏取り(2026-06発売、1A9は実在色)。canonical suffix形で収録。
- 決定4(yugioh TDPP-JP018 保留): 本日feasibility対象cert。JP(OCG)刷り情報0でscraper+resolver経路要=実装は再開greenlight後。推測収録せず保留=fail-closed正。
- 決定5(missing_models.csv非改変): HQ所有pipeline artifact。解決済は今後resolveされ再検出されないため触らず、_processed報告で代替。

### 変更
- 変更: integrations/psa_to_csv.py — Admirable: marketing map OP12→"P" / promo edition pair に ("ADMIRABLE COLLECTION")
- 変更: tests/test_psa_review_promo_resolve.py +6(Admirable#063/#068/OP12非回帰、S8a-P Mew ex/Charizard)。全301 green
- 変更(共有DB・git外): S8a-P 24枚 / OP06-068_AC01・OP12-063_AC01 / GA-V01CMG-6AJF・GM-2100LXB-1A9JF。bak: s8aP_fullset / catalogadd_batch
- 変更: requests/ 回答 psa_catalog_gap_..._response.md + auto 4件 _processed
- commit: 7533644

### 検証(実出力)
- 検証✅(S8a-P): lookup_pokemon(brand,'014')→S8a-P-014/Mew ex。003→Blastoise/025→Tapu Lele-GX/010→Shining Magikarp
- 検証✅(Admirable): #068→OP06-068_AC01 / #063→OP12-063_AC01 / OP12 booster brand→OP12(回帰なし)
- 検証✅(G-shock): lookup_gshock GA-V01CMG-6AJF→自身 / GM-2100LXB-1A9JF→自身。CASIO公式実在裏取り
- 検証⚠️(残): Admirable vol.1 残promo2枚未識別(公式ac01.phpは「Promotion Card x4」のみ、cert無=低優先) / S8a-P #013英名空欄 / yugioh JP保留


## 2026-06-13 — Catalog: PSA実物画像バッチ照合 (6cert確定/Pikachu reject撤回/DON再整備) + cert混入対策 + 在庫表突合

### 決定事項
- 決定1(UTA確定): cert143402937 → ST16-001_p1 (顔アップ紫=_p1、_p2全身緑と別物)。ユーザー提供スラブで再scrape不要解決。
- 決定2(Pudding確定): cert86915908 → ST07-008_p3。スラブ set「PREMIUM CARD COLL -GIRLS ED-」は catalog _p3「ジャンプGIGA 2023 Spring応募者全員サービス」と**同一商品**(公式one-piece.com/tcg-fun裏取り)。gap/誤ラベルでなく別名。
- 決定3(**Pikachu V reject撤回**): cert142931332 → S8a-G-005。前回(続2)はメタbrand="POKEMON ASIA"でASIA版→言語誤り→rejectだったが、**実物スラブ「2021 POKEMON JPN」+券面日本語**=catalog日本語S8a-G-005と一致。実物優先で出品可。メタ(ASIA)vs実物(JPN)矛盾はHQ照合推奨。
- 決定4(DON×3解決): OP15gold→DON-OP15-002 / OP13gold→DON-OP13-002 (既存データ正、reject真因はメタがvariety「ALTERNATE ART-GOLD」をsubject未取込=入力欠落) / 1st anniv silhouette→DON-EVENT-003 (全11 DON-EVENT画像目視で唯一silhouette確認、hint追加で一意化)。
- 決定5(CELL reject維持): cert95157623=Dragon Ball Heroes H2-CP8=catalog対象外(dragonball_scgと別ゲーム)。
- 決定6(cert混入真因): preflight CATEGORY-UNKNOWN4件=全非TCGノイズ。1103264/1106551/1106686=montbell型番(在庫表HIGH列I・R列カテゴリ=アウトドア・ジャケット)、147130900=Ricky Pearsall(NFL・在庫表不在)。真因=cert抽出がR列カテゴリ未フィルタ。対策=cert抽出にWHERE R列カテゴリ='TCG' (HQ依頼書化)。

### 変更
- 変更(共有DB・git外): DON-EVENT-003 specs.psa_subject_hint に "1ST ANNIVERSARY" 追加。bak: _bak/DON-EVENT-003_specs_before_20260613.json
- 変更: iMakCatalog/tests/test_don_card_lookup.py +3 (OP13gold/1st anniv silhouette/generic EVENT回帰)
- 変更: requests/ に 2026-06-13_psa_image_batch_resolution_response.md / _cert_input_category_filter_request.md / uta001_rescrape_decision_response.md(解決追記)
- コード変更(resolver/lookup): 無し (DON gold は既存lookup_donで解決可・入力欠落が真因)

### 検証(実出力)
- 検証✅ lookup_don: OP15→DON-OP15-002 / OP13→DON-OP13-002 / 1st anniv→DON-EVENT-003 / generic EVENT→None(fail-closed維持)
- 検証✅ pytest: test_don_card_lookup 18 passed / 全 301 passed
- 検証✅ 在庫表(service account経由): R列='カテゴリ'、HIGH=TCG603他/LOW=G-shock507他。montbell3番号=HIGH行440/442/445列I・R列アウトドア・ジャケット。147130900=HIGH/LOW不在
- 検証✅ Pudding公式裏取り: Girls Edition=ジャンプGIGA 2023 Spring応募者全員サービス同一商品(one-piece.com news 61473 / tcg-fun)


## 2026-06-13 (続) — Catalog: 残アクション1-2-3 着手 (Pikachu subject-path / DON variety上流依頼 / cert抽出カテゴリフィルタ)

### 決定事項
- 決定1(① Pikachu V subject-path 実装): lookup_pokemon に「subject に GOLDEN BOX + brand が JAPANESE/JPN」→ set_code を S8a-G に上書きする経路を追加 (日本語 gate)。ASIA/KOREAN/CHINESE brand は遮断=言語誤り防止 fail-closed。cert142931332 固有は scrape brand が誤(ASIA)のため、正しい JP brand で再scrape すれば自動解決 (依頼書化)。
- 決定2(② DON variety = 上流fix): resolver/lookup_don (私側) は variety を含む subject で OP15→DON-OP15-002 / OP13→DON-OP13-002 / 1st anniv→DON-EVENT-003 と一意解決すると実証。真因は PSA scrape が Variety「ALTERNATE ART-GOLD」を subject に取り込んでいないこと(=上流/dedupe)。DON は parse_psa_page が#番号必須で listing pipeline では拾えず、解決は dedupe→resolver 経由のみ。→ HQ/Dedupe 依頼書で「signals['subject'] に Variety 連結」を依頼。
- 決定3(③ cert抽出カテゴリフィルタ 実装): load_targets_from_sheet_psa (iMakTCG/psa_to_csv.py) に R列カテゴリ=='TCG' 限定を追加。montbell型番(列I)が cert誤認され PSA に流れる混入を構造的に遮断。

### 変更
- 変更: iMakCatalog/integrations/psa_to_csv.py — lookup_pokemon に GOLDEN BOX subject-path (日本語gate) 追加
- 変更: iMakCatalog/tests/test_psa_review_promo_resolve.py — subject-path test +1 / ASIA reject docstring 訂正(実物=JPN)
- 変更: iMakTCG/psa_to_csv.py — load_targets_from_sheet_psa に category=='TCG' フィルタ + 除外件数ログ
- 変更: requests/ に 2026-06-13_psa_scrape_field_completeness_request.md (DON variety + Pikachu brand の上流依頼)
- コード変更なし(②): variety連結の受け口は signals 契約に無く上流責務

### 検証(実出力)
- 検証✅ lookup_pokemon: JPN brand+GOLDEN BOX subj→S8a-G-005 / ASIA→None / KOREAN→None / 通常Lugia→S8a-024(回帰なし)
- 検証✅ pytest: 全 305 passed (test_psa_review_promo_resolve 16 / test_don_card_lookup 18 含む)
- 検証✅ cert抽出フィルタ(実シート再現): 抽出条件該当208行 → TCG 199抽出 / 非TCG(montbell) 9除外。montbell・147130900 混入ゼロ
- 検証✅ 構文: iMakTCG/psa_to_csv.py ast.parse OK


## 2026-06-13 (続2) — Catalog: S8a-G (25th Golden Box) 全15枚の誤set是正

### 決定事項
- 決定(誤set是正): S8a-G(25th Anniversary GOLDEN BOX)全15枚の specs.set_name_ebay が誤って
  "25th Anniversary Collection"(=別product s8a の名)だった。Bulbapedia/eBay裏取りで Golden Box は
  Collection(s8a→eBay "Celebrations")と別の premium product と確認 → "25th Anniversary Golden Box" に是正。
  Pikachu V cert142931332 等が解決時に正しい set で出品される(誤set出品=出品の正確性違反 を予防)。
- 色は Pokemon 全entry で未保持(convention無)のため追加せず。rarity は Golden Box 個別裏取り要で今回保留。

### 変更
- 変更(共有DB・git外): S8a-G-001〜015 の specs.set_name_ebay → "25th Anniversary Golden Box" /
  set_name_official → "25th ANNIVERSARY GOLDEN BOX [S8a-G]"。bak: _bak/S8a-G_setname_before_20260613.json
- 変更: iMakCatalog/tests/test_psa_review_promo_resolve.py +1 (Golden Box set_name 是正の lock)

### 検証(実出力)
- 検証✅ lookup_pokemon(S8a-G-005)→ set_name_ebay="25th Anniversary Golden Box"
- 検証✅ 通常Collection 不変: lookup_pokemon(S8a-024 Lugia)→ "Celebrations" (S8a-G-% のみ更新、S8a-% は無変更)
- 検証✅ pytest: test_psa_review_promo_resolve 17 passed
- 検証✅ 裏取り: Bulbapedia "25th Anniversary Golden Box (TCG)" / eBay 実listing が "25th Anniversary Golden Box" 使用


## 2026-06-13 (続3) — Catalog: S8a-G enrich(finish/type) + 名前是正 + Pikachu V override 不採用判断

### 決定事項
- 決定1(enrich): Bulbapedia裏取りで S8a-G 全15枚に finish(001/002=Full Art Gold, 003-015=Mirror Holofoil) + energy_type(Pokemon 5枚=Lightning) を記録。eBay rarity は「Mirror Holofoil/Full Art Gold」が標準フィルタ値外のため blank 維持(fail-closed, 空欄>誤値)。
- 決定2(名前是正): S8a-G-014 name_en "Imitation Pokémon"(誤訳) → 公式英名 "Poké Kid" に是正(Bulbapedia)。
- 決定3(Pikachu V override 不採用): cert142931332 を override で即出品化する案は**不採用**。理由=Pokemon override 前例ゼロで card_number 形式/title selfcheck の end-to-end 挙動を検証不能(PSA scrape/creds要)、未検証 override は誤出品リスク=fail-closed違反。Pikachu V は Catalog側完了(code fix+set是正+enrich)で、HQ が正しい brand で再scrape すれば subject-path で自動 resolve する(HQ 1動作)。

### 変更
- 変更(共有DB・git外): S8a-G-001〜015 specs に finish/energy_type 追加 + S8a-G-014 name_en→"Poké Kid"。bak: _bak/S8a-G_enrich_before_20260613.json
- コード変更なし(override不採用)

### 検証(実出力)
- 検証✅ enrich: S8a-G-001 finish=Full Art Gold/type=Lightning, S8a-G-005 finish=Mirror Holofoil/type=Lightning, S8a-G-014 name=Poké Kid
- 検証✅ Bulbapedia 全15枚 rarity/type 突合済


## 2026-06-13 (続4) — Catalog: HQ依頼2件処理 (name_en romaji是正30件 / set_name_ebay誤map方針回答)

### 決定事項
- 決定1(依頼① name_en romaji是正): S10P-077 Kai→Irida。横展開で romaji転記 name_en を系統検出(katakana name_jp ↔ Hepburn romaji 一致)→5名30件是正: カイ→Irida(12)/トウコ→Hilda(6)/キハダ→Katy(5)/アズサ→Brigette(4)/シュウメイ→Ryme(3)。全て Bulbapedia/PSA 裏取り。ココ→Koko(映画キャラ=正の可能性)/グリ→Guri(不明)は fail-closed 保留。大半の katakana→ASCII(Drayton等)は正しい公式名のため誤検出回避。
- 決定2(依頼② set_name_ebay 誤map = 方針回答のみ・実装は合意後): JP限定ハイクラスパックが英語版main set名に誤map(S8b VMAXクライマックス→"Brilliant Stars"=英S9 等)。proposal1(パック自前英名化)に同意。明確誤りA群3set(S8b/SM12a/S9a)+△英ハイクラス相当B群5set(S4a/S12a/SM8b/SV4a/SV8a)=計8set/約1,972件が対象。既に自前英名の前例あり(Eevee Heroes/Dream League等)+本日S8a-G是正が先行例。bulk実装はHQ承認後。

### 変更
- 変更(共有DB・git外): Pokemon name_en 30件 romaji→公式英名是正。bak: _bak/S10P-077_name_en_before_20260613.txt
- 変更: requests/ に _pokemon_s10p_077_..._response.md / _catalog_set_name_ebay_for_tcg_feasibility_response.md
- コード変更なし(②は方針回答のみ)

### 検証(実出力)
- 検証✅ name_en: カイ→Irida残0 / トウコ6・キハダ5・アズサ4・シュウメイ3 全件更新。romaji一致7名中5名是正/2名保留
- 検証✅ 裏取り: トウコ=Hilda(White Flare) / キハダ=Katy(SV177) / アズサ=Brigette(BREAKthrough134) / シュウメイ=Ryme(Obsidian Flames194) 全Bulbapedia
- 検証✅ set_name_ebay 棚卸し: 誤map 8 set_code 特定(S8b 271件等)。自前英名前例4set確認


## 2026-06-13 (続5) — Catalog: set_name_ebay A群修正(BUILD) + 内部整合監査スクリプト新設

### 決定事項
- 決定1(A群bulk修正・HQ greenlight): JP限定パックの誤map3 set を自前英名に是正。S8b→VMAX Climax(271) / SM12a→Tag All Stars(194) / S9a→Battle Region(93)。各set_code内100%・旧値残0。残った旧英名は別の正当set(Astral Radiance残176=S10P/S10D=真のJP相当)で誤誘導でない。
- 決定2(監査スクリプト新設): iMakCatalog/tools/set_name_integrity_audit.py 新設。検査=era整合/set_code内不統一/source=(none)棚卸し。pokemon実走: era不一致0・不統一8・source(none)9,364件/84setcode。
- 決定3(新規エラー検出=HQ判断待ち): 監査が DPt3("Frontier's Pulse"vs"Beat of the Frontier") / DPt2 / DPt4 等 set_code内不統一8件を検出。greenlight範囲外のため未修正、正値指示待ち(順次つぶす方針)。
- 決定4(B群現状維持): HQ keyword判断(英版カウンターパート高検索・1:1で誤りでない)を受け S4a/S12a/SM8b/SV4a/SV8a は変更せず。

### 変更
- 変更(共有DB・git外): S8b/SM12a/S9a の set_name_ebay 558件是正。source→hq_greenlight_Agroup_20260613。bak: _bak/setname_Agroup_before_20260613.json
- 変更: iMakCatalog/tools/set_name_integrity_audit.py 新設(git tracked)
- 変更: requests/ に _A_group_BUILD_greenlight_response.md + set_name_ebay_integrity_audit_20260613.md(共有)

### 検証(実出力)
- 検証✅ A群: S8b 271/271・SM12a 194/194・S9a 93/93 = 新値100%・set_code内旧値残0
- 検証✅ 監査: era不一致0 / 不統一8(DPt2/3/4等) / source(none)84setcode 9364件。新規エラー検出を実証
- 検証✅ pytest 306 passed(回帰なし)


## 2026-06-13 (続6) — Catalog: character_name同期(30) + DPt dedupe + 監査が新規91件scramble検出

### 決定事項
- 決定1(① character_name 同期): 前回romaji name_en修正5名30件が specs.character_name 未同期(eBay C:Character が旧romajiのまま誤出品)→ character_name=name_en に同期。検証: name_en∈5名 で character_name≠name_en =0達成。
- 決定2(② 監査に検査4追加): set_name_integrity_audit.py に name_en≠character_name(両非空・接頭辞除外)検査を追加=再発防止。
- 決定3(③ DPt dedupe・低優先): HQ指示の多数派表記に統一。DPt2→Bonds to the End of Time(126) / DPt3→Beat of the Frontier(132) / DPt4→Advent of Arceus(124)。不統一 8→5。
- 決定4(④ ⚠️新規重大エラー escalation): 検査4が character_name scramble 91件検出(name_en=Treecko だが character_name=Magnemite 等、別カード由来)。promo系集中(XY24/SA19/M-P17/DPs11/SCS10/MG9/S8a1)。eBay C:Character 誤出品。card_type別re-derive要(Pokémon→種名/Trainer→空)で盲目sync不可→HQ greenlight待ち。

### 変更
- 変更(共有DB・git外): character_name 同期30件 / DPt2-4 set_name_ebay 102件dedupe。bak: character_name_sync_/dpt_dedupe_before_20260613.json
- 変更: iMakCatalog/tools/set_name_integrity_audit.py に検査4(name整合)追加
- 変更: requests/ に _romaji_fix_sync_..._response.md + 監査レポート更新

### 検証(実出力)
- 検証✅ character_name: 5名 desync=0
- 検証✅ DPt: 各set_code単一値。不統一8→5(残5はHQ triage済「正」)
- 検証✅ 監査検査4: 接頭辞除外後 91件 真desync検出(M-P/DPs scramble)。pytest 306 passed


## 2026-06-14 — Catalog: gshock CSV監査15件 切り分け (C:Movement修正 / C:Color=generator側)

### 決定事項
- 決定1(切り分け): csv_auditor自動依頼の gshock 8ASIN(C:Color/C:Movement空)を ASIN→model→catalog(lookup_gshock)照合。movement=7/8空・8番目もSolar Quartz / dial-band color=4/8在4/8空。
- 決定2(C:Movement修正=catalog gap・deterministic): 真因=catalog movement空(gshock 831/1555 systemic)+generator L893 Quartzデフォルトが adapter '' で無効化。全G-Shockはquartz(機械式不在=deterministic,推測でない)→catalog空movement 831件を"Quartz"補完。残0。将来flagも恒久解消。
- 決定3(C:Color=catalog外・flag): generator(gshock_to_csv.py L1040)が C:Band/Dial/Case/Bezel Color は出すが単一"C:Color"列を出力せず=monitor必須との フィールド名不一致(真因A,generator側)。+ 4 model(GST-W310-1A/DW-5900-1/MTG-B2000B-1A2/MTG-B3000D-1A)はcatalog色gap(真因B,公式裏取り要)。推測補完せずHQ greenlight待ち。

### 変更
- 変更(共有DB・git外): gshock movement 空831件→"Quartz"(deterministic)。bak: gshock_movement_before_20260613.json
- 変更: requests/ に _audit_catalog_fix_gshock_processed.md
- コード変更なし(C:Colorは generator/monitor側=HQ)

### 検証(実出力)
- 検証✅ movement: gshock 空831→Quartz・残0。lookup_gshock(GST-W310/DW-5900/MTG-B3000D)→Quartz
- 検証✅ generator: gshock_to_csv.py L1040 出力列に"C:Color"不在(C:Band/Dial/Case/Bezel Colorのみ)確認


## 2026-06-14 — Catalog: orphan chrome 点検 (version_main 自動検出化)

### 決定事項
- 決定1(点検結果): Catalog scraper は全て finally:driver.quit() 済(usage安全)。現 orphan 無し(検出された undetected_chromedriver 2個は Inventory稼働中cron run_cycle.py(PID30016)所属=worktree規約で不触)。
- 決定2(真因=stale pin): 実機Chrome=149だが Catalog scraper の version_main が 146/147/148 に手動pin(全stale)。Chrome自動更新でpinがmismatch→uc.Chrome()構築crash→drv未代入でfinally無効→orphan の温床。
- 決定3(硬化): version_main を実機Chrome自動検出に変更。scrapers/_chrome_version.py 新設(registry/exe からmajor検出、失敗時None=uc本体委譲)。各scraperは installed_chrome_major(旧pin) を使用(検出失敗時は旧pin fallback=無回帰)。auto-killは入れない(手動tool・ユーザーブラウザ巻込回避、Harvest方針と同じ)。

### 変更
- 変更: scrapers/_chrome_version.py 新設
- 変更: scrapers/gshock.py(3) montbell.py(1) workman.py(1) _dbfw_official_local_fetch.py(1) _gundam_official_local_fetch.py(1) = version_main 7箇所 自動検出化
- 注: iMakeBayAPI/ebay_sold_finder.py(146) は別プロジェクト=今回対象外(別途)

### 検証(実出力)
- 検証✅ 実機Chrome=149.0.7827.103 / installed_chrome_major()=149
- 検証✅ 全5 scraper 構文OK・hardcoded version_main=14x 残0・pytest 306 passed
- 検証✅ orphan 2個=Inventory cron(run_cycle.py)所属と確認し不触(kill前にCommandLine確認)


## 2026-06-14 — Catalog: gshock 4model色(真因B) + character_name scramble 91是正

### 決定事項
- 決定1: gshock 色gap 4model を公式裏取りで投入(真因B解消)。GST-W310-1A/DW-5900-1=Black/Black, MTG-B2000B-1A2=Black/Black/bezel Blue, MTG-B3000D-1A=Silver/Black。source=sakurawatches正規店+g-central+casio europe+Amazon公式。fail-closed(公式確認色のみ・型番code/画像推測不採用)。
- 決定2: character_name scramble 91件を Option A(character_name=name_en コピー)で是正。HQ greenlightの種名strip/trainer空 方針は撤回(新コア tcg_listing_fields が C:Character=character_name 無加工使用・character_name==name_en 前提と実機確認。実DB慣習も verbatim copy)。Pokémon57/Trainer23/Energy11。

### 変更
- 変更(共有DB・git外): gshock 4model band/dial/bezel color 投入。bak: gshock_color_4model_before_20260614.json
- 変更(共有DB・git外): pokemon 91件 specs.character_name=name_en。bak: character_name_scramble_rederive_before_20260614.json
- 変更: tools/gshock_color_4model_backfill_20260614.py / tools/character_name_scramble_fix_20260614.py 新設(commit 3dfd743, 3b03296)

### 検証(実出力)
- 検証✅ lookup_gshock 4model全て band/dial color+source 出力 / 監査検査4(name不整合) 91→0 / pytest 306 passed

## 2026-06-15 — Catalog: MC-227誤resolve / *_ebay 32,659件 / gshock cron / resolver gap

### 決定事項
- 決定1(番号衝突): cert149832553 Pikachu ex #227 が SI-227(Hippowdon)に誤resolve。スタートデッキ100(SI,/414)と スタートデッキ100バトルコレクション(MC,/742)は別set・両者#227実在。brand索引に "START DECK 100 BATTLE COLLECTION"→MC を plain "START DECK 100"→SI より前に挿入(公式裏取り card/48943,48717)。
- 決定2(*_ebay): generator無加工copy前提で TCG specs に eBay正規化フィールド投入。attack_power_ebay/defense_toughness_ebay/color_ebay/hp_ebay/stage_ebay。複数色=Multi-Color, DB power裏は表のみ, Gundam hp=defense分離, Pokemon stage(MEGA→Mega,基本/VMAX/VSTAR=空欄fail-closed)。Pokemon color/type raw無→color_ebay付与せず(HQ質問回答)。
- 決定3(gshock cron): DWE-5600PR-2/LOV-25A-7A を公式裏取り投入(g-central slug未定義+公式Akamai+shockbase拒否で標準経路不可のため sakurawatches+公式Casio)。
- 決定4(resolver gap): TCG取りこぼし39 brand triage。索引3追加(MIRACLE TWINS→SM11/SKY-SPLITTING CHARISMA→SM7/AMAZING VOLT TACKLE→S4)で解消。27件既RESOLVED。未収録/variant 8件分類(OP _AC01/_BS4 variant解決は別機構=HQ相談)。
- 決定5(pdca gshock): 層A gshock ~37件は全件既収録(missing_models stale)。真の未収録0件。g-central scraper実走(GA-100 upserted=0/skipped=41)+lookup全resolveで二重確認。

### 変更
- 変更: integrations/psa_to_csv.py(_POKEMON_SET_NAME_TO_CODE 索引4追加: MC/MIRACLE TWINS/SKY-SPLITTING/AMAZING VOLT)
- 変更: tests/test_psa_dropped_6_setmap_promo.py(回帰テスト2件追加)
- 変更(共有DB・git外): TCG 32,659件 *_ebay 投入(bak: tcg_ebay_normalized_fields_before_20260615.json) / gshock 2model追加(tools/gshock_cron_add_20260615.py)
- commit: b6c7345 / 116f9bf / ddd093b / 2e9ccde

### 検証(実出力)
- 検証✅ resolve KEY=MC-227(plain=SI-227回帰維持) / color_ebay・stage_ebay distinct全てeBay vocab内 / lookup_gshock 37件全resolve / pytest 307 passed
- 検証✅ 未解決bare GW-2320FP は色曖昧の fail-closed正常(実商品-1A1/-1A2は既存)

### 情報待ち(HQ)
- audit m62564964167 C:Rarity空: SKU→cert はHQ側のみ→cert/KEY受領後に rarity投入(catalog rarity gap濃厚)
- OP variant解決(_AC01/_BS4): set_code索引と別機構が必要=別依頼で設計相談
- pdca queue: gshock 37件は既収録のため missing_models再生成でdone化

## 2026-06-16〜06-21 — Catalog: PSA再仕入gap対応 / card_number_text / HQ8問 / 構造案件発見

### 決定事項
- 決定1(cert4件索引・公式裏取り): HQ cert dump+pokemon-card.com 照合で resolver索引3追加。EXTRA REGULATION BOX→BW(Zoroark=BW-014)/EMERALD BREAK→XY6-B(Gallade-EX=XY6-B-030)/NATIONAL BEGINNING→HSZm(Voltorb=HSZm-014)。
- 決定2(card_number_text): OP/Gundam/DBFW全件で specs.card_number_text空→出品タイトル#番号欠落。base=product_id.split("_")[0] で backfill + scraper3件恒久化。
- 決定3(HQ Q1 prune): missing_models の解決済を resolver.resolve()で除去。prune_missing_models.py 新設・実行(78除去/10keep)。
- 決定4(HQ Q6 SWORD): "SWORD & SHIELD SWORD"→S1W/"...SHIELD SHIELD"→S1H 限定フレーズ索引(era名衝突回避)。
- 決定5(Q8-I S1W/S1H是正): filter_map が S1W→Shield/S1H→Sword と逆だった既存bug是正(catalog set_name裏取り)。
- 決定6(THE BEST OF XY #030): HQ PSAキャッシュで name_en=Raichu が正と確定→一括再導出は却下(危険)、catalog変更なし。
- 決定7(構造案件・実装NG): 残backlog は2根に収束=①set_code overload(THE BEST OF XY/Q8-J cardID 1,122/Q5)②DBFW dual-source(1,415)。HQ承認で根①設計ドラフトのみ作成、実装はDedupe/HQレビュー後。
- 判定(空が正常): OP DON 265/Gundam Resource-Token-EXBase 206/DBFW EnergyMarker 257 は rarity無が正。cardID 438=Basic Energy は番号無で fallback正。

### 変更
- 変更: integrations/psa_to_csv.py(resolver索引: EXTRA REGULATION BOX/EMERALD BREAK/NATIONAL BEGINNING/SWORD&SHIELD SWORD・SHIELD)
- 変更: scrapers/one_piece_tcg.py・gundam_tcg.py・dragonball_scg.py(card_number_text 設定追加)
- 変更: ebay_filter_map/pokemon.yaml(S1W/S1H swap是正)
- 変更: prune_missing_models.py 新設
- 変更(共有DB・git外): card_number_text 16,420件 backfill / S1W-S1H set_name_ebay 136件再計算 / gshock WR正規化7+case_material1 / missing_models prune 78除去(bak: missing_models.csv.bak_prune)
- commit: cdd334d / 03201c3 / d2e78b2 / d1cbf05

### 検証(実出力)
- 検証✅ pre-commit pytest 231 passed(全commit) / resolver: EXTRA REGULATION→BW-014・EMERALD BREAK→XY6-B-030・NATIONAL BEGINNING→HSZm-014・SWORD-066→S1W-066 解決、FUSION ARTS→S8/AMAZING VOLT→S4 誤爆なし
- 検証✅ card_number_text 残空0(OP/Gundam/DBFW) / S1W→Sword・S1H→Shield 再計算後正値 / prune後 missing_models=10行(真backlog)
- 検証✅ DBFW二重ソース: dry-run で _dummy_s1 重複生成を検出→単純再ingest不可と実証 / Q8-J: cardID-33580→XY-028 が Xerosic と衝突=再ingest不可を実証

### 情報待ち/レビュー待ち(HQ/Dedupe)
- 根①設計ドラフト(`2026-06-21_root1_setcode_separation_design_draft.md`)→ Dedupe レビュー(live影響/rollback/alias配線)→ POC可否
- Q8-I set_name_ebay tail(4,217 set_name本体欠落・promo中心)= 件数順 (a) 他セラー調査で低優先
- PSA cert C:Rarity(S-P-071/M-P-020 等 rarity空)= Pokemon rarity 9,599 PDCA に集約
- psa_mismatch itemID→KEY シート記入 = HQ域 / missing_models auto-prune 恒久化 = 並行

## 2026-06-21〜06-25 — Catalog: Q8-I投入 / prune恒久化 / 画像backfill機構 / 日次HQ依頼 / 新弾チェック

### 決定事項
- 決定1(Q8-I (c') GO): set_name_ebay 未マップは catalog に翻訳元(set_name)無し→公開リファレンス確証分のみ自由文字列投入。CP概念パック5コードを web確証(TCGplayer/eBay)で投入。promo/starter 127コードは除外残置(Advisor承認)。
- 決定2(missing_models prune 恒久化, Advisor (b) GO): prune_missing_models.py に pdca.db improvement_queue done化を統合(CSV除去とセットで done→pending復活を断つ)。schtasks 日次04:00登録(Advisor承認)。
- 決定3(M2a casing): yaml="MEGA Dream ex" vs test="Mega Dream ex" 乖離を TCGplayer商品名規約(title case)で是正。
- 決定4(resolver索引5件): pdca/auto_add の missing 多くは索引不備。catalog実在を実機確認し索引追加=BANDIT RING→XY7-B/PHANTOM GATE→XY4/PREMIUM CHAMPION PACK→CP4/RED FLASH→XY8-Br/ULTRADIMENSIONAL BEASTS→SM4A。
- 決定5(画像backfill機構): pokemon-card.com resultAPI.php(pg+keyword, sm_and_keyword=true必須)→cardID→画像 の解決機構を確立。find_official_card + tools/backfill_pokemon_images.py 新設。
- 決定6(phantom誤断定の訂正・HQ feedback): SM12a-224/SV-P-291 を「公式DBに無い=phantom」と報告→HQがPSA現物cert(147571967=#224 FA UR / 146003969=#291 新pr)で実在確認。resultAPIはsecret-rare/未掲載新promoを返さない=image gapであり削除/rekey不可。ツール分類を unverified に訂正。
- 判定(HQ日次依頼): One Piece auto_add 7件=全て既存(投入不要) / Pokemon FAMILY-014・BLACK DECK KIT×2=真missing(旧世代/簡易版・対象外寄りkeep) / Weiss Schwarz=catalog対象外 / m接頭辞=Mercari非catalog-backed / PSA10 C:Rarity=Pokemon rarity backlog。
- 判定(新弾チェック 06-25): 4カテゴリ全て released新弾の収録漏れ無し。Pokemon M1L-M5/SV11B/W 公式件数完全一致。次弾は全て未発売(OP17=8月/GD05=7/24/FB11=9/12/Pokemon M6)。

### 変更
- 変更: ebay_filter_map/pokemon.yaml(CP1/2/3/5/6 追加 / M2a casing是正)
- 変更: prune_missing_models.py(prune_pdca追加=CSV+pdca.dbセット)
- 変更: integrations/psa_to_csv.py(_POKEMON_SET_NAME_TO_CODE 5件追加)
- 変更: scrapers/pokemon_tcg.py(find_official_card 新設) / tools/backfill_pokemon_images.py 新設
- 変更(共有DB・git外): Q8-I CP系221件 set_name_ebay / E01 Energy Marker 24件 game_ebay+set_name_ebay / S8a-P プロモ画像25件 / BW Extra Regulation Box 12件 / dbs-cardgame 画像URL 2823件置換 / OP05-091正KEY確定(=base)。各backup取得済。
- 変更(scraper・gitignore): _dbfw_official_local_fetch.py 画像パス /fw/jp/→/fw/ 是正(site renewal)。
- commit: fdd4e1b / b30dac1 / c873690 / dd5c53d / 2e55b8c / ebd5e7d

### 検証(実出力)
- 検証✅ pre-commit pytest 全commit pass(231 passed,1 skipped) / 全体 308 passed
- 検証✅ resolver索引5件 期待product_id解決(XY7-B-061/XY4-089/CP4-054/XY8-Br-056/SM4A-051)・回帰なし
- 検証✅ prune_pdca: done88件にresolver適用→78解決/10未解決=HQ genuine-open判定と完全一致(fail-closed正常) / schtasks Next Run確認・初回手動実行ログUTF-8
- 検証✅ dbs URL置換後 新URL5本 HEAD fetch全200(死URL0) / S8a-P card-1/13/25 全200 / E01-09_p1 game_ebay+set_name_ebay充足
- 検証✅ 新弾チェック: 公式resultAPI件数 catalog完全一致(M1L92/M2a250/M5 81/SV11B174等) / M6=0(未発売)

### 情報待ち/レビュー待ち(HQ/Dedupe)
- phantom依頼(SM12a-224/SV-P-291)= HQ「実在・是正不要」で確定(secret/新prの image gap、別フェーズで画像対応)
- OP06-068_AC01/OP12-063_AC01 = Admirable Collection alt-art(bandai API/CDN外)=専用fetch別フェーズ
- 根①/DBFW = root① A-2(resolver alias追従)緑待ちでブロック(先行不可)
- 次弾scrape: GD05(7/24)→OP17(8月)→FB11(9/12)→Pokemon M6 の発売時

## 2026-06-26〜07-01 — Catalog: 日次HQ依頼(resolver索引4件/scope判断/promo衝突/FA secret)

### 決定事項
- 決定1(resolver索引4件・catalog実在確認): PSA brand→set_code 逆引き欠落の偽missing を索引追加で解消。
  20TH ANNIVERSARY→CP6(cert135877490 Haunter=CP6-046) / BLUE SHOCK→XY8-Bb(青い衝撃, 既存#001-064救済) /
  DOUBLE BLAZE→SM10(SM10-033 Gengar) / TAG BOLT→SM9(SM9-038 Gengar&Mimikyu-GX)。全て実在を実機確認。
- 決定2(前回判定の訂正): Girls Edition Charlotte Pudding #008 = 前回「真missing」→ **既存 ST07-008**(Premium Collection は
  既存カードの parallel 再録で原番号維持)と訂正。同型: 1st Anniversary Otama=OP01-006_p4 既存。解決は subject 照合(viewer域)。
- 決定3(スコープ外の確定): DBH GALAXY MISSION 10 / GOD MISSION 1(Super Dragon Ball Heroes=アーケード)は catalog対象外。
  Super Divers 40th は Fusion World と別ライン=**HQ scope判断待ち**(収録は business 判断)。
- 決定4(promo番号衝突・推測追加せず): HQ「P-013 Sanji / P-006 Chopper 追加」依頼→公式API(EN+JA)は P-013=Gordon /
  P-006=Luffy のみで**官製に該当variant無し**。id_strict/推測禁止に従い**追加保留**、cert画像で真product_id同定を要請(Boa Hancock同型)。
- 判定(FA secret=既知ギャップ): BLUE SHOCK #061(M Glalie EX FA)/NIGHT UNISON #067/MIRACLE TWINS #112 = base番号超の
  FA secret。公式 resultAPI が secret-rare を返さないため未scrape(実在だが未収録)。HQ「実在だが不採用(K3)」skip と同型。
- 所見(dual-code): 20周年セットが CP6-NNN(91枚,PSA番号一致)と 20th-NNN(74枚,別番号: 046=Tauros)で二重保持=dual-source dup(root①下流)。

### 変更
- 変更: integrations/psa_to_csv.py(_POKEMON_SET_NAME_TO_CODE: 20TH ANNIVERSARY/BLUE SHOCK/DOUBLE BLAZE/TAG BOLT 追加)
- commit: 2346f36 / cfc47cb / 81c0ab5 / c04687b (全 push 済)
- 共有DB変更なし(索引はコードのみ。data投入は無し=既存/対象外/skipのため)

### 検証(実出力)
- 検証✅ 索引4件 期待product_id解決(CP6-046 / XY8-Bb-060 / SM10-033 / SM9-038)・25th非衝突・全commit 308 pass(pre-commit 231 pass)
- 検証✅ promo衝突: 公式API EN+JA とも P-013=Gordon/P-006=Luffy のみ=Sanji/Chopper無し実証(推測追加せず)
- 検証✅ FA secret: SM9a max#063<#067 / SM11 max#106<#112 = base超secret を実機確認
- 検証✅ Girls Edition=ST07-008 / Otama=OP01-006_p4 / OP04-039 Rebecca alt-art 実在(既存=投入不要)

### 情報待ち/判断待ち(HQ)
- P-013/P-006 promo衝突: cert(#148328055/#150414013/#145541765)の PSA画像 → 真KEY同定 → 必要なら premium variant整備
- Super Divers 40th: catalog に Super Divers ライン収録するか = scope/business 判断
- FA secret(BLUE SHOCK#061/NIGHT UNISON#067/MIRACLE TWINS#112): secret対応 fetch は別フェーズ(現状 fail-closed skip で整合)

---

## 2026-07-02〜07-20 — Catalog: 停滞catalog_add一括解消 / name_en中黒是正 / DBSCG alt-art回収 / Classic rarity訂正

### 決定事項
- 決定1(promo rarity=Promo 方針・Gemini裏取り): Pokemon promo専用セット(product_id が厳密 `-P` stem)の rarity 空は
  eBay公式facet値 **'Promo'** で一括backfill可と確定。「-P/-G = promo配布」は product_id から導かれる確定事実で推測でない
  (Gemini: TOPセラーのデファクト、facet設計上も整合、絶対原則に非違反)。第1弾1,012件 + 第2弾155件(M-P/MMB-P/S8a-P)。
  **例外**: Premium Champion Pack(CP4)等 reprint 系は束ねNG。
- 決定2(CP4/Classic は rarity 記号を持たない=空欄が正): CP4 は全リバースミラーホロで printed rarity 無し(HQ が日本一次ソース
  カーナベル【-】で確定)。**同型で Classic(CLK/CLF)も printed rarity 無し**と判明 → 2026-07-18 に CLK-008 へ入れた
  `'Rare Holo'` は**誤りのため空へ訂正**。Serebii の "Promo" 表示は no-symbol のプレースホルダで ingest しない。
- 決定3(Gundam Resource は rarity 概念なし): 公式(gundam-gcg.com)に rarity 欄が存在しない → RP-### の C:Rarity 空は正。
  HQ に「card_type=RESOURCE は C:Rarity 必須から除外」を回答。set は `限定商品収録カード → Promo Cards` を filter_map 登録。
- 決定4(DBSCG canonical=_PARA、alias化は依然保留): `_PARA`(bandai)/`_p1`(dbfw)重複216組は **216/216 で _PARA=rarity有 /
  _p1=rarity無** を実測 → canonical は _PARA(HQ の「_p1が正」案は C:Rarity 空を招くため不採用。2026-06-21 決定と一致)。
  **一括alias化は root① A-2(resolver alias追従)未完 + live≠0 で KEY orphan 化=BAN直結のため着手せず**(alias_of は gshock 243件のみ実測)。
  代わりに **read-side のみ**の回避策(下記変更)で誤除外を回収。
- 決定5(cardID-* fallback key backlog): 実在するのに `cardID-{数字}` で resolver が引けないカードが **1,559件**。
  sibling 導出 dry-run で mismap 実測(THE BEST OF XY→XY衝突 / 裂空のカリスマ3枚が同一キーに潰れる)→ **一括re-keyは禁止**、
  cert 到来時の on-demand re-key を採用(Yveltal #034 → XY11-034 のみ実施)。
- 決定6(スコープ外の確定): ITAJAGA DRAGON BALL(VOL.7/8)= カルビー系スナック封入 promo で Fusion World SCG ではない
  → dragonball_scg は誤カテゴリ、収録しない。PRB01 の set-level entry は card-level identity 抽出不能(set はフル収録1,673件)。

### 変更
- **resolver set mapping 追加**(いずれも catalog に record 実在の "偽missing" を解消): SOULSILVER→L1-Bss / HEARTGOLD→L1-Bhg /
  POKEKYUN→CP3 / DREAM SHINE→CP5 / SUPER-BURST IMPACT→SM8 / EX BATTLE BOOST→EBB / FAMILY POKEMON CARD GAME→SH /
  BLACK DECK KIT→BDK / BLASTOISE & SUICUNE→CLK / VENUSAUR & LUGIA→CLF / PLASMA GALE→BW7-B
- **resolver 挙動修正**: ASIA誤ラベルの25th Golden Box→S8a-G(cert142931332) / OP `Nth ANNIVERSARY SET` edition照合(cert84400496)
  / OP `GIRLS EDITION` edition照合 / Gundam `PREMIUM GOODS`→ST02+_PB01 variant優先 / card# 分母除去(005/015→005)
- **DBSCG alt-art 回収(HQ依頼)**: `lookup_dragonball` で _PARA/_p1 重複時 **rarity保持側(_PARA)優先** + `★`付き rarity を
  base コードへ正規化 + `Features='Alternative Art'`(L★→SCR/P・PR★→Promo/他は base)。**alias_of・KEY 非接触**。
- **catalog 追加**: SM12-112 / SM12a-214 / SM9a-067 / SM11-112(secret rare HR、公式resultAPI非掲載)/ EBB-045 / CP4-075 /
  CLK-008 / CLF-002 / CLF-015 / BDK-005・006 / XY8-Bb-061 / ST07-008_GE / ST02-010_PB01 / GA-V01CMG-3AJF・4AJF(G-SHOCK)
- **データ是正**: name_en 中黒(・)→ドット誤romanize **814件**(+ character_name 753件)、name_jp=NULL の取りこぼし **109件**
  (遊戯王 T.G./P.U.N.K./D.D. 等の正当省略名は保護)。Pokemon promo rarity **1,167件**。Gundam RP set_name_ebay **53件**。
  SH set set_name_ebay 53件 + V-rarity 6件。XY11-034 re-key。CLK-008 rarity 訂正。
- commit: 3957f6a〜85818a8(15commit、**全 push 済**)。共有DB は毎回 backup 取得。

### 検証(実出力)
- 検証✅ 全 231 pass(pre-commit)/ 回帰テスト新規追加: `test_batch_resolve_20260710`(21ケース)、`test_dbscg_para_rarity_recovery`(4ケース)
- 検証✅ name_en: `P-074→Portgas D. Ace` / `PRB02-005→Monkey D. Luffy`、`Monkey.D%`/`Portgas.D%` 残**0**、遊戯王 `D.D.*` **135件無傷**
- 検証✅ promo rarity: 厳密 `-P` stem の rarity 空 残**0**(M-P-020/S8a-G-005/S-P-126 等 'Promo')
- 検証✅ Gundam RP: 全53枚 C:Set='Promo Cards' 統一、公式に rarity 欄なしを確認
- 検証✅ DBSCG: cert158452539 FB01-071 / cert158452538 FB04-051 → **_PARA解決** + C:Rarity='SCR'(非空) + Features=['Alternative Art']、
  base(★無)不変。SR★→SR / C★→C / SCR★→SCR も実測
- 検証✅ rarity='?' 仮説の**否定**: catalog 全走査で `rarity='?'` は**0件**(verbose の '?' は None のデフォルト表示)→ bulk backfill 対象ゼロ
- 検証✅ 前回 daily_report で「未収録・別フェーズ」としていた **FA secret(NIGHT UNISON#067 / MIRACLE TWINS#112)を本期間で追加完了**

### 情報待ち/判断待ち(HQ)
- **m*/PSA10-* の card identity**: Mercari SKU は catalog 側から card 解決不能。ledger.jsonl も監査run要約のみで subject を持たない
  → set_code+番号 or subject の提供で即切り分け可(recurring な C:Rarity/C:Set 空の残件)
- **PRB01 cert の card-level raw**(set はフル収録済、cert の subject/番号が抽出できていない)
- **cardID-* backlog(1,559件)の方針**: on-demand re-key 継続 / BREAK・LEGEND系~25件の限定バッチ実施可否
- **DBSCG 216組 alias 化**: root① A-2(alias追従の全franchise共通化)完了 + Dedupe 4証跡が前提。順序厳守で未着手
- **DBSCG rarity facet の表記**: 現行 SSOT は短縮コード(SR/SCR/C…)。eBay 実facetが full name なら★に限らず全dbscg一括の別正規化が必要

---

## 2026-07-30 — 214KEY §2 revert + permission deny 追加

### 決定事項
- 決定1: commit 8a8f428 の `2nd ANNIVERSARY SET → 500 Years in the Future` mapping は誤り(箱名から一意 eBay facet 決まらず)。yaml/DB から削除 + 回帰テスト固定 (依頼: `2026-07-29_live_key_214_verdicts_response.md`)
- 決定2: worktree root に `.claude/settings.json` を新規作成し 17 deny ルールで即席不可逆操作を防止 (依頼: `2026-07-29_permission_deny_for_irreversible_ops_response.md`)。HQ 指示で `Bash(git checkout .*)` (broad glob) を `Bash(git checkout -- *)` + `Bash(git checkout .)` の 2 分割に修正

### 変更
- 変更: iMakCatalog/ebay_filter_map/one_piece.yaml:49-53 — `2nd ANNIVERSARY SET` mapping 5行削除、削除理由コメントに置換
- 変更: iMakCatalog/tests/test_live_key_36_gaps_20260729.py — TestOpPromoSetBackfill から OP06-118_p4 期待削除 + TestAnniversarySetRevertRegression 2 tests 追加 (`to_ebay_value` None / lookup set_name ≠ '500 Years')
- 変更: (DB) `DELETE FROM ebay_filter_map WHERE category='one_piece_tcg' AND field='set' AND source_value='2nd ANNIVERSARY SET'` 実行済 (1 row 削除)
- 変更: C:/dev/iMak_catalog/.claude/settings.json 新規作成 (17 deny rules)。**.gitignore で `**/.claude/` 除外のため commit されない** → 本 daily_report 記載が唯一の証跡
- deny 内訳: git push --force系 2 / git push origin master系 2 / git reset --hard 1 / git checkout 破壊系 2 (broad glob 回避で narrow 化) / git clean -f 1 / rm -rf系 4 (broad 2 + catalog固有 2) / DROP TABLE/DATABASE/TRUNCATE 3 / products.sqlite 誤上書き 2 = **本業 (prune_missing_models.py / scrapers/*.py / scripts/backfill_*.py / migrations/*.py / loader.py / pytest / git commit) 非該当**

### 検証(実出力)
- 検証✅ pytest -q → 383 passed (0 failed) / pre-commit hook 231 pass
- 検証✅ `api.to_ebay_value('one_piece_tcg', 'set', '2nd ANNIVERSARY SET')` → None (revert 確認)
- 検証✅ DB SELECT COUNT — 削除前 1 → 削除後 0
- 検証✅ settings.json JSON valid (17 deny rules loaded / defaultMode=bypassPermissions)
- 検証✅ `git check-ignore -v .claude/settings.json` → `.gitignore:114:**/.claude/` (期待どおり untracked)
- 検証⚠️ 「deny 発動の目視確認」は headless セッションでは実施不能 (現セッションが起動時に読み込んだ設定に基づく)。次の Catalog 通常セッションで `git push --force` を叩いて確認要 (`completion_must_be_proven`)
- commit: 98caa61 (§2 revert), + 本 daily_report commit

---

## 2026-08-11 — SSOT契約 set_name_ebay canonical UPGRADE (churn 恒久停止の第1弾)

### 決定事項
- 決定1: 「修正が修正を生む」根因 = 派生値 set_name_ebay が公式でなく producer(catalog)⇔consumer(出品側)で ratify された契約無しの手動マップだった。**全4カテゴリで SSOT インターフェース契約 v1.1 を締結** ([[tcg_ssot_contract_initiative]])。Q0 確定=4ゲームとも eBay カテゴリ 183454 単一 (入稿CSV+生成器hardcode 実証) → master は tcg.json 1本。
- 決定2: **3状態ルール** (master に canonical在→canonical / master無→英語自由文字列で維持(空より良い) / セット不明→空)。fail-closed は「カード同定」にのみ適用、Set等の説明文字列には適用しない (真値を捨てない)。旧「未マップ=空(2状態)」は誤り撤回。表記の正=長形(両形あれば人が読める形。A-2 集計で (b)410set が最大=canonical統一は不採用)。
- 決定3: ★**master canonical が常に正しいとは限らない**。第1弾一括9,465行がテスト5件と衝突し撤回(backupから復元)。Golden Box(S8a-G)は「Collectionにするな」の明示テスト有=set code一致でも別セット。**テストゲートが止めた=契約CIゲートの意味**。Advisor GO: 長形22 / Golden Box・Si・CP4 現状維持(テストにwhy追記) / SM4p 121件 canonical。既出品 eBay revision は後回し(ユーザー決定)。

### 変更
- 変更: iMakCatalog/migrations/2026-08-10_ssot_canonical_upgrade_testgated.py 新規 — 現値ベース canonical UPGRADE 8,726行 (跨ぎ衝突=OP「25th Anniversary Collection」→Pokemon S8a をコード照合で機械除外 / blanked の set_code fallback 不採用=Golden Box 誤merge回避 / Si・CP4 除外)。commit 3382b46
- 変更: iMakCatalog/migrations/2026-08-11_ssot_deferred_longform_and_sm4p.py 新規 — 長形15表記(Lost Origin→`Sword & Shield - Lost Origin`等)+ SM4p 121件(SM-P-145含)→`Sm4+: GX Battle Boost`。commit ea4367c、フォローアップ 2c1fda5
- 変更: iMakCatalog/tests/ 4本更新 — test_op_promo_backfill/test_st21_22_25_restamp を Ultra Prism 327→206 (SM4p 意図的 un-blank) / test_op_lets_start_and_mc(Si)・test_batch_resolve(CP4) に「なぜこの値か」why-コメント追記 (master盲信の書換を却下する根拠=蒸し返し防止, Advisor依頼)。+ test_ssot_deferred_20260811.py 新規7 tests (2c1fda5)
- 変更: (DB) set_name_ebay 計 **10,898行 canonical/長形化** (tag=ssot_canonical_upgrade_20260810)。Ultra Prism blanked 327→206。backup: pre_ssot_testgated_/pre_ssot_deferred_ + before-JSON 有

### 検証(実出力)
- 検証✅ pytest -q → **531 passed** (524 + 新規7) / pre-commit hook 231 pass
- 検証✅ SM4p-001 → `Sm4+: GX Battle Boost` / ロストアビス → `Sword & Shield - Lost Origin` / 超電ブレイカー → `Sv8: Super Electric Breaker`
- 検証✅ Ultra Prism blanked 残 = 206 (327-121 SM4p)
- 検証✅ 跨ぎ衝突除外: S8a に化ける OP 行数 = 0 (コード照合が op06/eb01≠s8a を機械排除)
- 検証✅ Advisor spot-check: 8,726行の危険語(Promo/Box/Anniversary/Collection/Deck/Champion) 該当4表記173行は全て実在セット名=Golden Box型ゼロ
- 検証⚠️ 撤回1件: 第1弾一括9,465行はテスト衝突で全撤回(backup復元・524 green確認済)。教訓=systematic一括も盲目だと新churn
- 未了(スコープ外): 導出化(焼き込み廃止=契約§1-5)は HQ co-sign 待ち。(b)自由文字列18,194/(c)判定不能3,853は3状態どおり不変
- commit: 3382b46 / ea4367c / 2c1fda5 + 本 daily_report commit

---

## 2026-08-13〜08-16 — rarity 生値の eBay 漏れ 完治 (1,238行 + 再流入経路2本)

### 決定事項
- 決定1 (①②判定): **① カタログの誤り / ② 出品側は正**。出品側は契約 v1.2 §1-1 どおり `specs.rarity_ebay` を素通ししており正しい。誤っていたのは catalog が派生値を作りきれず raw fallback で生コードを焼いていたこと。実害 = cert158452539 (FB01-071_PARA) の C:Rarity が `L★` → 禁止文字除去で `L` の1文字になり出品取り止め。
- 決定2: **★ / + は公式 rarity 語彙ではない**。公式を実取得 (2026-08-13): dbs-cardgame.com/fw = `L/C/UC/R/SR/SCR/PR` の7値のみ、gundam-gcg.com = `C/U/R/LR/LKC/LKU/LKR/P` の8値のみ。★/+ は刷り違い(parallel/alt-art)マーカーなので落として base を出し、意味は Features='Alternative Art' が持つ。旧 yaml `L★→SCR` は「Leader の刷り違いを Secret Rare と名乗る」誤りで廃止。
- 決定3: **gundam `LR` = "Legend Rare"** (公式EN gundam-gcg.com/en/products/gd01.html)。旧 `Leader Rare` は One Piece の LR を持ち込んだ誤り (Gundam に Leader カードは無い) → 337行是正。**one_piece `SPカード`** は公式EN "SP CARD" (asia-en 実取得) → eBay master 実在値 `Special` を採用 (118行が日本語のまま出ていた)。
- 決定4: **公式の長形名が確認できない code は推測で埋めず空欄** (MUR/BWR/C2/U2 等)。公式ポケカは rarity をアイコン画像でしか持たず名前が存在しないことを実測確認 → 「公式名が取れ次第」は永久に来ないため待ち方針を撤回。HQ 判断 (2026-08-16) で pokemon 10件は出さないで確定、one_piece 7件 (`_OP11_dummy`) は重複整理の別件へ。`SS` 12件はカード名に印字がある (`Ho-Oh LEGEND` / `Flareon Star`) ので写して `LEGEND` / `Gold Star` を投入 (HQ 承認済)。
- 決定5: データを直しても**取込側が raw を書き戻すなら新弾ごとに再発する**ため、入口を fail-closed 化した (下記変更3)。

### 変更
- 変更: iMakCatalog/api.py:271-297 — `derive_rarity_ebay()` / `has_rarity_variant_mark()` 新設 (★/+ を落として filter_map、miss は None = fail-closed。raw に degrade させない)
- 変更: iMakCatalog/ebay_filter_map/{dragonball,gundam,one_piece,pokemon}.yaml — rarity を eBay master 実在値へ canonical 化。★/+ 付き source は削除 (DB 側も migration で削除)。one_piece `L→""` (空=Leader 丸ごと skip の地雷) を `Leader` に是正
- 変更: iMakCatalog/migrations/2026-08-13_dbscg_rarity_ebay_canonical.py 新規 — dragonball 995行 (★921 + 短縮SCR74)、★残存0、921行に Features 追加。commit 22bca8e
- 変更: iMakCatalog/migrations/2026-08-13_tcg_rarity_ebay_canonical_all.py 新規 — gundam 1,045 / one_piece 126 / pokemon 67 = 1,238行。うち公式長形名不明の29行は空欄化 (fail-closed)。commit a8b920c
- 変更: iMakCatalog/migrations/2026-05-30_tcg_ebay_fields_phase_b_rarity.py — `resolve_rarity_ebay()` 末尾の `return rarity_raw` (raw fallback) 廃止 → filter_map 一本化、未登録は None。**新弾取込フローが毎回走らせる migration = 再流入の主犯**
- 変更: iMakCatalog/migrations/2026-05-30_dbfw_official_import.py:88-115 — `_derive_leader_rarity()` が alt_art LEADER に `('L★','L★')` と生値を書いていたのを `api.derive_rarity_ebay` 経由 (`('L★','Leader')`) に。commit 71db664
- 変更: iMakCatalog/integrations/psa_to_csv.py:404-410 — consumer 側の ★ 再変換を削除 (契約 v1.2 §1-1)。同ファイル edition pair に `8 PACKS BATTLE ↔ 8パックバトル` 追加で cert160317119 SANJI #004 → ST10-004_p1 を一意特定 (score=280、データ追加なし)。commit 19ec633
- 変更: iMakCatalog/migrations/2026-08-13_pokemon_ss_legend_goldstar.py 新規 — `SS` 12行 (LEGEND 9 / Gold Star 3)。commit a41442c
- 変更: iMakCatalog/migrations/2026-08-16_rarity_accepted_blank_mark.py 新規 — 出さないと決めた17行に `specs.rarity_ebay_status='accepted_blank_20260816'` (値は入れない)。commit ebb4414
- 変更: iMakCatalog/tools/set_name_integrity_audit.py — §7 新設 (`raw_stamped` / `map_drift` / `unmapped` / `accepted_blank` を毎日出す)。★0 でも出し続ける規約は §5§6 と同じ
- 変更: iMakCatalog/scripts/add_clf001_bulbasaur_20260815.py 新規 — Classic `CLF-001` フシギダネ 001/032 追加 (公式はカードリスト非公開のため先行3枚と同じく小売2社クロス確認、rarity 空が正)。commit 3f16b86
- 変更: 回帰テスト 5本追加 (test_dbscg_rarity_ebay_canonical_20260813 / test_tcg_rarity_ebay_canonical_all_20260813 / test_rarity_ingest_no_raw_regression_20260813 / test_op_8packs_battle_promo_20260813 / test_dbscg_leader_rarity_backfill 他)、旧挙動を固定していた既存6件を是正

### 検証(実出力)
- 検証✅ pytest -q → **607 passed** (231→607)。pre-commit hook 全 commit で green
- 検証✅ 監査マーカー: `rarity_raw_stamped=0 rarity_map_drift=0 rarity_unmapped=0 rarity_accepted_blank=17` (生コード漏れ **4カテゴリとも0件**)
- 検証✅ 公式再取得: dbs-cardgame.com/fw の rarity filter 7値 / gundam-gcg.com 8値 / asia-en.onepiece-cardgame.com "SP CARD" / pokemon-card.com card/35904 に rarity アイコン無し
- 検証✅ 実害カード FB01-071_PARA → `rarity_ebay='Leader'` + Features 'Alternative Art'、公式生値 `rarity='L★'` は保持 (SSOT は公式のミラー)
- 検証✅ phase_b migration `--probe` → 全カテゴリ 0件更新 (churn 無し = 現DBと入口ロジックが一致)
- 検証✅ 他 facet 点検: `*_ebay` に日本語混入 0 / 未変換 0 (identity は数値・英語で正常)
- 検証✅ cert160317119 → `ST10-004_p1 / Promo Cards / Common` (17候補中 score=280)
- 未了(HQ判断済でクローズ): pokemon 10件・one_piece 7件は空欄のまま = 出品されない。値が要るようになったら HQ から値付きで依頼が来る
- commit: 22bca8e / 19ec633 / a8b920c / 71db664 / a41442c / 3f16b86 / ebb4414 + 本 daily_report commit

## 2026-08-17 — /doctor: Claude Code 環境の健全化 + CLAUDE.md 導出可能内容の削除

### 決定事項
- 決定1: プロジェクト CLAUDE.md から**コードを読めば分かる内容は削る**。ディレクトリ構成 (`ls`)・SQLite スキーマDDL (`db/schema.sql` に実物)・API コード例 (`api.py` に実装、しかも4関数しか書かれておらず実物は13関数)・完了済 Phase 計画。残すのは決定事項・安全規則・非自明な運用 (禁止事項 / SSOT契約 / 画像規約 / 運用ルール)。
- 決定2: **Worktree 分離ルールの節を削除**。グローバル `~/.claude/CLAUDE.md` に同内容があり、**しかもプロジェクト側は branch 名が `feature/catalog-phase2` のまま陳腐化**していた (実機・グローバルとも `feature/uniqlo-ut`)。重複を消すことで矛盾も解消。
- 決定3: npm 版 Claude Code (2.1.136) は **Node.js/npm 自体がこのPCに無い**ため `claude update` が構造的に成功しない → ネイティブ版へ移行 (`claude install`)。

### 変更
- 変更: iMakCatalog/CLAUDE.md — 328行 → **185行** (10,943→5,862字、143行削除、est. -1,270 tok/セッション)。削除5ブロック = Worktree節 L3-28 / ディレクトリ構成 L64-92 / スキーマDDL L93-130 / APIコード例 L131-166 / Phase計画 L285-298
- 変更: (環境) Claude Code を native 2.1.233 へ移行 (`C:/Users/imax2/.local/bin/claude.exe`)。`installMethod` = native。旧 npm 版 432MB (`%APPDATA%/npm`) 削除。ユーザーPATH を `.local/bin` 1本に整理
- 変更: (環境) `~/.claude.json` `autoUpdates` を false → **true** に復帰 (インストーラ副作用で無効化されていた)。backup: `.claude.json.bak_doctor_20260817174759`
- 変更: (環境) `~/.claude/settings.json` `permissions.defaultMode` = `auto` (走査時は `bypassPermissions`)。allow 1216件 / hooks は保持。backup: `settings.json.bak_doctor_20260817173416`
- 未変更(意図的): `C:/dev/iMak_catalog/.claude/settings.json` の `defaultMode=bypassPermissions` は checked-in のため触らず。**このプロジェクトでは user scope の auto は効かない**

### 検証(実出力)
- 検証✅ `claude --version` → **2.1.233 (Claude Code)** / 解決先 `C:\Users\imax2\.local\bin\claude.exe`
- 検証✅ pytest -q → 607 passed (CLAUDE.md 削除後も回帰なし)
- 検証✅ `git diff --stat iMakCatalog/CLAUDE.md` → 143 deletions のみ (追加0)
- 検証✅ 削除前に `db/schema.sql` (6,428字/3 CREATE TABLE) と `api.py` の13関数の実在を確認 = 導出可能性の裏取り
- 検証⚠️ SessionStart フック `session_beacon.py` (timeout 20s): 18回中 median 0.9-1.2s だが **最大 29.7s** (resume時) / 11.8s (起動時)。セッション開始が待たされる。非同期化かキャッシュを要検討 (今回は未修正)
- 検証⚠️ 走査は直近50セッション/9プロジェクト/4日間。全1,979セッション中の一部
- commit: 本 CLAUDE.md trim commit + 本 daily_report commit

---

## 2026-08-21〜08-22 — 変換表を「推測」から「eBay 実データ照合」へ切替 (Catalog)

### 決定事項
- 決定1: **変換表の出所を eBay の Taxonomy API に固定する**。従来は
  `ebay_filter_map/pokemon.yaml` 冒頭に「eBay 値は推測含む、定期的に eBay UI で確認」と
  書かれたとおり推測ベースだった。`set_name_ebay` 絡みの依頼は4ヶ月で **269本**
  (うち裁定を含むもの165本) で、それでも 8月が最多。個別裁定では収束しないと判断。
- 決定2: **鍵を共有領域に置き、カタログが自分で eBay から取得する**
  (ユーザー実施)。以後「一覧をください」の往復が不要。
- 決定3: **表記は code 形が正** (`Si: Start Deck 100` / `S12a: Vstar Universe`)。
  窓口 Advisor 確定。2026-08-11 §3 の carve-out (`Start Deck 100` 等を読める形で維持) は
  **解除**。§3 は Game 別マスタが手元に無かった時点の判断のため。
- 決定4: **日本語版カードは日本語版セット名**。`Crown Zenith` 等の英語版名は誤記載。
  eBay には両方在るのでフィルタの都合では決まらず、**正確性だけで決まる**。
- 決定5: **埋めない項目を確定** — Finish (現物依存) / Age Level (CPSC) /
  Autographed (取扱なし)。監査で 0% と出ても穴ではない。
- 決定6: **変換表をブラッシュする手順を確立** (CLAUDE.md に記録)。
  空欄を見つけてもいきなり埋めず、理由を5つに分けてから動く。

### 変更
- 変更: `iMakCatalog/tools/fetch_ebay_aspects.py` — eBay の 35 aspect を自分で取得。
  取得日つきで保存し上書きしない (`_input/ebay_aspects_183454_<日付>.json`)
- 変更: `iMakCatalog/tools/build_aspect_frame.py` — 35項目を網羅した枠を生成。
  それまで変換表は **Set / Rarity の2項目しか無く**、残り33項目は素通しだった
- 変更: `iMakCatalog/tools/ebay_value_reconcile.py` — 変換表を eBay 一覧に照合し
  A(一覧に在る) / B(実際に使われている) / U(未使用) を自動判定。手で status を書けない
- 変更: `iMakCatalog/tools/restamp_set_name_ebay.py` — 変換表から引き直す。
  **格下げ禁止** (今の値が既に一覧に在るなら触らない)
- 変更: `iMakCatalog/api.py` — `derive_game_ebay` / `derive_manufacturer` /
  `derive_speciality` 新設。プロモの弾番号切り出しを修正 (`SM-P-052` を `SM` と
  切っていた。**同じロジックが2か所にコピー**されており両方直した)
- 変更: `iMakeBayAPI/credentials.py` — 鍵/トークンの置き場を決める口を1か所に
  (12ファイル16箇所が自前でパスを組み立てていた)。両方に在って中身が違えば警告
- 変更: `iMakCatalog/tools/set_name_integrity_audit.py` — §8「レアリティでない値の検知」
  追加。遊戯王も除外しない
- 変更: データ — 日本語セット名復元 2,652行 / code 形統一 1,121行 /
  Game 空欄 2,835行 / Manufacturer 89,138行 / Features 10,756行 /
  Speciality 2,324行 / プロモ弾番号 647行 / レアリティでない値の空欄化 118行

### 検証
- 検証: 657 tests green (pre-commit で全実行)
- 検証: canonical_drift **7,583 → 175** (`set_name_integrity_audit` 実測)
- 検証: `not_a_rarity=0` / `rarity_unmapped=0` / `rarity_raw_stamped=0` (日次マーカー)
- 検証: Game 空欄 **0** (全5カテゴリ / test_game_ebay_required_20260822)
- 検証: eBay API から 35 aspect 取得成功 (OAuth + Taxonomy、実走)
- 検証: `credentials.py` の二重配置警告が鳴ることを、古いファイルを置いて実測

### 止めた事故 (誤出品になっていたもの)
- 7-ELEVEN ルフィ #003 が **別カード** (`ST13-003_P` = ドルトムント collab) を返していた。
  PSA スラブ実写で券面 `ST13-003` を確認し `ST13-003_7E01` を追加 + edition pair で一意特定
- **2セットが1つに潰れていた** 265行 (フリーズボルト/コールドフレア、ガイアボルケーノ/
  タイダルストーム、コレクションX/Y、ハートゴールド/ソウルシルバー)
- レアリティ欄に **レアリティでない値** 118行 (`2` / `New` / `European debut` / `force-SMW`)
- 類似照合の暴発を3回阻止: `GX Battle Boost`→`Ex Battle Boost` (別セット) /
  `Sm Promo`→`Sm` (プロモ352件を通常セットへ) / `Promo Cards`→`FF: Promo Cards` (別ゲーム)
- **766行の塗り潰し**: 変換表の `MC → Movie Promo` が誤りで、一括適用していたら
  正しい値を消していた。dry-run の一覧で発見

### 未了 / 次セッションへの引き継ぎ
- **未回答の依頼 7本** (`iMak_data/catalog/requests/`)。今日の作業中に届いた通常分
- **766行の確認1件** — スタートデッキ100 バトルコレクション (MC) を `Si: Start Deck 100` に
  寄せるか。**別商品**で eBay に Battle Collection が無い。現状は分けたまま。窓口回答待ち
- **英語カード名** — `Ultra Ball` (英語版券面) か `Hyper Ball` (catalog 他 set) か。未回答
- **鍵の切替が未了の worktree** — 監視くん・抽出くん・リバイスくん。
  全員が共有側を見るまで本体側のファイルは消せない
- **ポケモンの Attribute/Color 0%** (22,111行) — eBay 側に受け皿が在り、他3カテゴリは
  100%一致。**こちらがタイプを持っていないだけ**。公式から取り直せば埋まる。今日の残件で最大
- **Grade / Card Condition の一覧が取れていない** — 35 aspect に含まれず。
  リスト外だと出品が弾かれる項目で、PSA10 を売る以上毎回使う。要調査

### 天井 (これ以上やっても伸びない)
- ワンピース / ガンダム / ドラゴンボールの **Set・Character・Card Name** — eBay に値が無い。
  `Luffy` は eBay の全2,052キャラを探しても `Fluffy` しか出てこない
- **DBSCG の Card Type** — eBay の Card Type はマジック/遊戯王/ポケモン/デジモン専用
- **Rarity の空欄** (ポケモン 8,515行) — 公式がレアリティを出していない。
  変換の取りこぼしは **0行**

---

## 2026-08-23 — 出品項目をカタログに一本化 / 誤ったセット名の検知を常設

### 決定事項
- 決定1 (ユーザー確定「シンプルが一番」): eBay の Set に入れる値は3行のルールだけ。
  ① eBay master に在る値 → verbatim / ② 無ければ日本語セット名の英語表記 (空欄にしない) /
  ③ 英語版の別セット名は禁止。**例外は作らない** (2026-08-18 の英語版セット14種の裁定を廃止)
- 決定2 (ユーザー確定): 公式が印刷番号を打っていないカード (基本エネルギー等) は先回りで
  登録しない。PSA の cert が候補に出た時だけ1枚ずつ内部キーで登録する
- 決定3 (HQ Q2): `Year Manufactured` は **PSA の鑑定年** (owner=listing)。catalog の
  `release_year` は社内用に残すが eBay には出さない
- 決定4 (HQ Q3/Q4): Cost / Attack/Power / HP / Stage は出す。Country of Origin はカタログが持つ。
  Franchise / Autographed / Vintage / Material / Customized は**出すのをやめてもらう**
  (Franchise の eBay 37値は Disney Lorcana の作品名だけで TCG に該当が無い — 実取得で確認)
- 決定5: 出品側と監査側がスリム化した分、**誤りの検知はカタログが持つ**

### 変更
- 変更: `ebay_filter_map/_contract_aspects.yaml` 新設 (35項目 + 出品側5列 = 40行)。
  source / emit / owner / reason / decided を固定。共有領域 `iMak_data/catalog/` にも出力
- 変更: `scrapers/_raw_store.py` 新設 — 取った生データを gzip で保管 (取り直しを不要にする)
- 変更: `scrapers/pokemon_detail_refetch.py` — 公式21,982枚を取り直し (失敗0)。
  regulation_set +15,679 / type_en +11,637 / attack_name +8,558 / set_name_official +1,886
- 変更: `scrapers/pokemon_tcg.py` — タイプ判定を `hp-type` 直後にアンカー。公式のクラス名は
  electric / dark / steel / none (lightning 等は存在しない)
- 変更: `migrations/2026-08-23_pokemon_type_reparse.py` — 生HTMLから 6,393行を再解釈 (通信0)
- 変更: `migrations/2026-08-23_dbscg_card_type_from_raw.py` — 生JSONから 2,753行 (50%→99%)
- 変更: `migrations/2026-08-23_jp_sets_use_own_value.py` — 英語版セット名 1,361行を日本語版の値へ
- 変更: `tools/set_name_integrity_audit.py` — §0 弾コード食い違い / §0b 未登録のセット名 を新設
- 変更: `tools/build_free_text_registry.py` + `_free_text_set_values.yaml` (162値) 新設
- 変更: Windows タスク `iMakCatalog_OfficialSiteRawArchive_Once` 登録 (8/24 01:12 / 約2,460URL)

### 検証
- 検証✅: `pytest tests/` **671 passed**
- 検証✅: 監査 §0 弾コード食い違い **0件** (4ゲーム)
- 検証✅: 監査 §0b 未登録のセット名 **0件** (4ゲーム)
- 検証✅: `type_en` に11タイプすべて出る (Psychic 2,271 … Fairy 270)。
  ピカチュウ=Lightning / ヤミラミ=Darkness / ハガネール=Metal を実データで確認
- 検証✅: Card Type ワンピ100% / DBSCG 99% / ポケモン98% / ガンダム96%
- 検証✅: Attribute 17% → 71% (ポケモンのタイプが入った)
- 検証✅: 生データ倉庫 34,049ファイル / 75MB (ポケモン21,982 / ワンピ6,273 / DB3,985 / ガンダム1,808)

### 止めた事故 (誤出品になっていたもの)
- **ピカチュウ 6,138枚が「闘タイプ」** — 公式のクラス名が `icon-electric` なのに `lightning` を
  探しており、見つからないと **弱点のアイコン**を拾っていた (ピカチュウの弱点=闘)
- **エクストラバトルの日 201行が別セット `The Best of XY`** — product_id `XY-003` が
  set_code `XY` に当たっていた (以前から危険視されていた「XY衝突」が実際に発生)
- **英語版セット名 1,729行** — `Sun & Moon—Celestial Storm` / `Scarlet & Violet—Mega Brave` 等
- **長時間走行が他の修正を巻き戻していた** — 取り直しツールが起動時のスナップショットを
  書き戻すため、走行中に直した 322行 + 14,716行が元に戻っていた
- **ワンピの Leader 503行が公式に無い cost を持っていた** — 公式 API の `Cost/Life` は
  Leader の場合ライフ。出品側が「読むだけ」になった瞬間に出るところだった

### 反省 (仕組みで潰した)
- 「`Swsh` で始まる値」という**思いついた条件**で確認して「0行」と報告した。実際には
  1,729行が誤っていた。**条件を思いつけるかに依存する確認は必ず漏れる**。
  → 許可された値の一覧 (① master + ② 登録簿) と突き合わせる §0b を常設。
  新しい誤りは登録されていないので必ず出る

### 未了 / 次セッションへの引き継ぎ
- **git push が未実行** — Claude Code の auto mode で拒否された。手動 push が要る (21 commit)
- 今夜 01:12 の生データ保管 (Windows タスク登録済・自動)
- `ST13-008_P1` (大文字) / `_p1` (小文字) の重複統合 — HQ に約束済
- クローン行の画像2件 (`ST07-008_GE` / `ST13-003_7E01`) — 公式ページの特定待ち
- Features 19% — レアリティからの `Full Art` 推定は**やらない** (裏が取れない)

### 天井 (これ以上やっても伸びない)
- ポケモンの Rarity 空欄 8,515行 — 公式ページにレアリティ表示が無い (実取得で確認)
- ワンピ / DBSCG / ガンダムの Set — eBay 側に受け皿が無い (DBSCG の37値は旧作のもの)
- Finish / Age Level / Autographed など13項目 — 出さないと決めたもの
- ★訂正: **DBSCG の Card Type は天井ではなかった**。eBay の Card Type は自由入力で、
  一覧に無い値も出せる。50% → 99% まで埋まった (8/22 のこちらの回答が誤り)

---

## 2026-08-24〜08-25 — 出品項目 21個を「見張る」か「閉じる」かに片付けた (Catalog)

### 背景 (ユーザー指摘)

> 「いつまで修正が続くの？新弾以外は出来たんじゃなかったの？」

セット名は終わっていた (§0/§0b/§0c すべて0) が、**他の項目に「合っているか測る面」が無く**、
出品して気づいた分が毎日上がってくる状態だった。項目ごとに面を作るか、出さないと決めるかで
1つずつ閉じた。

### 決定事項

- 決定1: **公式カードリストに無いカードも登録してよい**。ただし値の出所を限る
  (可=発売元の公式ページ+PSA スラブ実写 / 不可=ショップ・wiki)。公式が載せたら上書きする
- 決定2: **21項目を仕分け** — 見張る17 / 閉じる3 / 保留1
  (閉じた3 = Creature/Monster Type 出さない / Illustrator 取れるカテゴリだけ / Speciality ポケモンだけ)
- 決定3: **ST系のセット名は直さない**。①は正しく、②のタイトル生成が原因だった (HQ が撤回・自己修正)
- 決定4: **限定商品167行に商品名を書き足さない**。番号だけでは決まらず (154/167 が候補2〜8個)、
  商品名は既に公式由来の別行が持っている
- 決定5: **BS4 の36行は一度直して戻した**。出力は同じなのに canonical KEY が動くため割に合わない

### 変更 (計 11,427行 + 検査5面)

- 変更: `scrapers/pokemon_tcg.py` — 種別をカード名からの推定 (`"エネルギー" in name`) から
  公式の見出し (`<h2>グッズ</h2>`) に差替え。語彙7つが eBay の値と1対1
- 変更: `migrations/2026-08-25_pokemon_card_type_from_official.py` — 5,561行を焼き直し
- 変更: `migrations/2026-08-25_card_size_fill_constant.py` — 2,859行
- 変更: `migrations/2026-08-25_language_country_fill.py` — 2,859行 (遊戯王は対象外)
- 変更: `migrations/2026-08-25_type_impossible_fields.py` — 148行
  (ポケモン化石の HP 43 / ワンピ Leader の cost 105)
- 変更: `migrations/2026-08-24_ortega_is_not_arven.py` — 3行
- 変更: `integrations/psa_to_csv.py` — Pokemon の lookup に PSA Subject 名前照合を追加
- 変更: `tools/set_name_integrity_audit.py` — §10 Card Type / §11 定数 / §12 券面番号 /
  §13 種別が持ち得ない項目 を追加。戻りを位置参照から名前参照に変更
- 変更: `CLAUDE.md` — 上記の決定と「eBay の値リストの読み方」を明記

### 検証

- 検証✅: `card_type_unknown=0` — pokemon 22,111行すべてが eBay の正規値 (リスト外0)
- 検証✅: `const_violation=0` / `card_number_mismatch=0` / `type_forbidden=0`
- 検証✅: 券面番号と product_id の食い違い 0件 (4カテゴリ 39,041行)
- 検証✅: Pokemon の名前照合は目視OK 20件で誤検知0・真の誤り1件検出 (SV3-130 'Arven')
- 検証✅: Features の4値は eBay の39値内 (リスト外0行)
- 検証✅: pytest 773 passed / 1 skipped
- 検証✅: push 済 (`6197cb1..a14572f` → origin/feature/uniqlo-ut)

### 止めた事故

- 事故1: **Pokemon の lookup にだけ名前照合が無かった** (他3カテゴリは3〜7箇所)。
  番号さえ合えば別カードでも通る fail-closed の穴。入れる前に実データで誤検知0を確認
- 事故2: **オルティガ3行が `Arven`** (= ペパーの英名)。別人の名前で出品される状態だった
- 事故3: **ポケモン化石43行に HP60**。効果文「HP60のたねポケモンとして…」を拾っていた
- 事故4: **ワンピ Leader 105行に cost**。8/22 の修正が variant を取りこぼしていた
- 事故5: **language 穴埋めの前提チェックが遊戯王を検知して中止**。英語刷りのみのカテゴリに
  `Japanese` を書き込む寸前だった (ガードが効いた)

### 反省

**測る前に列名とキーを確かめる。** 今日3回、測り方を間違えた:

1. `card_number_text` を product_id と文字列比較し「不一致 21,515件」と誤報
   (`OP06-022` の番号を `06` と読んでいた)。正しくは **0件**
2. `attribute_ebay` / `cost_ebay` を見て「全カテゴリ0」と誤報。契約表の実列は
   `specs.color_ebay` / `specs.cost`
3. eBay の値リストを `aspects.<項目>.values` で読み「一覧が在るのは2項目だけ」と誤報。
   正しいキーは **`all`** で、実際は16項目に在る

いずれも**結論は変わらなかった**が、誤った数字で判断を進めるところだった。
3件目は CLAUDE.md に読み方を明記した。

**★一覧が在っても「許可リスト」ではない。** `constraint.mode` を見ること。
カタログが出す21項目のうち20項目が `FREE_TEXT` で、外れても eBay は弾かない。
選択専用は Country of Origin だけ (`Japan` は在る)。

### 残り

**Features 1項目のみ。** カタログ側は完了 (リスト外0行)。HQ 側の区切り文字
(`,` → `|`、commit `11d4b22`) を次の入稿で実物確認するのを待っている。

---

## 2026-08-25 追補 — 決定表 (`_contract_aspects.yaml`) を今日の内容に更新

### 背景 (ユーザー指摘)

> 「表はどう整理された？」

**整理できていなかった。** 役割表で「カタログが決めること = `_contract_aspects.yaml` が唯一の表」と
決めているのに、08-24〜08-25 の作業が反映されておらず `decided` が全項目 `2026-08-22` のままだった。
数字も **16項目でズレ**ていた (Language 86,279→89,139 / Card Size 同 /
Country of Origin 36,181→39,041 / Stage 16,673→16,152 / HP 16,622→16,579 / Cost 12,853→12,749 ほか)。

### 決定事項

- 決定1: **作業のたびに表を更新する**。表を直さずにデータだけ直すと、次に見た人が古い前提で判断する
- 決定2: 決定表の `reason` 欄に **監査の節番号**を書く (§9〜§13)。どの面が見張っているかを表から辿れるようにする

### 変更

- 変更: `tools/build_aspect_contract.py` — 決定表の14項目に理由と日付を入れ直した
- 変更: `ebay_filter_map/_contract_aspects.yaml` — 再生成 (共有コピー
  `iMak_data/catalog/_contract_aspects.yaml` も同時更新)

### 検証

- 検証✅: `decided` が `2026-08-25` の項目 = 14 (Game / Card Type / Speciality / Features /
  Manufacturer / Creature/Monster Type / Card Number / Language / Stage / Card Size /
  Illustrator / HP / Attack/Power / Defense/Toughness)
- 検証✅: 35項目中 決定済35 / 未決定0 / 出す22 / 出さない13
- 検証✅: pytest 773 passed / 1 skipped
- 検証✅: push 済 (`bfa1480..9a2d2f5`)

### 反省 (本日4回目の同型ミス)

**`Creature/Monster Type` を「全カテゴリ0%」として閉じたが、見ていた列が誤りだった。**

```
見ていた列: specs.creature_monster_type_ebay  → 0行
実際の列  : specs.creature_type_ebay          → 遊戯王 31,937行
```

閉じる判断そのものは変わらない (当社は遊戯王を1枚も出していない) が、**理由が誤り**だった。

本日の測り間違いは計4回で、全部「列名・キーを確かめずに測った」もの:

1. 券面番号を文字列比較 → 「不一致 21,515件」(正しくは0件)
2. `attribute_ebay` / `cost_ebay` → 「全カテゴリ0」(実列は `color_ebay` / `cost`)
3. eBay 値リストを `values` で読む → 「一覧は2項目だけ」(正しいキーは `all`、実際は16項目)
4. `creature_monster_type_ebay` → 「全カテゴリ0%」(実列は `creature_type_ebay`)

**対策: 測る前に決定表の `source` 列を見る。** 表に正しい列名が書いてあるので、
そこから読めば4回とも防げた。表を「更新する対象」ではなく「**最初に引く場所**」として使う。
