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
