"""DON カード set 投入 (= ONE PIECE TCG special、 公式 PDF source).

依頼: 2026-05-27_don_card_set_investment.md (HQ Phase 2 承認、 案 B 採用)

KEY 体系 (= 案 B 英訳 + 連番):
  product_id = 'DON-{set_code}-{NNN}'
  例: 'DON-OP15-001', 'DON-PRB01-042', 'DON-STORAGE-RED'

source 分布 (= PDF 30 pages × 9 cards 観察結果):
- Page 1:    BASIC + EVENT + STDBP + STORAGE 6 colors                = 9 cards (mixed)
- Page 2:    STORAGE 続き (色違い) + ST10/13 + EVENT + OP01/02       = 9 cards (mixed)
- Page 3:    OP03/04/05/06/07/08 + OFCASE + CHAMP23 + EVENT          = 9 cards (mixed)
- Page 4:    GRAND-ASIA + EVENT x2 + その他 + PRB01 x3                = 9 cards (mixed)
- Page 5-13: PRB01 集中 (= 9 × 9 = 81 cards)
- Page 14:   PRB01 5 + OP-DAY-24 promo x3 + OP09                     = 9 cards (mixed)
- Page 15:   OP10 + EB02 + OP11 + OP12 + PROMO-PACK-V1 等             = 9 cards (mixed)
- Page 16:   PROMO-PACK-V1 4 + PRB02 5                                = 9 cards (mixed)
- Page 17-25:PRB02 集中 (= 9 × 9 = 81 cards)
- Page 26:   PRB02 5 + OP-DAY-25 promo + OP13 x2 + EB03               = 9 cards (mixed)
- Page 27:   EB03 Heroines (8 cards) + HEROINES-SPECIAL 1             = 9 cards
- Page 28:   OP14 x2 + EN-2ND + CN-2ND + EB04 x2 + 3RD + KUMAMON x2   = 9 cards (mixed)
- Page 29:   KUMAMON (Zoro/Usopp/Chopper/Robin/Jimbei/Brook/Nami/Franky) + OP15 = 9 cards (mixed)
- Page 30:   OP15 + OP16 x2 + EVENT                                   = 4 cards (final)
TOTAL: 29 × 9 + 4 = 265 cards
"""
import sqlite3
import sys
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat()
SOURCE_PDF = "C:/dev/iMak_data/catalog/don-cardlist.pdf"
NOTE_BASE = "DON Card; 公式 card_number 不在のため Catalog 内部 ID; source=don-cardlist.pdf 2026-05-27"

# (set_code, source_label_ja, source_label_en) = SOURCE 一覧
# 各 set_code 内で 連番 001-NNN を付与
# page_position_to_set 表 = PDF observation
# 表記: [(page, position_1_to_9, set_code, variant_note_jp)]
# page_30 は 4 cards only (positions 1-4)

