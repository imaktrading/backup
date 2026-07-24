# UNIQLO / GU Tシャツ URL → eBay 出品 Runbook（正本・必読）

> **トリガー**: ユーザーが UNIQLO/GU の商品 URL を貼って「出品作って/リスティング作って」と言ったら、**必ずこのファイルを最初に読んでから**着手する。メモリの自動呼び出しに頼らない。
> 最終更新: 2026-07-12（サイズ取得法を確立して追記）

---

## 0. 全体像
UNIQLO/GU 公式データ + main画像 から **eBay マルチバリエーション出品**（軸=Sizes、色は1listing1色固定）を作る。専用生成器は未実装 → 例listingを踏襲して作る。
- 例listing（GetItem して形式踏襲）: UNIQLO `358595544753` / GU `358711257418` / Women's全サイズ実例 `358764670607`

## 1. 公式データ取得（API・JSON）
`productId` は URL の `E483259-000` 部分。color/sizeDisplayCode も URL クエリにある。
- **UNIQLO と GU で host が違う（パスは同じ v5）**:
  - UNIQLO: `https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{productId}`
  - GU: `https://www.gu-global.com/jp/api/commerce/v5/ja/products/{productId}`
- 商品詳細（以下は UNIQLO 例。GU は host のみ差替）: `https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{productId}`
  - `result.name` / `result.colors` / `result.sizes`(名前のみ) / `result.composition`(=Material) / `result.countriesOfOrigin` / `result.longDescription` / `result.images`
- 在庫/バリアント: `.../products/{productId}/price-groups/00/l2s?withPrices=true&withStocks=true&httpFailure=true`
- **dns_cache 必須**（`sys.path` に `C:\dev\iMak\iMakeBayAPI` を足して `import dns_cache`）。DNS間欠対策。

## 2. サイズ実寸（仕上がり寸 inch）取得 ★ここが従来の詰まりどころ
**公式 JSON API に寸法は無い**（`sizeInformation`空 / `.../size-chart`は404）。`sizeChartUrl`(`.../size/<code>_size.html`)は **S3 AccessDenied で bot 直リン不可**。
**だが取れる** → PDP のサイズ表モーダルを自動操作:
```
cd C:\dev\iMak\iMakMercari
python uniqlo_size_fetch.py {productId} {colorCode} {sizeCode}
# 例: python uniqlo_size_fetch.py E483259-000 08 004
```
出力 = 全サイズ（XS〜3XL 等）の `身丈|肩幅|身幅|裄丈`（= Length|Shoulder|Chest|Sleeve, inch）。
（内部: PDP →「サイズを確認する」→「仕上がり寸」タブ →「inch」を uc.Chrome で自動click。Chrome majorはレジストリ検出・ハードコード禁止）
- 事前チャート `womens_ut_gu_sizecharts.md` は**フィット型ごと S〜XL しか無く端サイズ(XS/XXL/3XL)が欠ける** → **商品ごとに上記スクリプトで取るのが正**（2026-07-12 POP MART UT で漏れ発覚）。

### ★UNIQLO と GU の重要差異（2026-07-19 6商品で確立・厳守）
1. **`uniqlo_size_fetch.py` は uniqlo.com 固定**で GU には使えない。GU は `gu-global.com` の PDP を uc.Chrome で
   同じ手順（「サイズを確認する」→「仕上がり寸」→「inch」）で開いて読む。ボタン文言は共通。
2. **★サイズ表の列並びがブランドで違う。並べ替えず公式そのままの順で出す**:
   - UNIQLO = `身丈 / 肩幅 / 身幅 / 裄丈` = **Length / Shoulder / Chest / Sleeve**
   - GU     = `身丈 / 裄丈 / 肩幅 / 身幅` = **Length / Sleeve / Shoulder / Chest**（UNIQLOと肩幅・裄丈の位置が逆）
   値の対応さえ合っていれば良いが、Description の表は**公式の並び順に合わせる**（照合しやすさ・2026-07-19 ユーザー指摘）。
3. **キャラは main 画像を Vision で実確認**してから確定（longDescription 併用）。集合柄は代表キャラをタイトル/Characterに。

## 3. サイズ表記・マッピング
`US X (JP Y)` = US主 / JP括弧。**JP→US は one-down**: JP XS→US XXS / S→XS / M→S / L→M / XL→L / XXL→XL / 3XL→2XL。
- Women's は JP XS がある（XS/XXL/3XLはオンライン限定）→ 端まで出す。Men's は JP S スタート。

## 4. タイトル（~78-80字・SEO最優先・枠を余らせない）
**★正しい作り（2026-07-19 実 listing で確定。旧「ブランド先頭…Japan New」形式は誤り）**:
形式: `[作品] [キャラ] Anime Graphic Tee UNIQLO <UT|GU> Japan Exclusive [色] NWT`
- **作品・キャラを先頭**に置く（ブランド先頭にしない）。ブランド語は UNIQLO=`UNIQLO UT` / GU=`UNIQLO GU`（GUでも UNIQLO を併記＝SEO）。末尾は必ず `NWT`。
- 実 listing 例: `Evangelion Asuka Rei Shinji Anime Graphic Tee UNIQLO GU Japan Exclusive Gray NWT`（GU・80字ちょうど）
- 実作成例: `One Piece Sabo Flame Anime Graphic Tee UNIQLO UT Japan Exclusive Navy NWT`
- 80字に収まる範囲でキャラ数・`Exclusive`・アーク名を取捨（作品名が長い時はキャラ名を短縮 or `Exclusive` を落とす）。
- **出版社名/周年は入れない**（検索されない）。`Tee`(>T-Shirt) は必ず。メモリ `gu_uniqlo_official_variation_listing` と一致。

