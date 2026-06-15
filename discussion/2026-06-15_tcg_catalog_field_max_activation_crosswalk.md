# TCG catalog データ最大活用 — eBay aspect × catalog フィールド 全件突合 (2026-06-15)

発端: ユーザー「カタログにあるデータは最大限活用されているのか」→ 否。catalog は出品に必要な
公式情報を正規化済で持つ SSOT。generator は **catalog の eBay 値を copy するだけ**で最も完全・
正確な出品を作るべき。値の正規化(日本語→eBay語彙)は **catalog 側 `*_ebay` が担う**(既存
`set_name_ebay`/`rarity_ebay`/`card_size_ebay`/`game_ebay`/`card_type_ebay` と同じ設計)。

## eBay TCG aspect (cat 183454, 40個) × catalog 突合結果

### ✅ 既に新コアが使用 (13)
Game←game_ebay / Set←set_name_ebay / Card Type←card_type_ebay / Character←character_name /
Card Name←name_en / Card Number←card_number_text / Rarity←rarity_ebay / Features←features(正規化) /
Finish←finish / Illustrator←illustrator(Pokemon 594/600) / Card Size←card_size_ebay /
Language←language / Year←PSA cert。
静的/PSA: Grade/Graded/Professional Grader/Certification Number/Card Condition/Manufacturer。

### 🔧 catalog にデータ有・eBay aspect 有・**未活用** → 今回対応
| eBay aspect | CSV列 | catalog source | eBay制約 | 対応 |
|---|---|---|---|---|
| Cost | C:Cost(既存) | `cost`(OP/Gundam/DB=clean整数) | FREE_TEXT | **generator: raw直結=即活用済** |
| Attack/Power | C:Attack/Power(既存) | OP/DB `power`・Gundam `ap` | FREE_TEXT | catalog `attack_power_ebay`(DB値"15000 / (裏)20000"を正規化) |
| Defense/Toughness | C:Defense/Toughness(既存) | Gundam `hp`・YGO `def` | FREE_TEXT | catalog `defense_toughness_ebay` |
| Attribute/MTG:Color | C:Attribute/MTG:Color(既存) | `color`(緑/赤/BLUE=日本語混) | FREE_TEXT(値リスト有) | catalog `color_ebay`(日本語→eBay語彙) |
| HP | **C:HP(列追加要)** | Pokemon `hp`(564/600=clean) | FREE_TEXT | psa_to_csv 列追加 + catalog `hp_ebay` |
| Stage | **C:Stage(列追加要)** | Pokemon `stage`(たね等=日本語) | FREE_TEXT(9値) | psa_to_csv 列追加 + catalog `stage_ebay` |

generator は `_MULTI_SPEC_TO_COL` で `*_ebay` を優先 copy(空なら旧値温存=回帰なし)。
catalog が `*_ebay` を埋めた瞬間に自動で流れる(forward-compatible)。

### ⬜ 対象外 / N/A
- Franchise: eBay の値リストが Disney(Lorcana)専用 → 我々のゲームに該当値なし。スキップ。
- Creature/Monster Type: Pokemon のエネタイプ等。catalog に明確な source 無し(`color`は別物)。要 catalog 追加検討(後回し)。
- Age Level / Speciality / Material / Vintage / Customized / Autograph系 / California Prop 65 / Convention: 静的 or 我々の商材に無関係。
- Country of Origin: 静的 "Japan"(別途・catalog source でない)。

## eBay 正規語彙 (catalog 正規化の参照・実機 cat 183454)
- **Attribute/MTG:Color**(27値): Black, Blue, Colorless, Dark, Darkness, Divine, Dragon, Earth, Energy, Fairy, Fighting, Fire, Grass, Green, Ice, Light, Lightning, Metal, Multi-Color, Psychic, Purple, Red, Water, White …
  - Pokemon は energy type(Grass/Psychic/Fire/Water/Lightning/Darkness/Metal/Fairy/Dragon/Fighting/Colorless)が TOP セラー慣習。
- **Stage**(9値): Basic, Stage 1, Stage 2, Mega, Rookie, Champion, Ultimate, In-Training, Hybrid。Pokemon: たね→Basic / 1進化→Stage 1 / 2進化→Stage 2。
- **HP/Cost/Attack/Power/Defense/Toughness**: FREE_TEXT 値制約なし=数値そのまま可(要 clean)。

## フェーズ
- **Phase 1 (generator・完了)**: `_MULTI_SPEC_TO_COL` 配線。Cost 即活用。他は `*_ebay` 待ちで forward-compatible。
- **Phase 2 (Catalog 依頼)**: `color_ebay`/`attack_power_ebay`/`defense_toughness_ebay`/`stage_ebay`/`hp_ebay` を各ゲームで埋める(fail-closed=不明は空欄)。依頼書 `catalog/requests/2026-06-15_tcg_ebay_normalized_fields.md`。
- **Phase 3 (psa_to_csv・要go)**: C:HP / C:Stage 列を CSV ヘッダに追加(現行は列自体が無い)。
