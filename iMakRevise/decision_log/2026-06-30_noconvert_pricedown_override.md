# 2026-06-30 NO_CONVERT 値下げ override 本実装

## 概要
ファネルの NO_CONVERT(クリック有・無販売)層を売れやすくするため、HQ が AL列「値下FLG」で
指定した HIGH/LOW 商品を週1リバイス時に **一律 5pp 値下げ** する。価格は本元
`pricing_engine.apply_pricedown_override` を import して算出(再実装なし・冪等・gateで赤字防止)。

## 経緯
- HQ feasibility 依頼 → リバイス回答(全項目feasible) → HQ 本実装依頼。
- 着手前に **title_override 不整合を発見**: `apply_pricedown_override` が内部で title無し
  dispatcher を呼び、バッグ→Porter 等の title_override 対象品(flag193中3件=Porter)が誤カテゴリ価格になる。
- HQ に相談 → HQ が **案A採用**: 関数に `title` 引数追加(commit 06d0060、内部 v6 経由)。
  → Porter 含む全193件が正しいカテゴリで値下げ可能に。

## 記録
- 決定: AL列(index37)=="値下5pp" ∧ D列≠○ の HIGH/LOW 行に
  `apply_pricedown_override(cost_jpy=N×pack, category=normalize(R), title=Title)` を適用、
  戻り値 `price` と `shipping_profile_name` を **セットで** 採用(バンド跨ぎ不整合防止)。
- 変更: [revise/price_revise.py](../revise/price_revise.py)
  - COL_PRICEDOWN_FLG=37 / PRICEDOWN_FLG_VALUE="値下5pp" 追加。
  - load_sheet_rows(high_low): 読込範囲 `A1:AH` → `A1:AL` (値下FLG を含める)。
  - detect_candidates: `schema` 引数追加。variation列(34-36)読込を official限定化
    (high_low の 34-36 は KEY/KEY2/巡回ERR で衝突するため)。pricedown_flag 読込追加。
  - ReviseCandidate: pricedown_flag / pricedown_applied フィールド追加。
  - compute_new_usd: `pricedown_fn` 引数追加。標準V8算出後、flag品のみ override の price+policy で
    差替(赤字行は先に skip、override失敗は標準据置の fail-safe)。
  - run_price_revise: pricedown_fn を import し V8ループで渡す。適用件数を log 出力。
- 変更: [tests/test_price_revise.py](../tests/test_price_revise.py)
  - TestPricedownOverride 7件(flag適用/無flag据置/冪等/赤字注入gate据置/売切skip/title_override Porter/
    price+policyセット) + TestDetectCandidatesPricedown 2件(AL読込/official無視)。
- 検証: 全80テスト pass。
- 検証(本番統合): 実HIGH/LOWシート × 実pricing_engine の dry-run で
  「NO_CONVERT 値下げ: flag 193 件 中 190 件に 5pp 適用 (残3=gate据置)」を確認(HQ件数と一致)。
- 検証(正確性): Porter(バッグ+PORTER title)が DDP-B群(Porter基準)で価格化、赤字0・異常0。

## 既知の未検証 (環境要因)
- full pipeline (snapshot取得→CSV出力) の end-to-end は当日 api.ebay.com の DNS 障害で fresh
  snapshot が取れず未走。CSV書込部 (write_revise_csv) は未変更で、検証済の new_usd/policy を
  そのまま出力するのみ。次回 GUI/週1サイクル実行で fresh snapshot 込みの実出力を確認予定。

## スコープ外
- 公式(UNIQLO UT/Montbell)系は対象外(official synthetic row は AL不在で自動的に非対象)。
