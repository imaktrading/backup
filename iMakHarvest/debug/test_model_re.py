import re, json
from pathlib import Path
data=json.loads(Path("debug/empty_key_analysis.json").read_text(encoding="utf-8"))
# 改良: 型番が日本語に隣接しても抽出。 \b に依存せず、 ASCII 英数記号の塊を取り
# 末尾の連続英字(色名サフィックス含む)まで。 ハイフン無し型番(GWA11001A3JF)も拾う。
# 1) ハイフン付き標準型番: PREFIX-CORE(-SUFFIX)
RE_HYPH = re.compile(r'[A-Z]{2,5}-[A-Z0-9]+(?:-[0-9][A-Z0-9]*)?')
# 2) ハイフン無し long token (= GWA11001A3JF 等、 英字始まり 8文字以上 英数)
RE_NOHYPH = re.compile(r'\b[A-Z]{2,4}[0-9]{3,}[A-Z0-9]{2,}\b')
for d in data:
    t=d["title"].upper()
    if d["is_band"]:
        continue
    h=RE_HYPH.findall(t)
    nh=RE_NOHYPH.findall(t)
    print(f"row{d['row']} flg={d['flg']!r}")
    print(f"   hyph={h}")
    print(f"   nohyph={nh}")