## 5. Item Specifics — 公式から差し替えるのは 🔴4つだけ、残り固定
🔴 = `Color` / `Character` / `Character Family(=作品)` / `Country of Origin`（Character はmain画像+longDescriptionで判定）
- **Color は公式の色名(`colors[].name`)をそのまま使う**。見た目で Light Blue 等に変えない（公式=Blue なら Blue）。2026-07-14 Light Blue 誤修正の再発防止。
固定テンプレ（eBay検索ボリューム順・これに🔴を差す）:
```
Brand=Uniqlo / Size=Regular - XS,S,M,L,XL,2XL,3XL,4XL / 🔴Color / Department=Unisex Adults(Women'sはWomen)
Type=T-Shirt / Theme=Anime & Manga / Sleeve Length=Short Sleeve / 🔴Character / Pattern=Graphic Print
🔴Character Family / 🔴Country of Origin / Features=All Seasons / Neckline=Crew Neck / Material=Cotton
Fit=Regular(loose系=Relaxed) / Vintage=No / Fabric Type=Jersey / Product Line=Uniqlo UT
Personalize=No / Handmade=No / Season=Fall / Year Manufactured=2020-2029 / Garment Care=Machine Washable
```
- **Material は公式 composition から**（画像推測禁止）。綿100%が標準だが blend なら要修正。
- **★Brand / Product Line はブランド依存**（2026-07-19）: UNIQLO → `Brand=Uniqlo` / `Product Line=Uniqlo UT`。GU → `Brand=GU` / `Product Line=GU`。
  上のテンプレの `Brand=Uniqlo` / `Product Line=Uniqlo UT` は UNIQLO 用。GU では GU に差し替える。
- Women's カテゴリ=**53159**(Women's Tops)/ ストアカテゴリ=`42213521010`。Men's=15687。Women'sは Fit に "Oversized" 無し→ loose系=**Relaxed**、語はタイトル/Descriptionで担保。

## 6. Description（例listingのHTMLテンプレを踏襲）
- 構成: ①コラボ紹介(公式longDescription翻訳) ②Product Specs(バリエーションはSize行削除=軸へ) ③**実測テーブル(全サイズ・列=Length/Shoulder/Chest/Sleeve, 行=US(JP))** ④Fit note ⑤**Sheerness(必須・落とすな)**。
- **★Sheerness(透け感)は公式API `result.designDetail` の「透け感: 〇〇」から取る**(なし→None / ややあり→Slight / あり→Yes)。推測禁止。
  - **★designDetail に透け感が無ければ Sheerness 行を省略する**（2026-07-19 改訂）。GU は designDetail が空のことが多く、UNIQLO も商品により無い。
    **値があれば必ず入れ、無ければ出さない**（「必ず1行」だと推測を招くため条件付きに変更）。ある時に落とす脱落は禁止（2026-07-14 Chiikawa 再発防止）。
  - designDetail には「トップスフィット: 〇〇」もあり Fit 判定の裏付けに使える（普通→Regular / ゆったり→Relaxed）。
- **★GU 商品のみ「About GU」段落を必ず入れる**（UNIQLO には入れない。UNIQLO は海外販売あり＝下記は虚偽になる）:
  `About GU — GU is the affordable sister brand of UNIQLO, exclusively available in Japan and some Asian countries. Not sold in the US/EU/UK/AU — this is a Japan-exclusive item.`
- 実測テーブルは **§2 で取った全サイズ**を入れる（端サイズを欠かさない）。
- ※Description は eBay内部検索に**非索引**（コンバージョン/Google流入用）。
- **出力形式 = デスクトップにコピペ用の完成HTMLファイル**（`C:\Users\imax2\OneDrive\デスクトップ\<商品名>_description.html`）。
  既存テンプレ（例listing 358764670607 の Description をベース）を読み込み、コラボ紹介文・Color・Available sizes・実測テーブルだけ差し替えて書き出す。ユーザーがブラウザ/エディタで開いて eBay の説明HTMLに貼る。
  参照実装: scratchpad `build_desc_e484483.py`（テンプレ→差替→デスクトップ出力の実例）。

## 7. バリエーション作成/追加（ReviseFixedPriceItem）
- 軸 = `Sizes`、値 = `US XS(JP S)` 形式。VariationSpecificsSet に全値 + 各 Variation に price/qty/specifics。
- **新規 variation にも SKU を必ず付ける**（無いと "SKU is required for eBay-fulfilled items" 警告。uuid可 例 `UT-<uuid4>`）。既存は SKU 維持で specifics 一致マッチ。
- API: `X-EBAY-API-CALL-NAME=ReviseFixedPriceItem` / IAF token(`ebay_oauth_token.json` access_token) / COMPAT=1271。Description は CDATA。
- 参照実装: このセッションの `scratchpad/revise_uniqlo.py`（全7サイズ追加+説明差替の実例。要れば iMakMercari に恒久コピー）。

## 8. 価格
¥→eBay は DDP送料テーブル + 利益計算 V8。既存 variation と同額に揃えるのが基本（全サイズ同価格）。

## 関連メモリ
[[gu_uniqlo_url_to_listing_workflow]] / [[womens_ut_gu_listing_workflow]] / [[gu_uniqlo_official_variation_listing]] / [[uniqlo_size_chart_fetch_method]] / [[uniqlo_material_from_official_not_vision]] / [[womens_ut_gu_sizecharts]]
