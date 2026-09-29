"""カテゴリ別 product_id 抽出 regex 集約.

fail-closed: hit せず取れない場合は None を返し、 呼出側で「不明」 として扱う。
"""

from .tcg import extract_tcg_id
from .gshock import extract_gshock_model
from .url import extract_mercari_url_key
from .variant import extract_variant

__all__ = [
    "extract_tcg_id",
    "extract_gshock_model",
    "extract_mercari_url_key",
    "extract_variant",
]
