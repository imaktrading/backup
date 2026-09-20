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
    got, miss, _marks = T.plan(rows, _Conn())
    assert got == {2: "pokemon_tcg:SV1V-105"}
    assert miss == 1


def test_引けなかった行は空のまま():
    """★推測で入れると、別のカードとして出品することになる (判定不能は skip)。"""
    rows = [HEAD, _row("PSA10 ピカチュウ 25th")]
    got, miss, _marks = T.plan(rows, _Conn())
    assert got == {} and miss == 1


def test_既に入っている行は触らない():
    rows = [HEAD, _row("PSA10 ミモザ SAR SV1V 105/078", key="pokemon_tcg:既存")]
    got, _miss, _m = T.plan(rows, _Conn())
    assert got == {}


def test_KEYの形は商品管理シートと同じ():
    rows = [HEAD, _row("PSA10 ミモザ SAR SV1V 105/078")]
    got, _, _m = T.plan(rows, _Conn())
    assert list(got.values())[0] == "pokemon_tcg:SV1V-105"     # <category>:<product_id>


def test_引き方は1か所から():
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    assert "import catalog_lookup" in src


def test_書くのは明示した時だけ():
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    assert '"--write" in argv' in src


# ---- 仕分けの印 (2026-09-20 ユーザー「トレジャーハント対象はどれか分からない」) ----

def test_門を通る物に出せるの印():
    """★門 (ユーザー確定): 上限+¥7,000 かつ 上限×1.5。**厳しい方が効く**。"""
    assert T.mark_of(10000, 10000) == T.MARK_GO          # ぴったり
    assert T.mark_of(15000, 10000) == T.MARK_GO          # 1.5倍 = 通る
    assert T.mark_of(15001, 10000) == T.MARK_HIGH        # 1.5倍を超える
    assert T.mark_of(57000, 50000) == T.MARK_GO          # +7,000 = 通る
    assert T.mark_of(58000, 50000) == T.MARK_HIGH        # +7,000 を超える


def test_安いカードは1点5倍で締まる():
    """★上限¥400 に ¥5,500 払うと どう転んでも赤字。+¥7,000 だけだと通ってしまう。"""
    assert T.mark_of(5500, 400) == T.MARK_HIGH
    assert T.mark_of(600, 400) == T.MARK_GO


def test_売れ筋でなければ印を付けない():
    assert T.mark_of(5000, None) == T.MARK_NONE
    assert T.mark_of(5000, 0) == T.MARK_NONE


def test_値段が読めなければ出せない側に倒す():
    assert T.mark_of(0, 10000) == T.MARK_HIGH


def test_門の数字を自前で持たない()  :
    """★上限仕入れ値は HQ が実売から逆算した値。ここでは写すだけ。"""
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    body = src.split("def load_caps(")[1].split(chr(10) + "def ")[0]
    assert "上限仕入れ値(円)" in body            # CSV の値をそのまま読む
    assert T.CAP_ADD == 7000 and T.CAP_MUL == 1.5


def test_会社の仕入上限も見る():
    """★2026-09-20 ユーザー「7マン超えてるのあるけど」。

    カードごとの上限とは **別に**、会社としての仕入上限 (¥70,000) がある。
    実害: レックウザEX 122/XY-P は 上限仕入れ値 ¥87,200 でカードの門は通るが、
    会社の上限を超えるので出品できない。◎ に4件 混ざっていた。
    """
    assert T.mark_of(79000, 87200, 70000) == T.MARK_HIGH      # 会社の上限を超える
    assert T.mark_of(69000, 87200, 70000) == T.MARK_GO        # 両方 通る
    assert T.mark_of(69000, 10000, 70000) == T.MARK_HIGH      # カードの上限を超える


def test_会社の上限は自前で持たない():
    """値は global.yaml の1か所。共有領域の写しを読むだけ。"""
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    assert "cost_sanity.json" in src
    body = src.split("def hard_cap(")[1].split(chr(10) + "def ")[0]
    assert "70000" not in body


def test_上限が読めなければ走らない():
    """★判定できないまま印を付けると、出せない物を HIGH に写すことになる。"""
    src = open(os.path.join(HQ, "tools", "treasure_fill_key.py"), encoding="utf-8").read()
    body = src.split("def main(")[1]
    i = body.index("hard_cap() is None")
    assert "return 1" in body[i:i + 200]
