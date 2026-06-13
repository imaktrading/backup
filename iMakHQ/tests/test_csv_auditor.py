#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV監査くん (csv_auditor.py) 純関数の回帰テスト。

固定する不変条件 (ユーザー合意・出品の正確性):
  - 「修正」3分岐の分類が崩れない (送料=機械修正 / データ誤り=除外+カタログ依頼 /
     生成バグ=除外+プログラム依頼 / SEO=報告のみ)。値の捏造は決して MECH_FIX にしない。
  - 誤出品直結 (title>80/PSA10/禁止語/日本語/カテゴリ/cert/価格非数値/set誤マップ) は必ず除外。
  - 行集約は重い処置 (除外) を優先。
check_csv の validate_row 文言に依存するので、文言変更が起きたらここが落ちる (回帰検知)。
"""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load("csv_auditor")


def test_classify_mech_fix_shipping():
    assert A.classify_finding("WARN", "送料ポリシー '40-60' が価格$55に対して不一致（期待: 60-100）") == A.MECH_FIX


def test_classify_data_error_set_mismap():
    msg = "Set世代↔Year 不整合: Set='X'(世代 SM:2017-2019) なのに Year=2026 → set_name_ebay 誤マップ疑い"
    assert A.classify_finding("ERROR", msg) == A.EXCLUDE_CATALOG


def test_classify_required_spec_empty():
    assert A.classify_finding("WARN", "必須Item Specific 'C:Rarity' が空") == A.SPEC_EMPTY


def test_classify_failclosed():
    assert A.classify_finding("ERROR", "PSA鑑定番号が不正: abc") == A.EXCLUDE_FAILCLOSED
    assert A.classify_finding("ERROR", "価格が数値でない: ") == A.EXCLUDE_FAILCLOSED


def test_classify_program_bugs():
    assert A.classify_finding("ERROR", "タイトル92字 > 上限80字") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "タイトルが 'PSA 10' で始まっていない") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "禁止ワード 'mint' がタイトルに含まれている") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "カテゴリが 183454 でない: 999") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "ConditionID が 2750 でない: 1000") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "タイトルに日本語文字が混入: 'リソース'") == A.REPORT_PROGRAM


def test_classify_seo_and_info():
    assert A.classify_finding("WARN", "タイトル60字 < 推奨70字（キーワード不足の可能性）") == A.SEO_NOTE
    assert A.classify_finding("WARN", "タイトル内で 'pikachu' が重複") == A.SEO_NOTE
    # 推奨spec空は SEO 改善メモ扱い (プラン table どおり、行は残す)
    assert A.classify_finding("INFO", "推奨Item Specifics が空: Card Type, Features") == A.SEO_NOTE
    # SEO語を含まない素の INFO は INFO_ONLY
    assert A.classify_finding("INFO", "参考情報") == A.INFO_ONLY


def test_seo_never_becomes_mech_fix():
    # 値の捏造禁止: SEO/データ系が機械修正に分類されない (送料以外は CSV を書き換えない)
    for sev, msg in [
        ("WARN", "必須Item Specific 'C:Set' が空"),
        ("WARN", "タイトル60字 < 推奨70字（キーワード不足の可能性）"),
        ("ERROR", "Set↔total 不整合"),
    ]:
        assert A.classify_finding(sev, msg) != A.MECH_FIX


def test_row_disposition_priority_and_exclude():
    # 除外は機械修正より優先 / 1つでも除外系があれば行除外
    disps = [A.MECH_FIX, A.SEO_NOTE, A.EXCLUDE_CATALOG]
    assert A.row_disposition(disps) == A.EXCLUDE_CATALOG
    assert A.should_exclude(disps) is True
    # 送料修正だけの行は除外されない (修正して残す)
    assert A.should_exclude([A.MECH_FIX, A.SEO_NOTE]) is False
    assert A.row_disposition([A.MECH_FIX, A.SEO_NOTE]) == A.MECH_FIX


def test_detect_category():
    headers = ["*Title", "*Category", "C:Game", "C:Card Name", "C:Rarity"]
    rows = [["x", "183454", "Pokémon TCG", "Pikachu", "SR"]]
    assert A.detect_category(headers, rows) == "tcg"
    # *Category 値優先
    h2 = ["*Title", "*Category", "C:Model", "C:Movement"]
    assert A.detect_category(h2, [["x", "31387", "GA-100", "Quartz"]]) == "gshock"
    # Mercari apparel (eBay cat or C:Department)
    assert A.detect_category(["*Title", "*Category"], [["x", "57988"]]) == "mercari"
    assert A.detect_category(["*Title", "C:Department"], [["x", "Men"]]) == "mercari"
    # check_csv 無しカテゴリ (reel 261030 等) → generic (汎用監査は通す)
    assert A.detect_category(["*Title", "*Category"], [["x", "261030"]]) == "generic"
    # 空CSV → None
    assert A.detect_category([], []) is None


def test_ebay_aspect_findings():
    # 公式フィルタ(Aspects)照合: SELECTION_ONLY値の許容外検出 / 特殊値は許容 / 推奨未充足
    fake = {
        "Rarity": {"constraint": {"aspect_mode": "SELECTION_ONLY", "aspect_usage": "RECOMMENDED"},
                   "values": ["Common", "Rare", "Secret Rare"]},
        "Speciality": {"constraint": {"aspect_mode": "FREE_TEXT", "aspect_usage": "RECOMMENDED"},
                       "values": []},
        "Country of Origin": {"constraint": {"aspect_mode": "SELECTION_ONLY", "aspect_usage": "OPTIONAL"},
                              "values": ["Japan", "United States"]},
    }
    A._ASPECT_CACHE[A.CATEGORY_MAP["tcg"]["aspect_json"]] = fake
    headers = ["*Title", "C:Rarity", "C:Country of Origin"]
    rows = [
        ["x", "Ultra Rare", "Does not apply"],   # Rarity 許容外 / CoO は特殊値=許容
        ["y", "Rare", "Japan"],                  # 両方OK
    ]
    notes = A.ebay_aspect_findings(headers, rows, "tcg")
    msgs = " ".join(m for _, m in notes)
    assert "'Rarity'='Ultra Rare'" in msgs and "許容値外" in msgs       # SELECTION_ONLY違反検出
    assert "Does not apply" not in msgs                                  # 特殊値は誤検出しない
    assert "Speciality" in msgs and "列が無い" in msgs                   # eBay推奨aspect未設定=SEO機会
    del A._ASPECT_CACHE[A.CATEGORY_MAP["tcg"]["aspect_json"]]


def test_generic_findings_title_safety():
    # 汎用監査: 日本語混入 + 80字超 を捕捉、分類は除外/報告に倒れる
    headers = ["*Title", "*Category"]
    jp = A.generic_findings(headers, ["リール 新品 Japan", "261030"])
    assert any("日本語" in m for _, m in jp)
    long = A.generic_findings(headers, ["A" * 90, "261030"])
    assert any("上限" in m for _, m in long)
    # 正常タイトルは findings 0
    assert A.generic_findings(headers, ["Daiwa Zillion SV TW 1000 Baitcast Reel New Japan", "261030"]) == []


# --- タイトル↔Item Specifics 整合 (生成ロジック準拠の検証) ---
def test_consistency_gshock_model_series_NOT_flagged():
    """C:Model は eBay の『シリーズ』正規値 (G-SHOCK 5600 / G-SHOCK G-LIDE)。
    タイトルの実型番と異なって当然 → 整合チェックの対象外 = 誤検出しない (2026-06-08 訂正)。
    以前は『defect検出』としていたが、公式フィルタJSONで両方とも正規値と確認され誤検出と判明。"""
    h = ["*Title", "C:Model", "C:Display", "C:Band Color"]
    row = ["CASIO G-Shock GBX-100NS-1JF Mens Digital Watch Black New",
           "G-SHOCK G-LIDE", "Digital", "Black"]
    out = A.title_spec_consistency(h, row, "gshock")
    assert not any("C:Model" in m for m in out)        # Model は不一致として出さない
    assert A.title_spec_consistency(h, row, "gshock") == []  # Display/Band Color は一致


def test_consistency_gshock_display_mismatch_flagged():
    """C:Display がタイトルに反映されてない場合は検出 (Display/Band Color は正当な整合対象)。"""
    h = ["*Title", "C:Model", "C:Display", "C:Band Color"]
    row = ["CASIO G-Shock GA-2100 Mens Watch Black New", "G-SHOCK 2100", "Analog", "Black"]
    out = A.title_spec_consistency(h, row, "gshock")
    assert any("C:Display" in m for m in out)           # 'Analog' がタイトルに無い → 検出


def test_consistency_empty_spec_no_finding():
    """spec が空なら整合判定しない (空欄は別ゲートの責務)。"""
    h = ["*Title", "C:Model", "C:Display", "C:Band Color"]
    row = ["CASIO G-Shock GA-2100 Mens Digital Watch Black New", "", "", ""]
    assert A.title_spec_consistency(h, row, "gshock") == []


def test_consistency_unknown_project_skip():
    h = ["*Title", "C:Model"]
    assert A.title_spec_consistency(h, ["x", "y"], "generic") == []


def test_consistency_tcg_character_missing_flagged():
    h = ["*Title", "C:Character"]
    row = ["PSA 10 Pokemon Crown Zenith #200 Mewtwo VSTAR", "Pikachu"]
    out = A.title_spec_consistency(h, row, "tcg")
    assert any("C:Character" in m for m in out)
    # キャラがタイトルに在れば検出しない
    row2 = ["PSA 10 Pokemon Crown Zenith #025 Pikachu", "Pikachu"]
    assert A.title_spec_consistency(h, row2, "tcg") == []


# --- タイトル形式準拠 (生成ロジックのフォーマット) ---
def test_format_gshock_prefix_and_watch():
    h = ["*Title", "C:Brand"]
    assert A.title_format_checks(h, ["Casio GA-2100 Black New", ""], "gshock")  # prefix違反検出
    ok = ["CASIO G-Shock GA-2100-1A1 Mens Digital Watch Black New", ""]
    assert A.title_format_checks(h, ok, "gshock") == []


def test_format_ichibankuji_prefix():
    h = ["*Title"]
    assert A.title_format_checks(h, ["My Hero Academia A Prize Figure"], "ichibankuji")
    assert A.title_format_checks(h, ["Ichiban Kuji One Piece A Prize Luffy Figure New"], "ichibankuji") == []


def test_format_mercari_uniqlo_brand_must_be_uniqlo():
    h = ["*Title", "C:Brand"]
    # Brand='UNIQLO UT' は公式名でない → 検出
    bad = ["UNIQLO UT Doraemon T-Shirt Black US M Japan", "UNIQLO UT"]
    out = A.title_format_checks(h, bad, "mercari")
    assert any("eBay公式ブランド名でない" in m for m in out)
    # Brand='Uniqlo' + T-Shirt 有り → OK
    good = ["UNIQLO UT Doraemon T-Shirt Black US M Japan", "Uniqlo"]
    assert A.title_format_checks(h, good, "mercari") == []


def test_format_mercari_porter_requires_porter_and_condition():
    h = ["*Title", "C:Brand"]
    good = ["YOSHIDA PORTER Tanker Shoulder Bag S Black Used Japan", "Porter"]
    assert A.title_format_checks(h, good, "mercari") == []
    bad = ["Yoshida Tanker Bag Black Japan", "Porter"]  # PORTER語/Used無し
    assert A.title_format_checks(h, bad, "mercari")


def test_format_mercari_unknown_brand_skips():
    h = ["*Title", "C:Brand"]
    assert A.title_format_checks(h, ["Some Random Title", "NoSuchBrand"], "mercari") == []


# --- タイトル SEO 監査 (iMakKeywords PDF 参照) ---
def test_title_seo_score_counts_pdf_terms():
    pool = {"casio g shock": 0.9, "watch": 0.5, "mens watches": 0.4}
    s_hi = A._title_seo_score("CASIO G Shock Mens Watch Black New", pool)
    s_lo = A._title_seo_score("Black Resin Accessory New", pool)
    assert s_hi > s_lo


def test_title_seo_findings_flags_relative_weak():
    """同 CSV 内で PDF上位語の活用が他行比で著しく低い行を報告 (実ファイル非依存=cacheに注入)。"""
    pool = {"pokemon": 0.9, "card": 0.6, "psa": 0.5, "vstar": 0.3}
    A._KW_POOL_CACHE[A.KEYWORD_TXT["tcg"]] = pool  # PDF読込を差し替え (キーはファイル名)
    h = ["*Title"]
    rows = [
        ["PSA 10 Pokemon Card VSTAR strong"],   # 高 score
        ["PSA 10 Pokemon Card VSTAR strong"],   # 高 score
        ["PSA 10 Pokemon Card VSTAR strong"],   # 高 score
        ["Random Item No Keywords Here"],        # 0 score → 弱フラグ
    ]
    out = A.title_seo_findings(h, rows, "tcg")
    assert any("SEO弱" in m for _, m in out)
    A._KW_POOL_CACHE.pop(A.KEYWORD_TXT["tcg"], None)


def test_title_seo_findings_skip_when_no_pool():
    """KEYWORD_TXT に無い project (PDF未整備) は skip。"""
    assert A.title_seo_findings(["*Title"], [["x"], ["y"], ["z"]], "nopdf_project") == []


def test_mercari_seo_groups_by_brand_pdf():
    """Mercari は C:Brand で PDF を出し分け、商品グループごとに相対比較する (未対応を残さない)。"""
    A._KW_POOL_CACHE[A._TXT_CLOTHING] = {"bag": 0.8, "porter": 0.7, "nylon": 0.5}
    A._KW_POOL_CACHE[A._TXT_SPORTING] = {"reel": 0.8, "fishing": 0.7, "baitcast": 0.5}
    h = ["*Title", "C:Brand"]
    rows = [
        ["YOSHIDA PORTER Tanker Bag Nylon Japan", "Porter"],   # 衣料 高
        ["YOSHIDA PORTER Tanker Bag Nylon Japan", "Porter"],   # 衣料 高
        ["Plain Item No Match", "Porter"],                      # 衣料 0 → 弱
        ["Daiwa Fishing Reel Baitcast Japan", "Daiwa"],        # sporting 高
        ["Daiwa Fishing Reel Baitcast Japan", "Daiwa"],        # sporting 高
        ["Nothing Useful Title", "Shimano"],                   # sporting 0 → 弱
    ]
    out = A.title_seo_findings(h, rows, "mercari")
    msgs = " ".join(m for _, m in out)
    assert "Plain Item No Match" in msgs       # 衣料グループの弱行
    assert "Nothing Useful Title" in msgs      # sportingグループの弱行
    A._KW_POOL_CACHE.pop(A._TXT_CLOTHING, None)
    A._KW_POOL_CACHE.pop(A._TXT_SPORTING, None)


def test_mercari_pdf_for_brand_mapping():
    """全 Mercari 商品が PDF にマップされる (porter/uniqlo/montbell/workman→衣料, tomica→toys, リール→sporting)。"""
    assert A._mercari_pdf_for_brand("porter") == A._TXT_CLOTHING
    assert A._mercari_pdf_for_brand("uniqlo") == A._TXT_CLOTHING
    assert A._mercari_pdf_for_brand("montbell") == A._TXT_CLOTHING
    assert A._mercari_pdf_for_brand("workman") == A._TXT_CLOTHING
    assert A._mercari_pdf_for_brand("tomica") == A._TXT_TOYS
    assert A._mercari_pdf_for_brand("daiwa") == A._TXT_SPORTING
    assert A._mercari_pdf_for_brand("shimano") == A._TXT_SPORTING


# --- generic(reel/tomica/workman) も新タイトル検査を受ける (carve-out 撲滅) ---
def test_reel_detected_as_generic_but_routed_to_mercari():
    """reel(261030) は generic 判定だが、タイトル検査は mercari ルールへ routing される。"""
    assert A.detect_category(["*Category", "*Title"], [["261030", "x"]]) == "generic"
    assert A._title_check_project("generic", True) == "mercari"
    assert A._title_check_project("tcg", False) == "tcg"


def test_generic_reel_gets_format_and_seo_via_routing():
    """generic 経路の reel/tomica/workman が形式・SEO検査の対象になる (取りこぼし無し)。"""
    proj = A._title_check_project("generic", True)  # = "mercari"
    # 形式: リールは "Reel" 必須 → 無ければ検出
    h = ["*Title", "C:Brand"]
    bad = ["Daiwa Zillion SV TW 1000 Baitcast Japan", "Daiwa"]  # "Reel" 無し
    assert A.title_format_checks(h, bad, proj)
    # SEO: reel ブランドは sporting PDF にマップ
    assert A._mercari_pdf_for_brand("daiwa") == A._TXT_SPORTING


def test_reel_color_not_consistency_checked():
    """リールは型番中心でタイトルに色を入れない慣習 → C:Color整合は対象外(誤検出防止)。
    一方 porter(バッグ/衣料)は色がタイトルに入るので検出を維持。"""
    h = ["*Title", "C:Brand", "C:Color"]
    # reel: 色がタイトルに無くてもOK (検出しない)
    assert A.title_spec_consistency(h, ["Daiwa Zillion SV TW 1000 Reel Japan", "Daiwa", "Silver"], "mercari") == []
    # porter: 色がタイトルに無ければ検出 (維持)
    out = A.title_spec_consistency(h, ["YOSHIDA PORTER Tanker Bag Used Japan", "Porter", "Red"], "mercari")
    assert any("C:Color" in m for m in out)


# --- G-shock 全滅 誤除外 防止 (2026-06-13) -------------------------------
# check_csv が Movement/Color 空を必須扱いし全8行を誤除外→入稿0件になった件の回帰防止。
# 実機確認: cat 31387 で Movement=RECOMMENDED(必須でない)・"Color" は aspect 自体が無い。
# = eBay必須でない欄での fail-closed 全滅。apparel(mercari)同型なので spec空は報告のみにする。
def test_gshock_spec_empty_does_not_exclude():
    assert A.CATEGORY_MAP["gshock"].get("spec_empty_excludes") is False


def test_mercari_spec_empty_precedent_intact():
    assert A.CATEGORY_MAP["mercari"].get("spec_empty_excludes") is False


def test_tcg_still_excludes_on_spec_empty():
    # TCG は必須spec空を従来どおり除外 (誤って全カテゴリに緩和を広げていないこと)。
    assert A.CATEGORY_MAP["tcg"].get("spec_empty_excludes", True) is not False


def test_spec_empty_message_classified_as_spec_empty():
    # 「必須Item Specific 'C:Color' が空」= SPEC_EMPTY 分類 (除外対象の disposition)。
    assert A.classify_finding("WARN", "必須Item Specific 'C:Color' が空") == A.SPEC_EMPTY


def test_seo_note_is_not_excluding():
    # spec_empty_excludes=False のとき SPEC_EMPTY→SEO_NOTE に倒す。SEO_NOTE は除外しない。
    assert A.should_exclude([A.SEO_NOTE]) is False
    assert A.should_exclude([A.SPEC_EMPTY]) is True