# === 完全 page-position マッピング (= PDF Vision OCR 結果) ===
PAGE_POSITION_MAP = [
    # (page, pos, set_code, note_ja)
    # ===== Page 1: 通常 + event + 戦闘パック + ストレージ 6 色 =====
    (1, 1, "BASIC", "通常デザイン"),
    (1, 2, "EVENT", "イベント配布 (= 黄色)"),
    (1, 3, "STDBP", "スタンダードバトルパック Vol.1 (= 赤黒)"),
    (1, 4, "STORAGE", "ストレージボックス×ドンカードセット (= 赤)"),
    (1, 5, "STORAGE", "ストレージボックス×ドンカードセット (= 緑)"),
    (1, 6, "STORAGE", "ストレージボックス×ドンカードセット (= 橙)"),
    (1, 7, "STORAGE", "ストレージボックス×ドンカードセット (= 黄)"),
    (1, 8, "STORAGE", "ストレージボックス×ドンカードセット (= 青)"),
    (1, 9, "STORAGE", "ストレージボックス×ドンカードセット (= 紫 X)"),

    # ===== Page 2: ストレージ続き + ST10/13 + event + OP01/02 =====
    (2, 1, "STORAGE", "ストレージボックス×ドンカードセット (= 紫 variant 2)"),
    (2, 2, "STORAGE", "ストレージボックス×ドンカードセット (= teal)"),
    (2, 3, "STORAGE", "ストレージボックス×ドンカードセット (= 黒)"),
    (2, 4, "STORAGE", "ストレージボックス×ドンカードセット (= 金月)"),
    (2, 5, "EVENT", "イベント配布"),
    (2, 6, "ST10-13", "アルティメットデッキ 三海皇編 [ST-10] / 3兄弟 [ST-13]"),
    (2, 7, "EVENT", "イベント配布"),
    (2, 8, "OP01", "ブースターパック ROMANCE DAWN [OP-01]"),
    (2, 9, "OP02", "ブースターパック 頂上決戦 [OP-02]"),

    # ===== Page 3: OP03-08 + その他 =====
    (3, 1, "OP03", "ブースターパック 強大な敵 [OP-03]"),
    (3, 2, "OP04", "ブースターパック 謀略の王国 [OP-04]"),
    (3, 3, "OP05", "ブースターパック 新時代の主役 [OP-05]"),
    (3, 4, "OP06", "ブースターパック 双璧の覇者 [OP-06]"),
    (3, 5, "OP07", "ブースターパック 500年後の未来 [OP-07]"),
    (3, 6, "OP08", "ブースターパック 二つの伝説 [OP-08]"),
    (3, 7, "OFCASE", "オフィシャルカードケース リミテッドエディション付属"),
    (3, 8, "CHAMP23", "チャンピオンシップ2023 ワールドファイナル参加記念品"),
    (3, 9, "EVENT", "イベント配布"),

    # ===== Page 4: Grand Asia Open + event + PRB01 開始 =====
    (4, 1, "GRAND-ASIA", "Grand Asia Open"),
    (4, 2, "EVENT", "イベント配布"),
    (4, 3, "EVENT", "イベント配布"),
    (4, 4, "EVENT", "イベント配布"),
    (4, 5, "EVENT", "イベント配布"),
    (4, 6, "EVENT", "イベント配布"),
    (4, 7, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (4, 8, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (4, 9, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),

    # ===== Page 5-13: PRB01 集中 (各ページ 9 cards = 81 cards) =====
    *[(p, pos, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]")
      for p in range(5, 14) for pos in range(1, 10)],

    # ===== Page 14: PRB01 5 + OP-DAY-24 + OP09 =====
    (14, 1, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (14, 2, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (14, 3, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (14, 4, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (14, 5, "PRB01", "プレミアムブースター ONE PIECE CARD THE BEST [PRB-01]"),
    (14, 6, "OP-DAY-24", "ONE PIECE DAY '24 SPECIAL LIVE Day1"),
    (14, 7, "OP-DAY-24", "ONE PIECE DAY '24 SPECIAL LIVE Day2"),
    (14, 8, "OP-DAY-24", "プレミアムドンコレクション -ONE PIECE DAY'24-"),
    (14, 9, "OP09", "ブースターパック 新たなる皇帝 [OP-09]"),

    # ===== Page 15: OP10/EB02/OP11/OP12/promo pack =====
    (15, 1, "OP10", "ブースターパック 王者の咆哮 [OP-10]"),
    (15, 2, "EB02", "エクストラブースター Anime 25th collection [EB-02]"),
    (15, 3, "OP11", "ブースターパック 神龍の咆哮 [OP-11]"),
    (15, 4, "OP10", "ブースターパック 王者の咆哮 [OP-10] variant"),
    (15, 5, "EB02", "エクストラブースター Anime 25th collection [EB-02] variant"),
    (15, 6, "OP12", "ブースターパック 謀略の卵 [OP-12]"),
    (15, 7, "EVENT", "イベント配布"),
    (15, 8, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),
    (15, 9, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),

    # ===== Page 16: promo vol.1 4 + PRB02 5 =====
    (16, 1, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),
    (16, 2, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),
    (16, 3, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),
    (16, 4, "PROMO-V1", "プロモーション×ドンカードパック vol.1"),
    (16, 5, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (16, 6, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (16, 7, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (16, 8, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (16, 9, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),

    # ===== Page 17-25: PRB02 集中 (= 9 × 9 = 81 cards) =====
    *[(p, pos, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]")
      for p in range(17, 26) for pos in range(1, 10)],

    # ===== Page 26: PRB02 5 + OP-DAY-25 + OP13 + EB03 =====
    (26, 1, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (26, 2, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (26, 3, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (26, 4, "PRB02", "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"),
    (26, 5, "OP-DAY-25", "ONE PIECE DAY '25 promo"),
    (26, 6, "OP-DAY-25", "プレミアムドンコレクション -ONE PIECE DAY '25-"),
    (26, 7, "OP13", "ブースターパック 受け継がれる意志 [OP-13]"),
    (26, 8, "OP13", "ブースターパック 受け継がれる意志 [OP-13]"),
    (26, 9, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),

    # ===== Page 27: EB03 Heroines + HEROINES-SPECIAL =====
    (27, 1, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 2, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 3, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 4, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 5, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 6, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 7, "EB03", "エクストラブースター ONE PIECE Heroines Edition [EB-03]"),
    (27, 8, "HEROINES-SP", "ONE PIECE Heroines Special Set"),
    (27, 9, "HEROINES-SP", "ONE PIECE Heroines Special Set"),

    # ===== Page 28: OP14 + EN-2ND + CN-2ND + EB04 + 3RD + KUMAMON =====
    (28, 1, "OP14", "ブースターパック 最強の七皇 [OP-14]"),
    (28, 2, "OP14", "ブースターパック 最強の七皇 [OP-14]"),
    (28, 3, "EN-ANNIV2", "ONE PIECE カードゲーム English 2nd ANNIVERSARY SET"),
    (28, 4, "CN-ANNIV2", "ONE PIECE カードゲーム China 2nd ANNIVERSARY SET"),
    (28, 5, "EB04", "エクストラブースター EGGHEAD CRISIS [EB-04]"),
    (28, 6, "EB04", "エクストラブースター EGGHEAD CRISIS [EB-04]"),
    (28, 7, "ANNIV-3", "ONE PIECE カードゲーム 3rd ANNIVERSARY SET"),
    (28, 8, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (KUMAMON & LUFFY)"),
    (28, 9, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (SANJI)"),

    # ===== Page 29: KUMAMON Strawhats x8 + OP15 =====
    (29, 1, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (RORONOA ZORO)"),
    (29, 2, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (USOPP)"),
    (29, 3, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (TONY TONY CHOPPER)"),
    (29, 4, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (NICO ROBIN)"),
    (29, 5, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (JINBEI)"),
    (29, 6, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (BROOK)"),
    (29, 7, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (NAMI)"),
    (29, 8, "KUMAMON", "プレミアムカードコレクション -熊本復興スペシャル- (FRANKY)"),
    (29, 9, "OP15", "ブースターパック 神の島の冒険 [OP-15]"),

    # ===== Page 30: OP15 + OP16 + EVENT (= 4 cards のみ) =====
    (30, 1, "OP15", "ブースターパック 神の島の冒険 [OP-15] variant"),
    (30, 2, "OP16", "ブースターパック 決断の刻 [OP-16]"),
    (30, 3, "OP16", "ブースターパック 決断の刻 [OP-16]"),
    (30, 4, "EVENT", "イベント配布"),
]


def main():
    # 1) set_code 内 連番付与
    set_counters: dict[str, int] = {}
    entries: list[dict] = []
    for page, pos, set_code, note in PAGE_POSITION_MAP:
        set_counters[set_code] = set_counters.get(set_code, 0) + 1
        n = set_counters[set_code]
        product_id = f"DON-{set_code}-{n:03d}"
        entries.append({
            "product_id": product_id,
            "page": page,
            "pos": pos,
            "set_code": set_code,
            "note": note,
            "global_seq": len(entries) + 1,
        })

    print(f"=== Total entries: {len(entries)} ===")
    print(f"=== set_code distribution ===")
    for sc, n in sorted(set_counters.items(), key=lambda x: -x[1]):
        print(f"  {sc:15s}: {n} cards")
    print()

    # 2) DB 投入
    inserted = 0
    updated = 0
    skipped = 0
    for e in entries:
        pid = e["product_id"]
        name = "DON!! Card"
        specs = {
            "card_type": "DON!! Card",
            "effect": "自分のターン +1000",
            "page_in_pdf": e["page"],
            "position_in_page": e["pos"],
            "set_code": e["set_code"],
            "source_note": e["note"],
            "global_seq": e["global_seq"],
        }
        # 既存確認
        existing = api.lookup("one_piece_tcg", pid)
        try:
            api.upsert(
                category="one_piece_tcg",
                product_id=pid,
                name=name,
                name_jp="ドン!! カード",
                set_name="DON!! Card",
                set_name_official=e["note"],
                specs=specs,
                images=[],
                source="bandai_official_pdf_doncardlist_2026-05-21",
                source_url=SOURCE_PDF,
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        except Exception as ex:
            print(f"  ⚠️ {pid}: {ex}")
            skipped += 1

    print(f"\n=== DB 投入集計 ===")
    print(f"  INSERT: {inserted}")
    print(f"  UPDATE: {updated}")
    print(f"  SKIP:   {skipped}")


if __name__ == "__main__":
    main()
