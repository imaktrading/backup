# iMakCatalog — 全カテゴリ商品マスターDB

## 📦 DB の場所 (2026-05-03 変更)

`products.sqlite` は **`C:/dev/iMak_data/catalog/products.sqlite`** に配置 (worktree 跨ぎ共有)。

- 全 worktree が同じ DB を参照: `api._DB_PATH = Path("C:/dev/iMak_data/catalog/products.sqlite")`
- 旧 `C:/dev/iMak/iMakCatalog/db/products.sqlite` は当面残すが参照禁止 (移行確認後に削除予定)
- 修正箇所: `iMakCatalog/api.py` / `iMakCatalog/scrapers/gshock.py` (絶対パス化済)

---

iMak Trading Japan 全プロジェクトから参照される共通の商品データベース。
各カテゴリ (TCG / G-SHOCK / リール / ポーター 等) の公式DB をローカル SQLite に集約し、
listing スクリプトが `iMakCatalog.api.lookup(...)` で参照する。

---

## 立ち上げ背景 (2026-04-26)

### 直接トリガー
- 2026-04-25: cert #143570665 で PSA "PRB02-005" を bandai_jp 名前検索で **ST16-005** に誤マッチ → SR を Common として CSV 出力寸前 → 人力検出で水際阻止
- 2026-04-26: Pokemon カード13件全滅 (FA/プレフィックス未対応 + 辞書漏れ)
- どちらも「ハードコード辞書 + 正規表現」で公式DB lookup している限界

### 構造的な根本原因
- 各 listing スクリプトが個別に Bandai/Pokemon 公式サイトをスクレイプ
- 同名キャラの別カード誤マッチ / 新セット未対応 / 新ラリティ未対応 が日常的に発生
- 修正は対症療法 (辞書追加 / 正規表現拡張) の繰り返し → 構造的負債

### 解決アプローチ
全カテゴリの商品マスター (id / 公式値 / eBay フィルタ値) を**事前に SQLite に集約**し、
listing スクリプトは `api.lookup(category, product_id)` で**ID完全一致 lookup のみ**にする。
ID不一致 = 物理 reject、フォールバック禁止。

---

## listing スクリプト連携の原則

```python
# psa_to_csv.py 等の listing script
from iMakCatalog import api

# 1) ID完全一致 lookup を最優先
result = api.lookup(category="one_piece_tcg", product_id=psa_card_number)

if result is None:
    # 2) DB未登録 → CSV から物理排除 (フォールバック禁止)
    print(f"⚠️ iMakCatalog 未登録: {psa_card_number} → Skip")
    return None

# 3) DB値をそのまま採用 (推測なし)
specs = result["specs"]
set_name = result["set_name"]  # eBay フィルタ値で取れる
```

**禁止事項**:
- ID不一致時の名前検索フォールバック (← 昨日の Luffy ST16/PRB02 事故の原因)
- 公式DB値を推測で改変
- listing script 内でハードコード辞書を使う (Canonical Map 等は ebay_filter_map に集約)

### SSOT 契約 v1.2 §1-5 補足 — 導出化 = restamp + ズレ検知 (2026-08-12 制定)

契約 v1.2 §1-5 の「焼き込み廃止 → 導出化」の**実現方式**を確定:

**採用**: 現行の **migration restamp 方式**を正とする。
- catalog 側に stored 済 (`specs.set_name_ebay` に焼く)、yaml/filter_map 更新時は migration で一括 restamp
- scraper 側で毎回 `derive_set_name_ebay()` を呼ぶ (producer 側導出) はしない
  (yaml 更新のたびに全 scraper 再走が要る = churn 復活のため)

**却下**: producer 側導出 (scraper 埋め込み)。理由 = 上記トレードオフ。

**「古い値が焼き付いたまま誰も気づかない」の対策**:
- `set_name_integrity_audit.py` §6 canonical ズレ検知 (2026-08-12 実装) が担う。
- 定義: `specs.set_name_ebay ≠ derive_set_name_ebay(cat, set_name_official, product_id)`
  の行を category 別に絶対数で集計 (state (a) canonical のみ、state (b)/(c) は対象外)。
- **可視化のみ・gate にはしない**。0 になっても出し続ける (0 が続く証跡が唯一の証拠)。
- daily cron (2026-07-31 稼働) の完走マーカーに `canonical_drift=N` が出る (トレンド化)。

