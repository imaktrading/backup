# PSA再仕入れ RESTOCK後工程 設計書 (2026-06-17)

## 0. 位置づけ
- 作成: HQ / 作成日 2026-06-17 / フェーズ: **設計(着手前)**
- 上流(実装済): PSA再仕入れ照合 = 絞り込み → 目視確認ゲート(①現物 vs ②catalog変種, KEY確定+資産化) →
  選択変種で Mercari/SNKRDUNK 探索 → 再仕入れ可/不能 を「PSA再仕入れ」タブ + 待ち台帳。
- 本書: 探索で **再仕入れ可** になったカードを、実際に eBay で **RESTOCK(出品復活)** する後工程。
- 規模が大きい("一大イベント")ため feasibility(済)→ **POC** → 本実装 で刻む。

## 1. 大前提(無在庫モデルとの整合)
- iMak は **無在庫(drop-ship)**。RESTOCK = 「今すぐ仕入れる」ではなく **出品を再び出品可能(qty=1)に戻す**こと。
- 実購入は **売れてから** Mercari/SNKRDUNK で行う。だから RESTOCK の条件 = 「**正しいカードの供給が
  存在し、売れたら確実に履行できる**」こと。視覚確証はこの「正しいカード×供給あり」を担保する。
- ∴ RESTOCK時に必要なのは: ①正カード確証 ②qty=1復活 ③出品情報の最新化 ④供給URL記録 ⑤スプシ整合。

## 2. 全体フロー(RESTOCK後工程)
```
[再仕入れ可リスト(探索結果)]
   ↓ Phase1 視覚確証ビューア(現物 vs 仕入候補画像, proxy)
[RESTOCK確定リスト(視覚一致OK)]
   ↓ Phase2 eBay revise (ReviseFixedPriceItem 1回/件)
      ├ qty=1 (出品復活)
      ├ Item Specifics 刷新 (確定KEY→catalog値)
      ├ Description 刷新 (テンプレ)
      └ Title 再生成 (keyword PDF順守)
   ↓ Phase3 スプシメンテ
      ├ PSA再仕入れタブ: RESTOCK実行済 マーク
      ├ 再仕入れ待ち台帳: 該当を解決(復活済)
      ├ 商品管理シート: 状態/補URL(供給) 更新
      └ 利益計算V8: 仕入価格(最安¥)反映 → 価格妥当性チェック
   ↓ Phase4 状態同期の安全 (全Phaseに横断)
      ├ revise後 GetItem で qty=1 を verify(fail-closed: 未反映は要対応に残す)
      ├ reconcile: 意図(RESTOCK)vs 実eBay状態 の突合audit、乖離ゼロを証跡
      └ 急増ガード: 一括revise急増時は停止して警告(誤一括復活防止)
```

## 3. Phase別 詳細

### Phase 1: 視覚確証ビューア (HQ / 作りかけ)
- 目的: keyword/画像検索の「確証」はテキストヒューリスティックで視覚証明ではない。RESTOCK(不可逆)前に
  **現物(出品PSA画像) vs 仕入候補(実際に買う Mercari/SNKRDUNK 出品の画像)** を並べ人手で視覚一致確認。
- 実装: psa_resource_confirm のプロキシHTML(画像はサーバ取得=ホットリンク回避)。
  - 候補画像解決: mercari item→静的CDN / snkrdunk product→og:image(実装済 `_resolve_image_url`)。
  - 各 再仕入れ可 行: 左=現物 / 右=仕入候補(最安+補)サムネ+価格+リンク / チェック「RESTOCKする」。
  - 返り: 視覚一致でONにした itemID 群 = **RESTOCK確定リスト**。
- スコープ: 探索した全件でなく **再仕入れ可だけ**(コストを確証に集中)。

### Phase 2: eBay revise (iMakRevise 領分 / 要POC)
- API: Trading **ReviseFixedPriceItem**(feasibility済: qty+specifics+desc+title+price を1回で更新可。
  対象は Active/OOS(qty=0)/OutOfStockControl のライブ出品 = revise可。End/Relist不要)。認証は ebay keys.txt。
- **★大原則(2026-06-18): Title / Item Specifics / Description / 価格 は、すべて『今の新規出品で使っている
  生成ロジックをそのまま流用』する。RESTOCK用の別ロジック・旧ロジックは作らない(ロジック一本化)。**
  = 新規出品と RESTOCK で出力が完全一致し、生成側の改善が両方に効く。
- 更新内容(確定KEY/cert起点、新規出品と同一生成):
  - **qty=1**(復活)
  - **Title** = 新規出品の title 生成(iMakTCG `title_generation`、keyword PDF順守)を流用・再生成。
  - **Item Specifics** = 新規出品の `tcg_listing_fields` 生成を流用(catalog値/eBay正規値/空欄の3択)。全面再生成。
  - **Description** = 新規出品のテンプレ生成を流用(最新版)。
  - **価格** = 新規出品の `pricing_engine`(現行)で算出。最安¥(仕入想定)等を入力に新規と同じ式で価格決定。
