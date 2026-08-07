# 補URL POC 設計（HQ側・実装前ドキュメント）

- 起案: 2026-07-13 / HQ
- 前提: 重複くん filter是正 完了(commit da505e1、existing set=live のみ・`live_guaranteed=True`・sign-off PASS)
- フェーズ: **POC 設計（dry-run で数件、実書込しない）**。本実装は POC 目視 OK 後。

---

## 目的
重複くんが「既出品と同KEYで弾いた別個体」= backup 供給源。その **仕入URL(A列)** を、
同KEYの **出品中 primary 行の 補URL(AC〜AG)** に貯める → primary が売れたら補URLから再ソースして履行。

## データの場所（HIGHT 商品管理シート）
| 列 | 中身 | 確度 |
|---|---|---|
| **A** | 仕入URL（= 補URLに貯める元） | ユーザー確定 |
| **B** | itemID（出品済なら非空 = live primary の印） | dedupe と一致(LISTINGS_COL_ITEMID=2) |
| **D** | sold（売却で非空） | dedupe と一致 |
| **AC〜AG** | 補URL（5枠） | ユーザー確定 |
| cert列 / KEY列 | 除外行↔HIGHT行 の突合キー | **⚠️実装時に実列を確認**（psa_to_csv の読取 or write-keys の書込先） |

## フロー
1. 出品くんが `dedupe.checker --check-csv` 実行 → **除外行**が出る（`live_guaranteed=True`、除外KEY = 必ず live primary を持つ）。
2. **除外行の特定**: `.bak`(除外前) vs `.csv`(除外後) の差分 CustomLabel(=cert) = 除外された別個体。
3. 各 除外cert について HIGHT で:
   - a. **除外行の A列(仕入URL)** を取得（cert → HIGHT行）
   - b. **primary 行** = 同KEー AND B非空 AND D空（live）→ その行を特定
   - c. primary の **AC〜AG の左空き枠** に 除外行のA列URL を書く（**冪等**: 既に同URLあればskip）
4. **dry-run(POC)**: 実書込せず「行X primary(itemID=…) の AG に URL=… を追記予定」をログ + review_logs に出力 → 目視。

## 安全ガード（fail-closed）
- **`live_guaranteed=True` の除外のみ対象**（orphan は重複くんが既に除外済だが二重確認）。
- **primary が複数 live（同KEー>1、回答の LOW 3群ケース）→ POC は skip + 警告**（曖昧回避。本実装で方針決め）。
- **AC〜AG 5枠 満杯 → skip + 通知**（溢れ捨てを黙らせない）。
- **除外KEー↔primary の突合は KEー基準**（A列で突合しない=重複くんの判定基準に一致）。
- 誤URL 1件入れる方が取りこぼしより危険 → 少しでも曖昧なら書かない。

## restock 実行時の2段目ゲート（本実装で）
補URLから再ソースする時、**そのURLのカードが primary の KEー と一致するか再verify** してから出品（貯める時=exact KEー / 使う時=再確認 の dual gate）。

## 実装場所
`control_panel.py` の dedupe フック直後に「補URL plumbing」ステップを追加（HQ worktree=ここで可）。スプシ接続は既存 gspread 経路を流用。

## POC で確認する事
1. 除外行 → A列URL・KEー・primary行 の突合が実データで正しく取れるか（cert列/KEー列の実列確認込み）。
2. dry-run 出力が「正しい primary の AC〜AG に、正しい別個体URL」を指してるか目視。
3. 複数live・満杯・冪等 の各ガードが効くか。

## 未確定（POC前に詰める）
- HIGHT の **cert列 と KEー列 の実位置**（実装時に psa_to_csv / write-keys から確認）。
- gspread 接続情報（既存 listing スクリプトの認証を流用）。