**依頼書**:
- `2026-08-10_ssot_contract_master_coverage_and_leaf_check_response_question_response.md`
  §item 1 [IMPLEMENT-GO] / §item 3 (producer 側導出) やらない決定

### 変換表をブラッシュする手順 (2026-08-22 確立) — この順でやる

**空欄や不一致を見つけても、いきなり埋めない。まず理由を5つに分ける。**
見た目は同じ「空欄」でも、打つ手が全部違う。

| 原因 | 例 (2026-08-22) | 打つ手 |
|---|---|---|
| **引き方のバグ** | `SM-P-052` を `SM` と切っていた (表は正しかった) | コードを直す |
| **表に行が無い** | `S-P` / `BWP` / `SV-P` | 行を足す |
| **表の中身が誤り** | `MC -> Movie Promo` / FB06 の日本語誤字 | 中身を直す |
| **eBay に値が無い** | ワンピの Set、DBSCG の Card Type | **天井。触らない** |
| **元データが無い** | ポケモンのタイプ、Finish、Rarity | 別作業 (取得) か、埋めない |

★分類せずに「空いてるから埋める」と動くと壊す。実例: 変換表の `MC` が誤りだったため、
  そのまま流し込んでいたら **正しい 766行を `Movie Promo` に塗り潰していた**。

#### 守ること 6つ

1. **正解表 (eBay aspect) は自分で取る。取得日つきで残し、上書きしない**
   `tools/fetch_ebay_aspects.py`。人からもらったファイルで進めると、
   それが何の一覧か確かめずに結論を出す (2026-08-21 に実際にやった)
2. **照合の範囲を先に決める** — Game 別か全体か。
   同じデータでワンピが 3% にも 20% にもなる。**測り方で結論が反転する**
3. **完全一致だけ採る。似ているものは採らない**
   2026-08-21〜22 に3回止めた: `GX Battle Boost`→`Ex Battle Boost` (別セット) /
   `Sm Promo`→`Sm` (プロモを通常セットに) / `Promo Cards`→`FF: Promo Cards` (別ゲーム)
4. **格下げ禁止** — 今の値が既に eBay の一覧に在るなら触らない。
   具体的なセット名を汎用のプロモ枠に落とすと情報だけ失う (17行が該当した)
5. **書く前に dry-run で組ごとの一覧を出し、目を通す**
6. **「やらない」と決めたことを書き残す** — 書かないと次に「0%だ」と言われて蒸し返す。
   4ヶ月 269本の依頼が出た原因がこれ

#### 埋めるより「測れるようにする」方が効く

2026-08-22 に eBay の **35 aspect を全部並べた枠**を作った (`tools/build_aspect_frame.py`)。
それまで変換表は Set と Rarity の **2項目しか無く**、残り33項目は素通しで
**ズレていても誰も気づけなかった**。枠がある = 測れる = 埋める対象が見える。

### 埋めない項目 (2026-08-22 ユーザー確定) — 「0%だ」と言われても埋めない

eBay の aspect を全35項目 並べたところ、埋率0%の項目が複数出た。
そのうち**意図的に空欄にしているもの**を記録する。監査で 0% と出ても穴ではない。

| aspect | 理由 |
|---|---|
| **Age Level** | **CPSC (米国消費者製品安全委員会) の関係**。対象年齢を出すと規制上の含みが生じるので現行どおり空欄 |
| **Autographed** | **サイン入りの取り扱いが無い**。`No` を出す実益が無く現行どおり |
| **Finish** | 現物依存 (下の節を参照) |

★これらは「データが取れない」のではなく「**出さないと決めている**」。
  埋める提案が来たら、この表を示して却下してよい。

### 番号が無いカード (基本エネルギー等) は登録しない — 欠番として起票しない (2026-08-22 ユーザー確定)

**公式が印刷番号を打っていないカードは、欠番に見えても欠落ではない。**

実測 (2026-08-22 公式 cardID 走査): S12a (VSTARユニバース) の欠番 251〜258 の正体は
**基本エネルギー8種** (草/炎/水/雷/超/闘/悪/鋼)。公式ページに `card_number_text` が無い。
catalog は印刷番号を product_id にしているので、構造的に入らない。