- 実体としては iMakTCG `psa_to_csv` の per-card 生成(title/specifics/desc/price)を cert/KEY 起点で呼び、
  CSVでなく revise payload に流す形が理想(新規生成のSSOTを一本流用)。
- 要検討: revise で title変更が Cassini に与える影響(=(a)で受容済) / 生成入力(median/cost)の供給。

### Phase 3: スプシメンテ (HQ)
- PSA再仕入れタブ: 「RESTOCK実行済(日付)」列を追加。
- 再仕入れ待ち台帳: 復活した itemID を「復活可→実行済」へ(墓場化させない)。
- 商品管理シート: 補URL(供給) 最新化(売れた時の仕入先)。状態列。
- 利益計算V8: 最安¥(仕入想定)を反映 → V8で利益妥当性を事前確認(赤字復活を防ぐ。mass_price_change の教訓)。

### Phase 4: 状態同期の安全 (横断・必須)
- `state_sync_safety`(CLAUDE.md)準拠: RESTOCK送信後に **GetItemでqty=1をverify**、未反映は同サイクル内
  リトライ→残れば「要対応」明示(silent成功と書かない)。
- reconcile audit: 「RESTOCK意図」vs「実eBay qty」を毎回突合、乖離ゼロを継続証跡。
- 急増ガード: 1回のRESTOCK件数が閾値超なら自動実行停止→警告(データ不具合での誤一括復活防止)。

### Phase 5: 仕入連動 (記録のみ)
- 無在庫なので購入は売れてから。RESTOCK時は **供給URL(最安+補)を商品管理シートに記録**しておき、
  売れたら即その URL で購入。視覚確証済なので「正しいカードを買う」が担保される。

## 4. 結合点 / 依存
- iMakTCG: tcg_listing_fields(Item Specifics) / title_generation(Title) / Descriptionテンプレ → Phase2で呼ぶ。
- iMakCatalog: 確定KEYの catalog値が source。未収録/誤は別途 catalog依頼(既存PDCA)。
- iMakeBayAPI: ebay_getitem_images(GetItem) 既存 / ReviseFixedPriceItem(新規, POC)。
- iMakRevise: eBay書込(revise)の実装主体 + 状態同期audit。

## 5. リスク / 未決事項
- Title変更のCassini影響(露出リセット) — 変えるべきか据え置きか要判断。
- Item Specifics 上書き vs マージ(既存の良い値を壊さない)。
- revise一括のレート/BAN(件数ガード + 間隔)。
- 利益V8反映の自動度(自動 or 人手確認)。
- 視覚確証の運用(全再仕入れ可を毎回見る負担 → 確定済skipの考え方を踏襲できるか)。

## 6. 刻み(進め方)
1. **feasibility**: 済(ReviseFixedPriceItem可 / ライブOOS revise可 / 認証OK)。
2. **POC-A(HQ)**: Phase1 視覚確証ビューア単体(RESTOCK確定リストを出すだけ。eBay書込なし)。
3. **POC-B(iMakRevise)**: 1件だけ ReviseFixedPriceItem で qty=1+specifics+desc+title → GetItem verify。
   生成は iMakTCG 流用で1件試す。Title変更の是非もここで判断。
4. **POC-C**: スプシメンテ + 状態同期audit(reconcile)を1サイクル。
5. **本実装**: POC結果反映 + 急増ガード + 全件E2E + 失敗注入テスト(completion_must_be_proven)。

## 7. 責務分担
| 範囲 | 主体 |
|---|---|
| Phase1 視覚確証ビューア | HQ |
| Phase2 eBay revise(qty/specifics/desc/title) | iMakRevise(生成は iMakTCG流用) |
| Phase3 スプシメンテ | HQ |
| Phase4 状態同期安全(verify/reconcile/ガード) | iMakRevise + HQ |
| catalog 値の正 | iMakCatalog |

## 8. ユーザー判断(2026-06-18 決定)
- **(a) Title = 刷新(再生成)**。理由: 旧ロジックで間違っている可能性があるため据え置かず作り直す。
  keyword PDF順守で再生成。Cassini露出リセットは受容(正確性優先)。
- **(b) Item Specifics = 刷新(上書き)**。理由: 旧ロジック誤りの可能性 + Description テンプレも更新済。
  既存値はマージ温存せず、確定KEYの catalog値 + eBay正規値で**全面再生成**(空欄は空欄=fail-closed)。
- **(b') Description = 刷新**(テンプレ最新版で再生成)。
- **(c) RESTOCK実行 = 手動(当面)**。視覚確証→**RESTOCK確定リスト**を出し、revise実行は人手GO。自動revise はしない。
- **(d) 利益V8 = 自動**。最安¥(仕入想定)を V8 に自動反映して利益妥当性を自動チェック(赤字復活を自動検出)。

### 決定の影響
- Phase2 は title/specifics/description を **3点とも全面刷新**(旧値温存なし)。生成は iMakTCG 流用。
- 実行は手動GOなので、Phase1ビューアの出力 = 「RESTOCK確定リスト(タブ)」。eBay書込は人手起動。
- V8チェックは自動で確定リストに「利益OK/赤字警告」を付す。
