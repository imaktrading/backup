# CPSC 電子申告義務化 対応 — 状態メモ (2026-06-16)

期限: 2026-07-08。すぐ完了する話でないので保留中。続きはこの workstream 専用チャットで。

## 確定している対応方法
- 衣類(UNIQLO/Montbell/GU): GCC を1枚自作して付ける(※免除品でも要るかは確認中)
- 玩具(一番くじ/ガシャポン/S.H.Figuarts/プライズ/Tomica): 「Adult Collectible / 15歳以上」年齢表記のみ。試験不要
- PSA10 TCG: コレクター品扱い、年齢表記のみ。不要
- G-shock / Porter: 規制対象外、対応不要
- ★新発見 ぬいぐるみ(plush, active 79件): 児童製品判定の恐れ → 要チェック(最悪出品停止)
- ★新発見 GU/その他衣類76件: UNIQLO/Montbell と同じ Part1610 → GCC 範囲に含める
- ★未分類513件: 中身未検査 → triage 要

## 進め方(誰が)
- 既存出品: 私が一括改訂CSV(Age/Title)生成 → Takaaki さんが eBay アップロード
- 新規出品: 私が listing script に default 実装(玩具=Age自動 / 衣類=Material・Weight必須化)
- GCC: 私がPDFテンプレ+データ自動埋込。素材/重量無い品は fail-closed
- triage: 私が plush/未分類を分類・4要素一次判定 → Takaaki さん判定

## 確認待ち(これが出ると衣類とeFilingが確定)
- deep-research 実行中(このセッションに結果が返る): 
  ①免除衣類に GCC 自体が要るか ②eFiling を出すのは出品者か通関業者か
  ③de minimis 2025/2026 の状況 ④4要素で15+表示が決定打か(Pokemon系) ⑤GCC発行主体

## 次の一手(research 完了後)
- ①不要なら衣類も対応無し / 要なら GCCテンプレ実装
- ②出品者でないなら eFiling 実装不要(GCC保管のみ)
- STEP1(玩具/PSA10 の Age/Title)と STEP4(triage)は research 非依存で先行可
