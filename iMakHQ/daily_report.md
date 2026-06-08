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
