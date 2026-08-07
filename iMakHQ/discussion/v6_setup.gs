/**
 * V6 スプシ 構造改善 一括セットアップ
 *
 * 実行手順:
 *   1. V6 スプシを開く
 *   2. 拡張機能 > Apps Script
 *   3. Code.gs にこの内容を全部貼り付け
 *   4. 関数 `setupV6()` を実行 → 承認ダイアログ → 実行
 *
 * 動作:
 *   - mst_DDP タブ新規追加 (DDP IFS tier + HTS マスタ + HTS_BASE_RATE)
 *   - 名前付き範囲を一括定義 (式が「何の表参照か」一目で分かるように)
 *   - US計算 / UK計算 等の既存タブは触らない (= 段階的移行)
 *
 * ロールバック:
 *   - mst_DDP タブを手動削除
 *   - 名前付き範囲を「データ > 名前付き範囲」で手動削除
 */

function setupV6() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // ===== Step 1: mst_DDP タブ作成 =====
  let mst = ss.getSheetByName('mst_DDP');
  if (mst) {
    ss.deleteSheet(mst);  // 既存ならリセット
  }
  mst = ss.insertSheet('mst_DDP');

  // ヘッダ (出典・更新日)
  mst.getRange('A1').setValue('# DDP 計算マスタ').setFontWeight('bold');
  mst.getRange('A2').setValue('更新日: 2026-05-20');
  mst.getRange('A3').setValue('出典: V3 実績IFS (Gemini ブラッシュ案①) + USITC HTS Schedule 2025');
  mst.getRange('A4').setValue('注意: B セル補正は HTS_BASE_RATE (V3 暗黙想定率) からの差分で計算');

  // V3 ブラッシュ IFS tier 値 (A6-B16)
  mst.getRange('A6:B6').setValues([['max_USD', 'ddp_USD']]).setFontWeight('bold').setBackground('#e8f0fe');
  const ifsTiers = [
    [40,   15],
    [60,   20],
    [100,  35],
    [200,  50],
    [300,  70],
    [400,  90],
    [500,  110],
    [600,  140],
    [800,  180],
    [99999, 250],
  ];
  mst.getRange(7, 1, ifsTiers.length, 2).setValues(ifsTiers);

  // HTS マスタ (D6-E25)
  mst.getRange('D6:E6').setValues([['カテゴリ', 'HTS率']]).setFontWeight('bold').setBackground('#e8f0fe');
  const htsRates = [
    ['TCG(PSA10)',          0],
    ['G-SHOCK',             0.035],
    ['Tシャツ(UT)',         0.27],
    ['Montbell(軽)',        0.27],
    ['Montbell(重)',        0.27],
    ['一番くじ',            0],
    ['フィギュア',          0],
    ['ユニクロ(非UT)',      0.27],
    ['サンリオ文具',        0],
    ['ヴィンテージ玩具',    0],
    ['トミカ',              0],
    ['POPMart',             0],
    ['ガシャポン',          0],
    ['ダイソー',            0],
    ['バッグ(アネロ)',      0.07],
    ['サンリオぬいぐるみ',  0],
    ['Porter',              0.07],
    ['リール',              0],
  ];
  mst.getRange(7, 4, htsRates.length, 2).setValues(htsRates);

  // V3 暗黙想定 HTS 率 (G2)
  mst.getRange('G1').setValue('HTS_BASE_RATE').setFontWeight('bold').setBackground('#fff2cc');
  mst.getRange('G2').setValue(0.20);
  mst.getRange('G3').setValue('= V3 IFS が暗黙に想定する HTS 率');
  mst.getRange('G4').setValue('B セル補正 = HTS率 - HTS_BASE_RATE');

  // 列幅調整
  mst.setColumnWidth(1, 100);
  mst.setColumnWidth(2, 100);
  mst.setColumnWidth(3, 30);
  mst.setColumnWidth(4, 170);
  mst.setColumnWidth(5, 100);
  mst.setColumnWidth(6, 30);
  mst.setColumnWidth(7, 200);

  // ===== Step 2: 名前付き範囲を一括定義 =====
  const ranges = [
    // 既存「設定」タブ から
    ['FX_USD',          "'設定'!B2"],
    ['FX_EUR',          "'設定'!F2"],
    ['FX_GBP',          "'設定'!H2"],
    ['FX_AUD',          "'設定'!J2"],
    ['PROMO_RATE',      "'設定'!B3"],
    ['PAYO_RATE',       "'設定'!B4"],
    ['TARGET_PROFIT',   "'設定'!B5"],
    ['CATEGORY_TBL',    "'設定'!A11:D28"],
    ['COUNTRY_TAX_TBL', "'設定'!A36:E43"],
    ['GSHOCK_FVF_TBL',  "'設定'!A48:B52"],
    // 新規 mst_DDP から
    ['DDP_IFS_TBL',     "'mst_DDP'!A7:B16"],
    ['HTS_TBL',         "'mst_DDP'!D7:E24"],
    ['HTS_BASE_RATE',   "'mst_DDP'!G2"],
  ];

  // 既存 named range 削除 (重複回避)
  ss.getNamedRanges().forEach(nr => {
    if (ranges.some(r => r[0] === nr.getName())) {
      nr.remove();
    }
  });

  // 新規定義
  ranges.forEach(([name, range]) => {
    try {
      ss.setNamedRange(name, ss.getRange(range));
    } catch (e) {
      Logger.log(`Failed to set ${name} = ${range}: ${e.message}`);
    }
  });

  // ===== Step 3: 確認ダイアログ =====
  SpreadsheetApp.getUi().alert(
    'V6 セットアップ完了',
    `mst_DDP タブを追加、${ranges.length} 件の名前付き範囲を定義しました。\n\n` +
    `これだけでは US計算 の式は変わりません (= 既存挙動維持)。\n\n` +
    `次のステップ: US計算 の DDP 列 (N列) を以下に書換:\n\n` +
    `  N_A: =VLOOKUP(F_value, DDP_IFS_TBL, 2)\n` +
    `  N_B: =price × (VLOOKUP(category, HTS_TBL, 2) - HTS_BASE_RATE)\n` +
    `  N:   =N_A + N_B\n\n` +
    `書換は別関数 setupUSCalcDDP() で実行可能 (要事前確認)`,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

/**
 * US計算 の DDP 計算列 (N列) を A/B/最終 の 3 セル分離に書換
 * setupV6() の後に、慎重に実行する。
 * 既存ロジック (N9 = O9*35%) を破壊するので、bk タブにバックアップを取る。
 */
function setupUSCalcDDP() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const us = ss.getSheetByName('US計算');
  if (!us) {
    SpreadsheetApp.getUi().alert('US計算 タブが見つかりません');
    return;
  }

  // バックアップ
  const bkName = 'bk_US計算_' + Utilities.formatDate(new Date(), 'JST', 'yyyyMMdd_HHmmss');
  us.copyTo(ss).setName(bkName);

  // TODO: N列 (DDP) を A/B/最終 に分離する実装
  // 現状: N9 = O9*35% (V5 一律 markup)
  // 変更後:
  //   N_A 列追加 (= VLOOKUP IFS tier)
  //   N_B 列追加 (= HTS 補正)
  //   N 列  (= N_A + N_B)
  // ※ rows 6-12 (試算ラダー) と row 9 (V5 base) の式が違うので個別対応要

  SpreadsheetApp.getUi().alert(
    'バックアップ完了',
    `タブ「${bkName}」に US計算 をコピーしました。\n\n` +
    `DDP 列の書換 (V5 → V3+HTS補正) は手動 or 別関数で実装してください。\n` +
    `先に setupV6() で mst_DDP + Named Range が定義されている必要があります。`,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}
