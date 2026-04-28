"""SKU 詳細シートを header 残して全行クリア (1回限定の運用ツール).

使用シーン:
  - サンプルデータ + 試走で汚れた行を一度全部消して再起動したい時
  - スキーマ変更後の初期化

注意: 実行すると全データ行が消える。事前に必ず確認すること。
"""
from sheet_updater import open_sheet, get_sku_worksheet


def main():
    sh = open_sheet()
    ws = get_sku_worksheet(sh)
    print(f"対象シート: {sh.title} / タブ: {ws.title}")
    print(f"現在の行数: {ws.row_count}, データ行 (header 除く): {len(ws.get_all_values()) - 1}")

    confirm = input("\n全データ行を削除します。続行? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("中止")
        return

    # 行 2 以降を全クリア
    last_row = ws.row_count
    if last_row > 1:
        ws.batch_clear([f"A2:L{last_row}"])
        print(f"✅ A2:L{last_row} をクリア")

    # 行数を 100 に縮小 (条件付き書式の範囲に合わせる)
    if ws.row_count > 100:
        ws.resize(rows=100)
        print(f"✅ 行数を 100 に縮小")

    print("完了")


if __name__ == "__main__":
    main()
