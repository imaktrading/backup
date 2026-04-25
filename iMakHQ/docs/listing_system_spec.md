# iMak Trading Japan eBay Listing System 再現性仕様書

最終更新: 2026-04-23 v3 (再現性フォーカス版)
作成: HQ (Claude) / 検証対象: Gemini

---

## 1. 本書の目的

**「ユーザーが一度指示したルールが、毎回100%再現性で実行されるか」** だけを検証する。

売上目標・ビジネス戦略・ROI 等は本書のスコープ外。

「再現性100%」 = SYSTEM_PROMPT (Claude依存・確率的) ではなく、**Python deterministic コードで物理保証されている**こと。

---

## 2. 再現性レイヤー定義

| レベル | 信頼度 | 例 |
|---|---|---|
| ⛔ レベル0: 指示のみ | 0% | ユーザー口頭指示、メモ |
| ⛔ レベル1: SYSTEM_PROMPT 記載 | 30-70% | Claude API への指示、確率的に守られる |
| ⚠ レベル2: メモリ/ドキュメント | 0-50% | 私 (Claude) が読まないと無効 |
| ✅ **レベル3: Python 実装 + 自動実行** | **100%** | コードがある限り守られる |
| ✅ レベル4: テストでカバー | 100% + 退行検知 | 修正崩壊時に即発覚 |

本書は各ルールが**レベル3以上**で実装されてるかだけを判定する。

---

## 3. 検証対象 4論点

ユーザーが繰り返し指示した懸念事項：

| # | 論点 | ユーザーの指示内容 |
|---|---|---|
| 3.1 | 価格設定 | 競合相場を反映した適正価格にする |
| 3.2 | タイトル | 70-79字 / variation正確 / ConditionID整合 / PDFキーワード活用 / 推測suffix禁止 |
| 3.3 | Item Specifics | eBay公式フィルタ正規値で全項目埋める / 必須欠落ゼロ / 異種商品 specs混入禁止 |
| 3.4 | 学習機能 | 同じ指摘を繰り返させない仕組み |

---

## 4. ルール別 再現性判定

### 4.1 価格設定

| 個別ルール | 実装場所 | レベル | 判定 |
|---|---|---|---|
| カテゴリ別 FVF/送料 SSOT 取得 | `iMakeBayAPI/profit_params.py` (GSheets連携) | レベル3 | ✅ |
| コストプラス + 利益率計算 | `iMakeBayAPI/pricing_engine.py:compute_listing_price` | レベル3 | ✅ |
| eBay competitive median を価格に反映 | `mercari_to_ebay_csv.py:898` で `compute_listing_price(cost, ebay_median=0, ...)` | **レベル0** | ❌ **median=0 固定** |
| カテゴリ別最低価格 | 一律 `$9.98` floor | レベル3 (一律のみ) | ⚠ カテゴリ別なし |
| ALERT 発生時に CSV 出力ブロック | 警告ログ出すだけ | レベル0 | ❌ |

**3.1 結論**: ❌ **競合相場反映は事実上未実装** (median=0 固定)

### 4.2 タイトル

| 個別ルール | 実装場所 | レベル | 判定 |
|---|---|---|---|
| 70-79字目標で物理パディング | `mercari_to_ebay_csv.py:1010` (if文内、reel限定) | レベル3 (reel限定) | ⚠ **mercari_to_ebay_csv.py の `--sheet=reel` 経路のみ** |
| ConditionID と Title 整合 (Pre-owned ↔ New) | `mercari_to_ebay_csv.py:980` (if文内、reel限定) | レベル3 (reel限定) | ⚠ 同上 |
| Amazon variation 正式タイトル取得 | `mercari_to_ebay_csv.py:fetch_amazon_title` | レベル3 (mercari_to_ebay_csv.py のみ) | ⚠ tshirt/montbell/gshock等で Amazon仕入時は未対応 |
| 推測suffix (H/HG/XG等) 禁止 | SYSTEM_PROMPT のみ "MODEL NUMBER 厳格ルール" 記載 | **レベル1** | ❌ Python検証なし |
| PDF top30 キーワード含有 | SYSTEM_PROMPT のみ | **レベル1** | ❌ |
| 80字超過の物理ブロック | なし (Claude 任せ + warning のみ) | レベル0 | ❌ |

**3.2 結論**: ⚠ reel限定では物理保証あり、**他5スクリプトは全て SYSTEM_PROMPT 任せ (再現性0-70%)**

該当スクリプト:
- `iMakMercari/tshirt_listing.py`
- `iMakMercari/montbell_listing.py`
- `iMakMercari/mercari_to_ebay_csv.py --sheet porter` (reel系の if 内に居ない)
- `iMakMercari/mercari_to_ebay_csv.py --sheet tomica` (同上)
- `iMakMercari/mercari_to_ebay_csv.py --sheet ichibankuji` (同上)
- `iMak_ichibankuji/ichibankuji_to_csv.py`
- `iMakG-shock/gshock_to_csv.py`

### 4.3 Item Specifics

