# Phase 1 ロジック全面刷新 (コストプラス簡易版) — 2026-05-03

## 決定: ratio 方式廃止 → コストプラス簡易版

### 変更前 (ratio 方式)
```
新 USD = 現 USD (Browse API) × (新 N / 旧 F)
```
- Browse API 依存
- 過去 revise の累積誤差を引きずる
- 検知: F vs N の |delta| >= 3% (両方向)

### 変更後 (コストプラス簡易版)
```
[検知]
  D=○ → 対象外
  D=空 + AH 値あり → rate = (N - AH) / AH    [短期 trend]
  D=空 + AH 空欄    → rate = (N - F) / F     [大局フォールバック]
  rate >= 0.03 で起動 (値上げのみ、トラバホ準拠)

[計算]
  新 USD = round_98((N + SHIPPING[category]) / (rate × 0.59) × 1.10)
  
  SHIPPING:    Book1.xlsx 準拠 17 カテゴリ (¥2000/¥2500/¥3500)
  net_ratio:   0.59 (= 1 - 0.185 - 0.10 - 0.025 - 0.10)
  rate:        frankfurter API (1h cache, ¥155 fallback)
  バッファ:    × 1.10 (オファー -10% 譲歩想定)

[fail-closed 二重ガード]
  - category 未登録 → skip
  - N が ¥100 未満 / ¥500,000 超 → skip
  - AH も同じ range check
  - F+AH 両空欄 + N 値あり → init として F=N (CSV 出さない)

[完了処理]
  - revise CSV 生成 → csv_output/
  - スプシ M クリア + F ← N
```

## 各決定の根拠

### 1. ratio → コストプラス
- **Why**: 仕入価格変動だけでなく価格設定ロジック変更時の全アイテム revise も役割。ratio は "出品時の値付けを継承" するため新ロジック適用に向かない
- **検証**: pytest 53 件 pass
- **変更**: `revise/price_revise.py:compute_new_usd` 全面書き換え

### 2. 検知軸: AH vs N (主) / F vs N (フォールバック)
- **Why**: 監視くんが N 更新時に AH を copy。AH = "前期買えた値段" で純粋 trend が拾える。F vs N は補切替の累積を含むためノイズ多い
- **検証**: `should_revise()` 11 ケース pytest pass

### 3. 値上げのみ (片側)
- **Why**: トラバホ準拠 + 値下げで利益自爆を防止 (仕入下落時に eBay USD 下げる必要なし)
- **変更**: `should_revise` で `rate >= threshold` (絶対値ではなく)

### 4. 為替動的 (frankfurter API)
- **Why**: 為替変動だけでは revise 起動しないので、起動時に最新為替で計算する方が正しい。固定 ¥155 だと円高 (¥150) で利益率 8% に下振れ
- **変更**: `revise/usd_jpy_rate.py` 新規 (1h cache, 24h stale, env override, ¥155 fallback)

### 5. 送料 dict (Book1.xlsx 準拠)
- **Why**: ユーザー提供 Excel に確定送料表。¥2000/¥2500/¥3500 の 3 種類のみ
- **変更**: `revise/shipping_dict.py` 新規

### 6. オファーバッファ ×1.10
- **Why**: eBay Best Offer で -10% 譲歩しても元の利益率を維持
- **検証**: 仕入¥1000、Tシャツ → $36.98 (×1.10 込)、-10% 受諾後 $33.28 = 利益率 ~22% (= ×1.10 なし時相当)

## 計算例 (為替¥155、Tシャツ送料¥2000)

| 仕入¥ | 出品$ | 直販利益率 (LX) | -10% オファー後利益率 |
|---|---|---|---|
| 1,000 | $36.98 | 31% | 12% |
| 3,000 | $60.98 | 22% | 12% |
| 5,000 | $84.98 | 18% | 11% |
| 10,000 | $144.98 | 14% | 8% |
| 30,000 | $384.98 | 11% | 5% |

## カテゴリ別計算例 (仕入¥3000、為替¥155)

| カテゴリ | 送料¥ | 出品$ |
|---|---|---|
| TCG/Tシャツ/Montbell一般 | 2000 | $60.98 |
| G-SHOCK/POPMart/サンリオぬいぐるみ等 | 2500 | $66.98 |
| フィギュア/一番くじ/Porter/リール/バッグ(アネロ) | 3500 | $78.98 |

## 動作確認

| 項目 | 結果 |
|---|---|
| pytest | **53 件 pass** (round_98 / to_float / is_sold / is_valid_jpy / should_revise / detect_candidates / detect_init_targets / compute_new_usd / write_csv / shipping_dict / control_panel parse + extract) |
| frankfurter API | OK (¥156.76 取得) |
| 実 Sheet 925 行読込 | OK |
| 検知ロジック | F 初期化対象 158 件、revise 候補 0 件 (= 期待通り、初回 cycle 待ち) |

## 廃止

- `revise/ebay_browse_price.py` (Browse API loader) — 削除済
- `pricing_engine.compute_listing_price` import — 削除
- `pricing_engine._round_98` import — 自前 `round_98()` に置換 (修正連鎖さらに削減)

## 修正連鎖回避ステータス

| 連携先 | 修正の有無 |
|---|---|
| 監視くん (iMak_inventory) | なし (A/B/D/G 既実装の AH/multi-sourcing/D 列/初回 AH 空欄 を利用) |
| 出品くん (pricing_engine, profit_params) | **依存ゼロ化** (import 廃止) |
| iMakeBayAPI/check_csv_core.py | なし |
| Browse API | 廃止 |

## 残タスク

- [ ] cron 登録 (`tools/register_task.ps1 -Action Register` ユーザー実行)
- [ ] 初回 cron 走行で 158 件 F=N 初期化
- [ ] AH 列が監視くん側で更新され始めたら次 cycle から N vs AH 検知が動く
