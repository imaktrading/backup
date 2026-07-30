# 送料・関税まわりの メンテ手順書

> **何かが変わったとき、どこを直せばいいか**の一覧。2026-07-31 制定。
> 変更のたびに「どの値がどこへ流れるか」を追い直すと事故る (実際に 2026-07-31 に
> グループ識別子を関税率と誤認して壊した)。**先にこの表を見ること。**

## 0. データの流れ (これを頭に入れてから触る)

```
V9スプシ 設定 E列(★グループ識別子) / F列(split)
   │  ※ E列は「関税率」ではない。0.18=A / 0.30=B / 0.43=C の識別子
   ↓  sync_sheet_to_yaml.py  (一方向・READY_TO_SYNC=ON 必須・split不一致でabort)
global.yaml  v6_pricing.groups  A/B/C の hts_rate・split
   ↓  pricing_engine.py:287
Policy送料 D = tier_upper × hts_rate × 1.021 × split + 1.5
   ↓
eBay Shipping Policy (DDP-A/B/C-Pxx) → 全 US 出品の送料
```

**別 SSOT (yaml 直接編集・同期対象外)**
- `global.yaml categories[].hts_duty_rate` … 真の MFN 税率の目安
- `global.yaml categories[].shipping_jpy` … **日本郵便で送った場合の想定送料**。実運送手段の実費ではない
- V9スプシ `EU送料マスタ` … EU25か国の実費・DDP収入・収支 (出典つき)

---

## 1. 関税が変わったとき

**★レートは料金表に載っていない。** Orange Connex の公式スタンス:

> 貨物の申告価値及び平均関税率に基づき、特定割合(**事前設定レート**)で算出される。
> 適用される事前設定レートは随時変更される場合があり、**最終的な決済は請求金額に基づく**
> — `RATE_GUIDE_SpeedPAK_Economy_JP_20260730.pdf` L430-437

→ **請求書が唯一の一次情報。HTS を引いても実請求は分からない。**

```bash
# 請求書 (xlsx) を置いて実効率を出す
cp <請求書.xlsx> C:/dev/iMak_data/shipping/invoices/
python C:/dev/iMak/iMakeBayAPI/invoice_duty_rate.py --dir C:/dev/iMak_data/shipping/invoices
# → 明細ごとの実効率 + 仕向地×月の集計。duty_rate_history.jsonl に追記され推移が残る
```

判断の目安:
- 実効率が **group の hts_rate より十分低い**状態が数ヶ月続いたら、group を下げる検討
- **下げる = 回収不足側**。取り過ぎは安全側なので、サンプルが薄いうちは動かさない
- group 値は「**+5% buffer 込み**」の設計。buffer を消さないこと

米国側は制度が短期で動く (2025-09 相互関税15% → 2026-02-20 最高裁で無効 →
一律10% Section122 → **2026-07-24 失効**)。**制度ニュースではなく請求書で判断する。**

## 2. 送れる国が変わったとき

| 変更 | 直す場所 |
|---|---|
| 発送除外国を足す/外す | `ebay_exclude_regions.py --add/--list` (全ポリシー一括) + 管理スプシ |
| EU の対地が増減 | V9スプシ `EU送料マスタ` に行追加/削除 (国コード・段階$・基本料金・TPC手数料) |
| rate table の段階変更 | **eBay UI 専用・API不可**。`ebay.com/ship/rt/details/5296250010` を手作業。<br>順序厳守: ①新しい行を**追加** → ②古い行を**削除** (逆にすると発送可なのに料金なしの穴) |
| 日本郵便の引受停止など | `jp_post_eu_suspension_*` memory と `SPEEDPAK_COVERAGE.md` を更新 |

## 3. 運送会社を変えたとき

1. `SPEEDPAK_COVERAGE.md` の対地・料金・制約を更新 (PDF を `iMak_data/shipping/` へコピー)
2. `EU送料マスタ` の「基本料金」「TPC独自手数料」を新料金表の値に
3. **listing の配送サービス名**を差し替え — `de_mirror_fedex_removal.py` と同型のスクリプトで
   `ReviseFixedPriceItem` に inline 焼込 (ポリシー編集は eBaymag ミラーには効かない)
4. 価格帯で手段が変わるなら **成約額で判定** (出品価格ではない)。`offer_calc.py` の `shipInfo()` を更新

## 4. カテゴリを追加したとき

1. V9スプシ `設定` A11:F30 に行追加 — **E列は 0.18/0.30/0.43 のいずれか** (グループ識別子)、F列は split=1
2. `global.yaml` の `categories`(実送料・真のHTS) と `v6_pricing.category_to_group` に追加
3. `sync_sheet_to_yaml.py` を走らせる (READY_TO_SYNC=ON が必要)
4. **新カテゴリ初回は Item Specifics の項目構成を他セラーから調査**してから出品 (グローバル規約)

## 5. 発送先 (仕向地) を追加したとき

1. `EU送料マスタ` (EU なら) に行追加 / 非EU なら `SPEEDPAK_COVERAGE.md` に対地追記
2. shipping policy の `shipToLocations` と rate table に追加
3. `offer_calc.py` の `CUR2DEST` / `shipInfo()` に分岐追加
4. **VAT/GST の徴収境界**を確認 (EU €150 / UK £135 / AU A$1,000)。境界で発送手段も税も変わる

## 6. eBaymag にサイトを追加したとき

1. **1国は1サイトにしか割当できない。追加 = 既存サイトから消える** (露出の移動であって拡大ではない)
2. 追加の価値は「その国がそのサイトを見ているか」で決まる。**ebay.de の流入は独語圏のみ**
   (独90% / 墺1.5% / 瑞1.2%、他は1%未満) → memory `ebaymag_mirror_country_assignment`
3. 新ミラーを作ったら V9スプシに `<国>計算` タブを作る。**`DE計算_new` を雛形に**
   (D=送料収入 / N=DDPコスト の構造。`US計算` 系と同じ形にすること)
4. ミラーの itemID はスプシに無い。**SKU で商品管理シートと突合**する

---

## 触るときの鉄則

- **E列は関税率ではない** (グループ識別子)。F列は split。備考は D列。**列を確認してから書く**
- **設定タブに行を足さない** — `offer_calc.py` が固定レンジ (`A11:F30` `A36:E44` 等) で読む。
  新しい表は**別タブ**に作る (`EU送料マスタ` がその例)
- **定数を入れたら必ず出典を書く** (PDF名 + 項目名)。`555` の出典特定に1時間かかった
- **書き戻す値は `UNFORMATTED_VALUE` で読む**。表示値だと `70` → `"$70.00"` になり、
  書き戻した瞬間にセルが文字列化して下流が全部 `#VALUE!` になる (2026-07-31 に174件発生)
- **本番タブを直接いじらない**。`_new` で作って before/after を出してから差し替える
- 価格に効く変更は **V4 事前検証 + 承認** (2026-05-15 に一括変更で1473件赤字事故)
