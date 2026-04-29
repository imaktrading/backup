"""scrapers - 仕入元別の在庫スクレイピングモジュール群.

各 scraper は単独実行可能な独立モジュールとして実装する。
共通インターフェース:
  - fetch_product_inventory(url, **kwargs) -> dict
  - is_sold(url, **kwargs) -> bool  (1点もの仕入元向け、TCG/Mercari)
"""
