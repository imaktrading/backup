"""トレジャーハントの候補に KEY を埋める (2026-09-20)。

ユーザー「KEY埋めて」。抽出くんが集めた 1,129件は KEY が全部 空で、そのままでは
出品くんが「どのカードか」を判定できない。KEY を入れるのは **カタログを引くだけ**
なので出品くんの仕事 (値を決めるのはカタログの仕事。ここでは写すだけ)。

実測: 1,129件のうち **648件 (57%) が引けた** (ポケモン494 / ワンピース148 / ガンダム6)。
引けない481件の内訳は **番号が読めない 448件** + 番号は読めたが引けない 33件。
メルカリのタイトルは番号を書かないことが多い ("ピカチュウ 25th PSA10")。
書き方違い (`[SV-P 291]` / `M-P 020`) を拾っても8件しか増えないので入れていない。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import treasure_fill_key as T                                 # noqa: E402


class _Conn:
    """カタログの代わり。引けるのは SV1V-105 だけ。"""

    def execute(self, sql, args=()):
        class R:
            def fetchone(_self):
                if args and str(args[0]).upper() == "SV1V-105":
                    return ("SV1V-105", "Miriam", "ミモザ", "pokemon_tcg", "[]")
                return None

            def fetchall(_self):
                return []
        return R()


HEAD = ["URL", "itemID", "タイトル"] + [""] * 32
def _row(title, key=""):
    r = [""] * 35
    r[T.COL_TITLE] = title
    r[T.COL_KEY] = key
    return r


def test_引けた行だけ埋める():
    rows = [HEAD,
            _row("PSA10 ミモザ SAR SV1V 105/078"),
            _row("PSA10 ピカチュウ 25th")]          # 番号が無い = 引けない
    got, miss = T.plan(rows, _Conn())
    assert got == {2: "pokemon_tcg:SV1V-105"}
    assert miss == 1


def test_引けなかった行は空のまま():
    """★推測で入れると、別のカードとして出品することになる (判定不能は skip)。"""
    rows = [HEAD, _row("PSA10 ピカチュウ 25th")]
    got, miss = T.plan(rows, _Conn())
    assert got == {} and miss == 1


def test_既に入っている行は触らない():
    rows = [HEAD, _row("PSA10 ミモザ SAR SV1V 105/078", key="pokemon_tcg:既存")]
    got, _miss = T.plan(rows, _Conn())
    assert got == {}


def test_KEYの形は商品管理シートと同じ():
    rows = [HEAD, _row("PSA10 ミモザ SAR SV1V 105/078")]
    got, _ = T.plan(rows, _Conn())
    assert list(got.values())[0] == "pokemon_tcg:SV1V-105"     # <category>:<product_id>


def test_引き方は1か所から():
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    assert "import catalog_lookup" in src


def test_書くのは明示した時だけ():
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    assert '"--write" in argv' in src