| 個別ルール | 実装場所 | レベル | 判定 |
|---|---|---|---|
| 7カテゴリ enum/range/regex 定義 | `iMakeBayAPI/whitelist_registry.py:28,85,201,338,521,689,894` | レベル3 | ✅ |
| validate_and_normalize リトライループ | mercari_to_ebay_csv.py / tshirt_listing.py / montbell_listing.py / ichibankuji_to_csv.py / gshock_to_csv.py | レベル3 (5スクリプト) | ✅ (psa_to_csv は別メカ) |
| Plausibility range (異種商品 specs 検出) | `whitelist_registry.py:929,935,924` (reel カテゴリのみ) | レベル3 (reel限定) | ⚠ **他カテゴリ未定義** |
| max_length チェック (Features 65字等) | `whitelist_registry.py:946` (reel Features のみ) | レベル3 (reel限定) | ⚠ |
| matched_item の type_keyword 一致検証 | `shimano_jp.py:_is_valid_cached_specs` `daiwa_jp.py:_is_valid_cached_specs` | レベル3 (リール限定) | ⚠ |
| 必須項目空欄 → HOLD | `mercari_to_ebay_csv.py:959` (Brand のみ) | レベル3 (mercari_to_ebay_csv.py + Brand のみ) | ⚠ **他スクリプト+他項目 未対応** |
| eBay 公式 Required Fields との照合 | なし | **レベル0** | ❌ |

**3.3 結論**: ⚠ Whitelist は7カテゴリ整備済だが、**Plausibility/max_length/source verification は reel偏重**。他カテゴリは無防備。

### 4.4 学習機能

| 個別ルール | 実装場所 | レベル | 判定 |
|---|---|---|---|
| 過去指摘の物理的再発防止 (回帰テスト) | なし | **レベル0** | ❌ |
| 同じ指摘N回検出 → 強制実装タスク化 | なし | レベル0 | ❌ |
| listing後の自動 audit | なし (control_panel.py に未統合) | レベル0 | ❌ |
| iMakAudit 監査官の自動呼出 | iMakAudit/ あり、活用度ゼロ | レベル0 | ❌ |
| AI review_logs の listing 改善反映 | なし | レベル0 | ❌ |
| 3AI議論 (Claude+Gemini+Groq) の汎用展開 | `listing_validator.py:deliberate_3ai` (PSA/TCG限定運用) | レベル3 (PSA限定) | ⚠ |

**3.4 結論**: ❌ **学習機能は事実上ゼロ**。指摘の再発を物理的に防ぐ仕組み無し。

---

## 5. 再現性100%達成までの距離

| 論点 | 現状再現性 | 主要ギャップ |
|---|---|---|
| 3.1 価格 | 30% | competitive median 未取得 |
| 3.2 タイトル | reel: 80% / 他: 30% | 5スクリプトに Python強制ロジック未展開 |
| 3.3 Item Specifics | reel: 80% / 他: 50% | Plausibility/HOLD化未展開 + Required Fields照合無し |
| 3.4 学習機能 | 10% | 回帰テスト無し、自動 audit 無し |

---

## 6. ギャップ解消の最小実装セット (再現性100%へ)

> 売上目標やビジネス戦略は本書スコープ外。あくまで「指示通りに毎回動く」状態を作るための最小実装。

| # | 内容 | 影響 |
|---|---|---|
| ① | `iMakeBayAPI/listing_common.py` (作成済・未統合) を 6スクリプトに **import 統合** | 3.2/3.3 の reel限定機能を全カテゴリ展開 → 再現性 80% → 95% |
| ② | `iMakHQ/tests/fixtures_listing.json` + `test_listing_rules.py` 新設 (過去指摘事例を全件) | 3.4 の回帰防止 → 修正崩壊時に物理発覚 |
| ③ | `audit_csv_row()` を CSV出力前 final lint として全スクリプトで強制呼出 | 3.2/3.3 の物理ゲート完成 |
| ④ | `whitelist_registry.py` の Plausibility range / max_length を全カテゴリ拡張 | 3.3 の異種商品混入検知を全カテゴリ化 |
| ⑤ | `pricing_engine.py` で `ebay_median` を Browse API 動的取得 | 3.1 の唯一の未実装解消 |

①②③ で再現性100%に到達。④⑤は精度向上。

---

## 7. Gemini 検証観点

本書は**売上目標やビジネス戦略のレビューを依頼していません**。以下のみ判定願います:

1. **§4 の各 個別ルール について、「実装場所」「レベル判定」が論理的に妥当か**
   - 例: "reel限定" 主張は spec の grep結果で正しいか
2. **§5 の現状再現性パーセンテージが過大評価/過小評価でないか**
3. **§6 の最小実装セットで「再現性100%」と呼べる状態に到達できるか**
   - 不足してる項目があれば指摘
4. **再現性の文脈で見落としてる失敗モード** (例: 並行実行時のキャッシュ衝突、API障害時の挙動等)

**売上向上施策・カテゴリ戦略・在庫運用 等は本書のスコープ外なので回答不要**。

---

## 8. 検証コマンド (再現用)

各主張は以下で再検証可能:

```bash
cd "c:/Users/imax2/OneDrive/デスクトップ/iMak_workspace/"

# §4.1 価格: median=0 固定確認
grep -n "compute_listing_price" iMakMercari/*.py

# §4.2 タイトル: reel限定の if 文確認
grep -n "args.sheet == \"reel\" and len(title_en)" iMakMercari/mercari_to_ebay_csv.py
grep -rln "from listing_common\|import listing_common" iMakMercari iMakG-shock iMak_ichibankuji iMakTCG iMakeBayAPI

# §4.3 Item Specifics: Plausibility 定義箇所
grep -n "plausibility_range" iMakeBayAPI/whitelist_registry.py

# §4.4 学習機能: 回帰テスト存在確認
ls iMakHQ/tests/ 2>&1 || echo "tests ディレクトリ無し"
find iMak* -name "test_*.py" -o -name "fixtures*.json" 2>&1
```
