# mercari_scraper 在庫判定: HTML 実物比較レポート

**作成**: 2026-04-29 (Phase 2)
**目的**: 憶測ロジックでなく、HTML 実物比較で 100% 正解できる判定軸を導く
**検体**: in_stock 11件 + sold 10件 = 21件 (全件 hydration 完了で取得)

---

## A. 実検証結果: 提示された User 仕様セレクタは大半が **存在しない**

| User 仕様セレクタ | in_stock 11件 | sold 10件 | 採否 |
|---|---|---|---|
| `.mypage-item-not-found` | 0 | **0** | ✗ HTML に存在せず |
| `.mypage-sold` | 0 | **0** | ✗ HTML に存在せず |
| `[data-testid='product-detail']` | 0 | 0 | ✗ HTML に存在せず |
| `mer-price` | 0 | 0 | ✗ HTML に存在せず |
| `[data-testid*='purchase-button']` (Shops) | 0 | 0 | n/a (検体は全 `/item/m...`、Shops 不在) |

→ **User 仕様の selector はほぼヒットしない**。代替を実 HTML から導出する必要あり。

## B. 実 HTML 実装で **全件一致する** 判定軸

| シグナル | in_stock 11件 | sold 10件 | 弁別力 |
|---|---|---|---|
| `data-testid="checkout-button-container"` (hydration proxy) | **11/11** | **10/10** | ✓ 100% (universal hydration check) |
| `data-testid="checkout-button"` (button inside container) | 11/11 | **9/10** | △ 1件 absent |
| `data-testid="checkout-button"` div の `name="purchase"` | **11/11** | 0/10 | ✓ IN_STOCK 確定 |
| `data-testid="checkout-button"` div の `name="disabled"` | 0/11 | 9/10 | ✓ SOLD 確定 |
| div class に `disabled__` 文字列 | 0/11 | 9/10 | ✓ SOLD 確定 |
| `data-testid="view-transaction-button"` (取引中 派生) | 0/11 | 1/10 | ✓ SOLD 派生形 |
| body text に "売り切れ" 出現 | 11/11 | 10/10 | ✗ i18n bundle に存在、弁別力ゼロ |

## C. 実 HTML パターン詳細

### IN_STOCK 標準パターン (11/11)

```html
<div data-testid="checkout-button-container">
  <div class="merButton primary__01a6ef84 medium__01a6ef84 fluid__01a6ef84 sc-d306941c-2 hTiixm"
       data-location="item_details:footer:pay_button:buy"
       data-testid="checkout-button"
       name="purchase">
    <button type="button">購入手続きへ</button>
  </div>
</div>
```

### SOLD 標準パターン (9/10) — checkout-button が disabled として残る

```html
<div data-testid="checkout-button-container">
  <div class="merButton primary__01a6ef84 medium__01a6ef84 fluid__01a6ef84 disabled__01a6ef84"
       data-testid="checkout-button"
       name="disabled">
    <button type="button" disabled="">売り切れました</button>
  </div>
</div>
```

### SOLD 派生 (1/10) — 取引中 / view-transaction-button

サンプル: `m63571237049` (Takaaki さんが売主かつ取引進行中)

```html
<div data-testid="checkout-button-container">
  <div class="merButton secondary__01a6ef84 medium__01a6ef84 fluid__01a6ef84"
       data-testid="view-transaction-button">
    <a href="/transaction/m63571237049">取引画面を表示する</a>
  </div>
</div>
```

このケースでは `data-testid="checkout-button"` が存在しない (代わりに `view-transaction-button`)。
取引中 = 別バイヤーに売却済 = SOLD 扱い。

## 判定ロジック (確定版)

```
1) [data-testid="checkout-button-container"] が描画されるまで待機 (max 30s)
   timeout → real_err (誤取下げ防止)

2) container 内の checkout-button div を探す:

   a) [data-testid="checkout-button"] が存在しない
      → SOLD (取引中 / view-transaction-button 派生など)

   b) [data-testid="checkout-button"] 存在 + class に "disabled__" を含む
      → SOLD

   c) [data-testid="checkout-button"] 存在 + name="disabled"
      → SOLD

   d) [data-testid="checkout-button"] 存在 + name="purchase"
      → IN_STOCK

   e) 上記いずれにも該当しない (新パターン)
      → real_err (安全側、人間目視確認に回す)
```

## 検証スクリプトでの結果

`debug/verify_detection_logic.py` で 21/21 全件正解。

| label | item_id | verdict | reason |
|---|---|---|---|
| in_stock | m13033508222 | IN_STOCK | name="purchase" |
| in_stock | m49383173561 | IN_STOCK | name="purchase" |
| ... | ... | ... | (全 11 件 同じ) |
| sold | m96600846115 | SOLD | disabled__ class |
| sold | m63571237049 | SOLD | checkout-button absent (transaction) |
| sold | m63905828803 | SOLD | disabled__ class |
| ... | ... | ... | (残り disabled__ class) |

## ハイドレーション対策

`checkout-button-container` 自体は描画完了の最良 proxy:
- 21/21 全件で出現 (確実な universal selector)
- container 出現後は内側の状態判定で 100% 正解

`product-detail` / `mer-price` 待ちにすると **永久 timeout** (DOM に存在しない)。

## Mercari Shops (`/shops/product/`)

検体に Shops URL なし。既知の testid `variant-purchase-button` (過去 probe で確認済) を継続使用。
本レポートは `/item/m...` 通常 Mercari に限定した分析。

## 推奨実装

`scrapers/mercari_scraper.py:_is_sold_button` を以下に置換:

1. `WebDriverWait(30s)` で `[data-testid="checkout-button-container"]` を待つ
2. container 内に `[data-testid="checkout-button"]` 検索
3. 上記判定フローを順次適用 → IN_STOCK / SOLD / real_err