- **先回りで登録しない**。単価が安く PSA 鑑定に出る数が少ない
- **PSA の cert が候補に出た時だけ、その1枚を内部キー** (`S12a-E-KUSA` 等) **で登録する**
- 「欠番がある」という起票は不要。回答書:
  `requests/2026-08-22_hq_withdraw_two_missing_lines_response.md`

### Rarity の空欄 8,515行 は「公式に無い」= 天井 (2026-08-22 実測・蒸し返し禁止)

**ポケモンの rarity 空欄は取り直しても埋まらない。公式ページにレアリティが載っていない。**

2026-08-22 に「同じ弾の中で有り/無しが混在しているから取りこぼしでは」と疑い、公式を
実取得して確かめた結果、**混在は取りこぼしではなかった**:

| 確認したカード | 公式ページ | 結果 |
|---|---|---|
| S4a-009 (RR) | `rarity/ic_rare_rr.gif` **有り** | 取れている |
| S4a-001 | レアリティ画像 **無し** | 公式に無い |
| MC-001 (スタートデッキ100 バトルコレクション) | **無し** (regulation logo のみ) | 公式に無い |
| SI-001 (スタートデッキ100) | **無し** | 公式に無い |

つまり公式は **一部のカードにしかレアリティを表示していない**。scraper は表示されている分は
全部取れている (`ic_rare_*` + `ic_hikaru`)。

**やらないこと**: セット名や番号からのレアリティ推測。同じ弾でもカードごとに違うので当たらない。
**根拠が変わる条件**: 公式ページにレアリティ表示が増えた時だけ。

### Finish (キラかどうか) は空欄が正 — 埋めようとしない (2026-08-22 ユーザー確定)

**`specs.finish` は空欄のままにする。レアリティやセットから推測して埋めてはいけない。**

理由: **現物を見ないと決まらないから**。公式データに foil/holo を示す項目が無い
(one_piece の specs 33キーを全部見て確認済み)。

★レアリティからの推測は**できない**。同じカードにキラ版と通常版があり、
  **レアリティは同じ**。eBay の Finish は4値 (`Foil` / `Holo` / `Regular` / `Reverse Holo`) で
  `Holo` と `Reverse Holo` は別の値なので、レアリティで決めると誤った値が混ざる。

**例外**: 公式が「全カード foil」等と明記している商品だけ入れてよい。
実績 (2026-08-22 時点で 136行のみ):

    Holo             92行  ポケモンカードゲーム クラシック 3デッキ (公式が「all as foil cards」と明記)
    Holo             24行  プロモカードパック 25th (公式サイトで確認)
    Mirror Holofoil  13行  pokemon_card_jp が返した値

#### 蒸し返し防止

監査や棚卸しで「Finish が 0%」と出ても、**それは穴ではなく仕様**。
埋める提案が来たら、この節を示して却下してよい。
根拠が変わる条件は1つだけ: **公式データに foil/holo の項目が増えた時**。

### eBay "Set" 欄に何を入れるか — ルール案 (2026-08-21 / ★未確定・データ修正は禁止)

> **状態: 出品くんの回答待ち。** Gemini 二次検証は通したが、eBay の Set 値リストと
> Terapeak の検索データが出品くん側にしか無いため、**まだ確定していない**。
> ユーザー指示 2026-08-21:「出品くんと Gemini とすり合わせて、確定したら修正しよう」。
> **確定するまで 6,377行のデータ修正に着手しない** (1,539行の英語版セット名も含む)。
> 依頼書: `iMak_data/hq/requests/2026-08-21_set_name_and_name_en_need_ebay_facet.md`

```
① eBay の Set 値リストに在る正式値      → それを入れる
② リストに無い                          → 日本語セット名の英語表記を自由入力で入れる
                                          (★空欄にしない)
③ 英語版の別セット名で代用する          → 禁止
```

**これで終わり。例外を足さない。**

#### ②を「空欄」にしてはいけない理由 (2026-08-21 Gemini 指摘で訂正)

当初は「リストに無ければ空欄=出さない」にしていたが**誤り**。

- リスト外の値は **自由入力として通る**。出品は弾かれない
- 絞り込み (左サイドのフィルタ) には乗らないが、**キーワード検索にはヒットする**
- 正しい日本語セット名を入れるのは**誤記載ではない**ので、
  「間違った内容で出品しない」の原則には抵触しない
- 空欄にすると絞り込みにもキーワードにも乗らず、**安全性を1つも買わずに露出だけ失う**

