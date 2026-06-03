"""run_revise.py - リバイスくん エントリポイント.

機能:
  --action price          (default) 価格 revise (Phase 1)

廃止: best_offer / title_refresh / relist (= 2026-05-12 整理で削除済)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
if str(THIS) not in sys.path:
    sys.path.insert(0, str(THIS))


def main():
    parser = argparse.ArgumentParser(description="リバイスくん", add_help=False)
    parser.add_argument("--action", choices=["price"], default="price",
                        help="price (= Phase 1 価格 revise)")
    args, remaining = parser.parse_known_args()

    sys.argv = [sys.argv[0]] + remaining
    from revise.price_revise import main as price_main
    return price_main()


if __name__ == "__main__":
    sys.exit(main())
