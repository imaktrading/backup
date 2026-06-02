"""PSA cert metadata cache (= 共通 API 連携 hub の PSA 担当 module).

設計原則 (= 2026-05-28 体系的再評価で確立、 gemini レビュー推奨):
- SoC: PSA cert metadata 連携を iMakeBayAPI 内に集約 (= eBay API と同 layer)
- SSOT: cert → metadata の唯一の内部真実 (= 外部 SSOT = PSA web)
- DRY: 出品くん (= 書込) / 重複くん (= 読込) で共通 caller 利用

役割分担:
- 出品くん iMakTCG/psa_to_csv: PSA scrape 後に save_cache() で永続化
- 重複くん iMakDedupe/dedupe: get_cached() のみで参照 (= driver 不要、 速度問題なし)

cache miss 時の重複くん挙動:
- title-only fallback で代替 (= 既存 logic 維持、 fail-closed)
"""
import json
from pathlib import Path
from typing import Optional, Dict

_CACHE_DIR = Path(__file__).parent / "cache" / "psa_certs"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cached(cert: str) -> Optional[Dict]:
    """cert metadata cache 参照. miss / 不正 → None (= fail-closed).

    Returns: 出品くん get_psa_data 戻り値同形 dict (= Brand / Subject / CardNumber / Year / etc)
    """
    if not cert:
        return None
    f = _CACHE_DIR / f"{cert}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(cert: str, metadata: Dict) -> bool:
    """metadata を cert 単位で永続化 (= 出品くん cycle で scrape 後 call).

    Returns: 書込成功 True、 失敗 False (= fail-closed、 既存 cycle 続行)
    """
    if not cert or not metadata:
        return False
    f = _CACHE_DIR / f"{cert}.json"
    try:
        f.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def cache_stats() -> Dict[str, int]:
    """cache 統計 (= 監査用)."""
    files = list(_CACHE_DIR.glob("*.json"))
    return {"total_certs": len(files), "dir": str(_CACHE_DIR)}