→ 空欄が正しいのは「そのカードのセットが特定できない時」だけ。
  「eBay のリストに無い時」ではない。

#### ③を禁止する理由

日本語版「VSTARユニバース」のカードに `Crown Zenith` と書くのは、
**手元の現物が刷られた商品名ではない**ので誤記載になる。

★注意 (2026-08-21 訂正): 「Crown Zenith に VSTARユニバースのカードは収録されていない」
というのは**言い過ぎだった**。Crown Zenith は VSTARユニバースからの再録を多数含む
(アルセウスVSTAR UR 等)。禁止の根拠は「収録されていないから」ではなく
**「現物が刷られた商品は日本語版であって英語版ではないから」**。

#### ★このルールだけでは判断は消えない — 本体は変換表

Gemini 指摘: ルールは「リストに在るか確認しろ」と言っているだけで、
**確認作業そのものが人に残る**。根本は「信頼できる変換表が無い」こと。

**本当の成果物は「日本語セット名 → eBay 正式値」の1対1の変換表**で、
それが eBay の値リストから機械生成され、git 管理されていること。
`iMakCatalog/ebay_filter_map/*.yaml` を**推測ベースからリスト由来に置き換える**のが本丸。

依頼済: `iMak_data/hq/requests/2026-08-21_set_name_and_name_en_need_ebay_facet.md`

#### 適用 (2026-08-21 時点の実測)

pokemon_tcg で「変換表が言う値」と「行に焼いてある値」が食い違うのは 6,377行:

| 内訳 | 行数 | 扱い |
|---|--:|---|
| **英語版セット名が焼かれている** (Crown Zenith 等) | 1,539 | **③に該当 = 誤り。日本語セット名に戻す** |
| 表記違い (`Black Bolt` vs `SV11B: Black Bolt` 等) | 2,871 | **このルールでは裁けない**。変換表が要る |
| その他 (変換表が壊れている 766 を含む) | 1,967 | 個別。変換表側を直す |

#### バイヤーの検索についての注意 (2026-08-21 訂正)

当初「自社 live 4,449件のタイトルを数えたら日本語セット名14件 / 英語版0件」を
根拠に挙げたが、**これは自社の付け方を数えただけで、バイヤーの検索行動の証拠にならない**
(Gemini 指摘。循環論法)。

バイヤーの検索を測るなら **Terapeak の検索キーワードと Sold Listings** を見る。
これは eBay セラーツール = HQ 側。上の依頼書に含めてある。

#### Why (この規約が生まれた経緯)

`set_name_ebay` に触れた依頼書は 4ヶ月で **269本**、うち「裁定/確定」を含むものが **165本**。
それでも 2026-08 が最多 (98本) で減っていない。
原因は変換表の冒頭に書いてある: 「**eBay 値は推測含む、定期的に eBay UI で確認**」。
= 台帳が「推測 + 人が目で直す」前提で、新弾のたびに判断が要る作りだった。
165回の裁定はその場を埋めただけで、埋める仕組みは推測のまま残っていた。

### 画像 (images) の役割分担 — 両面カード規約 (2026-08-10 制定)

**catalog は表面 (front) のみ持つ。裏面 (back) は listing 側で規則導出する**。
根拠: 公式 API (bandai-tcg-plus.com/user/card/{id} 等) に back URL 独立フィールドが無い。
catalog の SSOT は「公式値のミラー」であり、規則導出値は SSOT ではない。

適用対象:
- **Dragon Ball SCG LEADER 型カード** — 両面。裏面 URL は front URL の
  `..._f.png` を `..._b.png` に置換で導出可能 (公式 dbs-cardgame.com / bandai-tcg-plus.com
  双方で規則性確認済)。
- 将来他カードで両面が増えた場合も同方針 (規則が壊れた時に案再検討)。

listing 側 (post_psa_review / CSV 生成器) の責務:
- `images[0]` は表面 URL とみなす
- LEADER 型の裏面表示が必要なら `_f→_b` 派生で URL を組立てる
- catalog record を勝手に mutate してはならない (SSOT は公式のみ)

例外条件 (将来 back を catalog に持たせるべきになる case):
- 公式 API が back URL 独立フィールドを追加
- LEADER 以外の両面カードが増え、URL 規則が壊れた場合

