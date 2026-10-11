"""is_psa10: PCG は後に数字がある時だけ他社鑑定 (2026-10-12 B-20261012-002)。

実害: 「PSA10 わるいヘルガー … PCG 構築済みデッキ」(PCG = ポケカの旧シリーズ名) を他社鑑定と見て、
監視くんが正しい PSA10 の補URLを外した。9/24 の「【PCG10鑑定品】」は引き続き落とす。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from mercari_psa_resource import is_psa10


def test_PCG_のシリーズ名は_PSA10_のまま():
    assert is_psa10("PSA10 わるいヘルガー PCG 構築済みデッキ") is True
    assert is_psa10("【PSA10】ヘルガー PCG") is True


def test_PCG_の後に数字は他社鑑定():
    assert is_psa10("【PCG10鑑定品】リザードン（同PSA10）") is False
    assert is_psa10("PCG 10 ピカチュウ PSA10相当でない") is False


def test_ほかの他社鑑定はそのまま():
    assert is_psa10("CGC pristine PSA10 ルフィ") is False
    assert is_psa10("PSA10 STARS ピカチュウ") is True
