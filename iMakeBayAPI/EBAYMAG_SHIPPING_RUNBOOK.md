# eBaymag ミラーの送料を正しく表示させる Runbook（正本）

> 目的: eBaymag が各国ミラーに焼き込む送料を、意図どおり(UK/CA/AU=無料 / DE=SpeedPAK)に **実 listing レベルで** 正す手順。
> 確立: 2026-07-13（DE 412件一括修正で実証）。

---

## 0. 大原則（送料モデル）
- 送料は **商品価格に内包**。eBaymag の送料フィールド値 = 「国際エアポケット(=日本郵便エコノミー)基準との差分 + DDP」。
- **UK / CA / AU = DDP不要** → 送料 **無料(€0/£0/$0)**。基準のまま。国内(自国)発送、EU等は除外(~75地域)で自国のみに絞る。
- **DE = EU で DDP必要** → **SpeedPAK 課金**。
  - 国内(独): `DE_EconomySppedPAK` **€14.86**（SpeedPAK Economy = Cpass の**ドイツ国内専用**サービス）
  - 国際(墺のみ): `DE_IntlExpeditedSppedPAK` **€17.49**（Expedited。Economy は国際に出せないため）、宛先 **Österreich のみ**（他EUは US本体 rate table 担当、UKは UKミラー担当＝二重回避）

## 1. eBaymag UI で「元」を正す（DE の場合）
1. listing が乗ってるポリシーを **1本に集約**（乱立ポリシーの多くは空。実 listing が乗ってる少数だけ対象）。
2. そのポリシーを開き:
   - 「Kostenlosen Versand anbieten(無料提供)」の**チェックを外す**
   - 国内サービス = **eBay Sparversand mit SpeedPAK**（Economy）、料金 **14,86**（独語表記=カンマ。`14.86` はピリオド=千区切りで 1.486,00 になる罠）
   - 国際サービス = **eBay Schneller Versand mit SpeedPAK**（Expedited）、料金 **17,49**、宛先 **Österreich**
   - 「変更を適用」

## 2. ★但し eBaymag は反映が虫食い → API で検証＆一括修正（本命）
eBaymag は送料を **listing ごとに inline 焼き込み** し、ポリシー変更を全 listing に push しない。
→ UI 表示は「DDP-A-P16 に乗ってる」でも、**実 listing は無料€0 のまま**が多発（表示≠実体）。

### 検証（実体を暴く）
- `GetItem`（読取は legacy AuthToken でOK）で実 listing の `ShippingServiceOptions` を見る。

> ★2026-07-31 改訂: **「€0 = leak / €14.86 = 正」は誤り**。正否は **価格帯**で変わる。
>
> ```
> 送料 = (その手段の実費 − 国際エアパケット実費) + 当方負担の関税
> ```
>
> | 帯 | サービス | 送料 |
> |---|---|---|
> | **≤€150** | `DE_EconomySppedPAK` / `DE_IntlEconomySppedPAK` | **有料**。実送料¥2,000 のカテゴリなら 国内 €6.6 / 国際 €11.6 (レートで変動) |
> | **>€150** | `DE_SparversandAusDemAusland` / `DE_SonstigeInternational` | **€0** (国際エアパケット。関税は買い手着払い) |
>
> 経緯: 同一SKU 5ミラー実測 (PSA10 Pikachu / SKU m76107330544) で
> UK £188.35+£0 / CA C$355.36+C$0 / AU A$363.69+A$0 が本体だけで ¥40.5千に揃うのに対し、
> DE だけ €220.62+€14.86 で **¥2,700 高い**と判明。ただし「全部 €0」も誤りで、
> **≤€150 は SpeedPAK で送り DDPコスト(関税込)を当方が負担する**ため、その差額は徴収する。
> 全帯 €0 にすると ≤€150 が全額持ち出しになる。
>
> **帯 (と ≤€150 ではカテゴリ別実送料) を見ないと正否は判定できない。**
> 判定と修正は `de_mirror_fedex_removal.py` (帯・カテゴリを持つ) で行うこと。

### 一括特定
- `GetMyeBaySelling`（ActiveList, 全ページ）で active 全件走査。各 Item は **`CurrentPrice currencyID`（通貨=マーケット判定）** と **`ShippingServiceCost`（送料）** を inline で返す。
- **`currency==EUR` かつ `ShippingServiceCost==0.0`** = 無料 DE ミラー = 要修正。

### 一括修正
- `ReviseFixedPriceItem`（SITEID=77）で SpeedPAK を inline 焼き込み:
  ```
  <ShippingDetails><ShippingType>Flat</ShippingType>
    <ShippingServiceOptions><ShippingService>DE_EconomySppedPAK</ShippingService>
      <ShippingServiceCost currencyID="EUR">14.86</ShippingServiceCost><ShippingServicePriority>1</ShippingServicePriority></ShippingServiceOptions>
    <InternationalShippingServiceOption><ShippingService>DE_IntlExpeditedSppedPAK</ShippingService>
      <ShippingServiceCost currencyID="EUR">17.49</ShippingServiceCost><ShippingServicePriority>1</ShippingServicePriority>
      <ShipToLocation>AT</ShipToLocation></InternationalShippingServiceOption></ShippingDetails>
  ```
  - Ack=Warning（「Rahmenbedingungen 有効…ポリシー化した」）で成功。eBay がアカウントのポリシー設定で自動ポリシー化して適用する。
- **スクリプト: `fix_de_speedpak_shipping.py`**（`--count`=無料DEを数えるだけ / 無引数=無料DEを一括SpeedPAK化。token自動refresh込）。

### 検証（churn チェック）
- 再走査して **EUR無料=0件** を確認。eBaymag が後の同期で無料に戻す(churn)可能性 → 定期再実行で塞ぐ。

## トークン運用（重要）
- **読取(GetItem)**: legacy `AuthToken`（`ebay keys.txt`、`<RequesterCredentials><eBayAuthToken>`）。長期有効。
- **書込(Revise)/列挙(GetMyeBaySelling)**: **`ebay_oauth_token_sell.json` の access_token を `X-EBAY-API-IAF-TOKEN` に使う**（base api_scope superset だから Trading も通る）。legacy AuthToken は revise 権限NG。
- sell token は ~2h で失効 → `python oauth_sell_setup.py refresh`。
- `ebay_oauth_token.json`（Trading/監視くん用）は**触らない**設計（監視くんを壊さない）。
- `import dns_cache` 必須（`cd iMakeBayAPI` して）。DNS間欠対策。

## 現状（2026-07-13）
UK/CA/AU=無料 ✅ / DE=SpeedPAK €14.86・€17.49（520件全て）✅。DE の churn 戻りは未発生。