Why (履歴):
- 2026-08-09 依頼 `card_images_leader_back_and_pokemon_missing`: LEADER 裏面 catalog に
  0件 → HQ 側で規則導出済と確認 → catalog に持たせず listing 側の派生で完結、と方針明文化。

### 画像 (images) の第三者 source 例外規約 (2026-08-10 制定)

**原則**: images URL も SSOT = 公式のみ。第三者サイト由来を入れない。

**例外条件 (全て満たす場合のみ)**:
- 公式サイトに当該カードが**存在しない**ことが実測で確定している
  (公式 API hitCnt=0 + カード名・収録番号でも hit しない)
- 第三者サイトの画像内容が catalog の name / 収録番号 / セット と**全項目一致**することを
  人手で確認している
- 用途が**社内目視照合限定** (eBay 出品画像は PSA スラブ実写、この画像は表に出ない)
- `source` に第三者由来と分かる印を含める (例: `..._pcg_search_confirmed_YYYYMMDD`)

**適用実績**:
- 2026-08-10: BDK-005 / BDK-006 (pcg-search.com / 依頼書
  `2026-08-10_pcg_search_images_for_official_gaps.md`)

**取ってよいのは画像のみ**。name / rarity / set 等の値は絶対に第三者から取らない。

### 画像 (images) を構造的に持たない internal dedup KEY 規約 (2026-08-11 制定)

**catalog に画像が無いことが正しい record が一部ある**。以下の record は
`images` が空のまま維持し、「画像欠損」として起票しない (=目視枠の対象外)。

**該当条件**:
- `source` が `HQ_vision_character_poc` 等、公式 card_number を持たない出所である
- `specs.catalog_internal_key_note` に「公式 card_number 不明; Catalog 内で dedup KEY;
  eBay 'C:Card Number' 列には送信しない、AI 索 = dedup index で利用」相当の
  記述がある

**該当実績**:
- 2026-08-11: `DON-PRB02-BUGGY-GOLD` / `DON-PRB02-SHANKS-GOLD`
  (依頼書 `2026-08-10_missing_images_blocking_listing_response.md` §「B群 4件着手 GO /
  DON-*-GOLD は構造的に画像なしで正しい」で decisions 済)。

**Why (背景)**:
- これらは HQ 側 vision (PSA cert cache 実画像) で character 抽出し、dedup 用の
  internal record として登録した KEY。公式 card_number が存在しないため公式画像も存在しない。
- listing 生成器 (psa_to_csv 系) は `C:Card Number` にこれらを送信しない (dedup 索
  のみで利用)。目視 viewer が空 images を「欠損」と判定して再起票する誤検知を防ぐため
  明文化。

**画像0件監視 (image_backfill 系) の対処**:
- `source LIKE 'HQ_vision_%'` を除外条件に加える
- viewer は該当 record を「目視対象外」ラベルで表示 (現時点は起票をスキップするだけで十分)

---

## 運用ルール

### 新弾発売時
1. 該当カテゴリのスクレイパーを実行 (`scrapers/one_piece_tcg.py --update`)
2. 差分のみ DB に追加
3. ebay_filter_map/{category}_set.yaml に新セット名を追記 (eBay 表示値確認後)

### スクレイピング頻度
- TCG: 月1回 + 新弾発売直後
- G-SHOCK / リール: 四半期1回
- ポーター / モンベル: 半年1回 (商品入替少ない)

### バックアップ
- products.sqlite は Git 管理 (容量数十〜数百MB、Git LFS 検討)
- スキーマ変更時は migrations/ ディレクトリで版管理

---

## 横断的気づき・連携プロジェクト

- **iMakHQ**: プロジェクト一覧に iMakCatalog 追加済 (2026-04-26)
- **iMakeBayAPI**: 出力側 (eBay API)、こちらは入力側 (公式DB集約)、用途が独立
- **iMakAudit**: iMakCatalog の DB 整合性も監査対象に追加検討

## 関連メモリ

- `psa_bandai_brand_divergence.md` — プロモ二重国籍の許容パターン (Brand 文字列のみ判定の限界)
- `dual_gate_disagreement.md` — psa_to_csv ↔ check_csv の二重基準問題
- `gundam_bandai_tcg_plus_reliability.md` — fetch_card 誤ヒット問題
- `completion_must_be_proven.md` — "完了" 宣言は実走証跡で実証
