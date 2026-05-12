"""[移行] iMakHQ/seller_hub_view.py → iMakeBayAPI/seller_hub_view.py に統合.

5/12 ユーザー判断: HQ 専有モジュールから iMakeBayAPI 共有モジュールに移行。
Revise/Inventory/Harvest 等の他 worktree からも import 可能に。

この shim は後方互換用 (control_panel.py や cron batch が参照してる場合の保護)。
将来 直接 iMakeBayAPI/seller_hub_view.py を使う形に切替後、削除可。
"""
from __future__ import annotations

import os
import sys

# iMakeBayAPI を sys.path に追加
_EBAY_API_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI")
if _EBAY_API_DIR not in sys.path:
    sys.path.insert(0, _EBAY_API_DIR)

# 本体を re-export
from seller_hub_view import *  # noqa: F401, F403
from seller_hub_view import main  # noqa: F401


if __name__ == "__main__":
    sys.exit(main())
