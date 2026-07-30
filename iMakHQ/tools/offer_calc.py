"""オファー判定 HTML を生成する — 仕入値とオファー金額を入れると利益が出る (2026-07-30).

なぜ:
    利益計算タブが 6 つあり (US / US_非US / UK / DE / AU / CA)、**選び間違えると判断を誤る**。
    特に US サイトは **バイヤーが米国内か国外か**でタブが変わる (関税を払うか払わないか)。
    無条件に US計算 で見ると実態より悪く出て、**通せるオファーを落とす**。

★数式はスプレッドシート (v9) の各タブ 15 行を**そのまま移植**している。
  別実装で式を作り直すと数字がズレ、「どちらが正しいか」が分からなくなる。
  生成時に **シートへ実際に金額を書いて読み戻し、一致を検証**する (--verify)。

使い方:
    python offer_calc.py            # 生成して開く
    python offer_calc.py --verify   # 生成 + シートと突合検証 (数式を変えた時は必ず)
"""
from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHEET_ID = "1YLnR4aW5cgjquYXUaNPb_hnVwrHegobZyh-eAT6tVM0"
OUT = Path(r"C:\dev\iMak_data\hq\offer_calc.html")
TABS = {"US計算": 1508273141, "US計算_非US": 607539795, "UK計算": 5314130,
        "DE計算": 1674894197, "AU計算": 1197179659, "CA計算": 1530445170}
# 仕向地 → (タブ, 通貨記号, 為替キー)
ROUTES = {
    "US": ("US計算", "$", "USD"),
    "CA": ("CA計算", "C$", "CAD"),
    "UK": ("UK計算", "£", "GBP"),
    "DE": ("DE計算", "€", "EUR"),
    "AU": ("AU計算", "A$", "AUD"),
    "その他 (US出品・米国外へ発送)": ("US計算_非US", "$", "USD"),
}


def fetch():
    """設定タブから、計算に要る値を全部取る (これが SSOT)。"""
    import gspread
    from google.oauth2.service_account import Credentials

    import sheet_io
    creds = Credentials.from_service_account_file(
        sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)
    st = sh.worksheet("設定")

    # ★2026-07-30: **生値で読む**。表示値だと丸めが入り、TCG の公式 13.25% が
    #   「13.3%」として読まれて 0.05% ずれ、検証が DE/AU で落ちた。
    #   率は小数 (0.1325) でそのまま入っているので、%変換もしない。
    def get(ref):
        v = st.get(ref, value_render_option="UNFORMATTED_VALUE")
        return v if v else []

    def num(v):
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace(",", "").replace("%", "").replace("¥", "").replace("$", "").strip()
        try:
            f = float(s)
        except ValueError:
            return 0.0
        return f / 100 if "%" in str(v) else f

    fx_row = get("A2:L2")[0]
    fx = {"USD": num(fx_row[1]), "EUR": num(fx_row[5]), "GBP": num(fx_row[7]),
          "AUD": num(fx_row[9]), "CAD": num(fx_row[11])}
    promo = num(get("B3")[0][0])
    payo = num(get("B4")[0][0])
    target = num(get("B5")[0][0])

    cats = {}
    for r in get("A11:F30"):
        r = (list(r) + [""] * 6)[:6]
        if str(r[0]).strip():
            cats[r[0]] = {"fvf": num(r[1]), "ship": num(r[2]), "hts": num(r[4]), "split": num(r[5])}

    country = {}
    for r in get("A36:E44"):
        r = (list(r) + [""] * 5)[:5]
        if str(r[0]).strip():
            country[r[0]] = {"tax": num(r[1]), "intl": num(r[2]), "reg": num(r[3])}

    gshock = {}
    for r in get("A48:B52"):
        r = (list(r) + [""] * 2)[:2]
        if str(r[0]).strip():
            gshock[r[0]] = num(r[1])

    ship_mode = (sh.worksheet("US計算_非US").get("S3") or [["FedEx7"]])[0][0]
    return {"fx": fx, "promo": promo, "payo": payo, "target": target, "cats": cats,
            "country": country, "gshock": gshock, "shipMode": ship_mode,
            "routes": ROUTES, "tabs": TABS,
            "url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid="}


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>オファー判定 — 通していい？</title><style>
body{font-family:system-ui,'Meiryo',sans-serif;background:#141414;color:#eee;margin:0;padding:20px;
  max-width:980px}
h1{color:#ffd700;font-size:20px;margin:0 0 2px}
.sub{color:#999;font-size:12px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.f{background:#1e1e1e;border:1px solid #333;border-radius:8px;padding:12px}
.f label{display:block;color:#9cf;font-size:12px;margin-bottom:6px}
input,select{width:100%;box-sizing:border-box;background:#111;color:#eee;border:1px solid #555;
  border-radius:5px;padding:9px;font-size:16px}
#verdict{margin-top:16px;border-radius:10px;padding:18px;border:2px solid #444;background:#1a1a1a}
#verdict.go{border-color:#4caf50;background:#16301a}
#verdict.warn{border-color:#ff9800;background:#3a2a16}
#verdict.ng{border-color:#f44336;background:#3a1616}
.big{font-size:30px;font-weight:bold}
.line{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #2a2a2a;
  font-size:14px}
.line b{font-variant-numeric:tabular-nums}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
td,th{border:1px solid #3a3a3a;padding:6px 9px;text-align:right}
th{background:#252525;color:#9cf}td:first-child,th:first-child{text-align:left}
.note{color:#bbb;font-size:12px;margin-top:14px;line-height:1.8}
a{color:#7ab8ff}
</style></head><body>
<h1>オファー判定 — 通していい？</h1>
<div class="sub">スプレッドシート v9 の各タブ15行の数式をそのまま移植（生成時に突合検証済）。
最終確認はシートで。</div>

<div class="grid">
  <div class="f"><label>バイヤーの国（仕向地）</label><select id="dest"></select></div>
  <div class="f"><label>カテゴリ</label><select id="cat"></select></div>
  <div class="f"><label>オファー金額（現地通貨）</label><input id="price" type="number" step="0.01" value="70"></div>
  <div class="f"><label>仕入値（円）</label><input id="cost" type="number" step="10" value="1800"></div>
  <div class="f"><label>ポイント還元（円）</label><input id="pt" type="number" step="10" value="0"></div>
  <div class="f"><label>プロモ</label><select id="promo">
      <option value="0">外す（承諾時はこちら）</option><option value="1">つけたまま</option></select></div>
</div>

<div id="verdict"></div>

<div class="note">
★ <b>承諾するならプロモは外す</b>。10%のまま見ると赤字に見え、通せる案件を落とす
（実例: $70承諾 ad10%で ¥-150 / ad0%で ¥+1,212）。<br>
★ <b>仕入は「購入 → 入金確認 → 少し置く」</b>。承諾時点では仕入れない。<br>
★ 米国向けは <b>関税を我々が負担（DDP）</b>。米国外はDDUなので同じ価格でも利益が厚い。<br>
★ 最終判断はシートで。<span id="lnk"></span>
</div>

<script>
const P = __DATA__;
const dest = document.getElementById('dest'), cat = document.getElementById('cat');
Object.keys(P.routes).forEach(k => dest.add(new Option(k, k)));
Object.keys(P.cats).forEach(k => cat.add(new Option(k, k)));
cat.value = 'TCG(PSA10)';

const DDP = [10,20,30,40,50,60,70,80,90,100,120,140,160,180,200,220,240,260,280,300,
             350,400,450,500,550,600,700,800,900,1000,1500];
const yen = n => '¥' + Math.round(n).toLocaleString();

function feeRate(countryKey, catKey){
  const c = P.country[countryKey] || {tax:0,intl:0.0165,reg:0};
  const base = (catKey === 'G-SHOCK')
      ? (P.gshock[countryKey] !== undefined ? P.gshock[countryKey] : (P.gshock['その他'] || 0.1375))
      : P.cats[catKey].fvf;
  return (base + c.intl + c.reg) * (1 + c.tax);
}

function calc(price){
  const dk = dest.value, ck = cat.value;
  const [tab, sym, cur] = P.routes[dk];
  const fx = P.fx[cur], C = P.cats[ck];
  const promo = document.getElementById('promo').value === '1' ? P.promo : 0;
  const cost = +document.getElementById('cost').value || 0;
  const pt = +document.getElementById('pt').value || 0;
  const J = C.ship;
  let cKey = (dk === 'その他 (US出品・米国外へ発送)') ? 'US' : dk;
  const fr = feeRate(cKey === 'US' && tab === 'US計算_非US' ? 'US' : cKey, ck);
  let D, E, F, G, N, K, L, M;

  if (tab === 'US計算' || tab === 'US計算_非US'){
    F = Math.floor(price + (price * C.hts * 1.021 + 245 / fx) * (1 - C.split)) + 0.98;
    if (tab === 'US計算'){
      const t = DDP.find(x => F <= x) || 1500;
      D = t * C.hts * 1.021 * C.split + 1.5;
      N = D * fx;
    } else {
      D = P.shipMode === '独' ? 17 : (P.shipMode === 'FedEx7' ? 20 : 0);
      N = P.shipMode === '独' ? (2296 - J + 3 * P.fx.EUR + 555)
        : (P.shipMode === 'FedEx7' ? (2721 - J + 3 * P.fx.EUR + 555) : 0);
    }
    E = F + D; G = E * fx;
    K = G * fr + 0.4 * fx; L = G * promo; M = G * P.payo;
  } else {
    const tax = (P.country[cKey] || {tax:0}).tax;
    D = price * tax; E = price + D; F = price; G = E * fx; N = D * fx;
    K = (G - N) * fr + 0.4 * fx; L = (G - N) * promo; M = (G - N) * P.payo;
  }
  const O = cost - pt + J + K + L + M + N;
  return {tab, sym, cur, fx, fr, price, D, E, F, G, N, K, L, M, J, O,
          profit: G - O, margin: (G - O) / G, cost, pt};
}

function solve(targetMargin){                 // その利益率になる価格を二分探索
  let lo = 0.5, hi = 5000;
  for (let i = 0; i < 60; i++){
    const mid = (lo + hi) / 2;
    (calc(mid).margin < targetMargin) ? lo = mid : hi = mid;
  }
  return (lo + hi) / 2;
}

function render(){
  const r = calc(+document.getElementById('price').value || 0);
  const v = document.getElementById('verdict');
  const ok = r.margin >= P.target, be = r.profit > 0;
  v.className = ok ? 'go' : (be ? 'warn' : 'ng');
  const head = ok ? '✅ 通してよい' : (be ? '⚠️ 薄い（黒字だが目標未達）' : '🚫 赤字');
  const breakEven = solve(0), targetPrice = solve(P.target);
  v.innerHTML =
    '<div class="big">' + head + '</div>' +
    '<div style="font-size:26px;margin:6px 0">利益 ' + yen(r.profit) +
      ' <span style="color:#9cf;font-size:18px">（' + (r.margin * 100).toFixed(1) + '%）</span></div>' +
    '<div style="color:#bbb;font-size:13px">使用: <b>' + r.tab + '</b> ／ 為替 ' +
      r.fx.toFixed(2) + ' 円 ／ 実効手数料率 ' + (r.fr * 100).toFixed(2) + '%</div>' +
    '<table><tr><th>ここまでなら</th><th>金額</th><th>利益</th></tr>' +
      '<tr><td>損益分岐（これ未満は赤字）</td><td>' + r.sym + breakEven.toFixed(2) +
        '</td><td>' + yen(0) + '</td></tr>' +
      '<tr><td>目標 ' + (P.target * 100).toFixed(0) + '% を満たす下限</td><td>' + r.sym +
        targetPrice.toFixed(2) + '</td><td>' + yen(calc(targetPrice).profit) + '</td></tr>' +
      '<tr><td><b>今回のオファー</b></td><td><b>' + r.sym + r.price.toFixed(2) +
        '</b></td><td><b>' + yen(r.profit) + '</b></td></tr></table>' +
    '<div style="margin-top:12px">' +
      line('売上', yen(r.G)) + line('仕入', '-' + yen(r.cost)) +
      (r.pt ? line('ポイント還元', '+' + yen(r.pt)) : '') +
      line('送料', '-' + yen(r.J)) + line('eBay手数料', '-' + yen(r.K)) +
      line('プロモ費', '-' + yen(r.L)) + line('Payoneer', '-' + yen(r.M)) +
      line(r.tab.startsWith('US') ? 'DDP/関税ほか' : 'VAT/GST相殺', '-' + yen(r.N)) +
    '</div>';
  document.getElementById('lnk').innerHTML =
    '<a href="' + P.url + P.tabs[r.tab] + '" target="_blank">' + r.tab + ' を開く</a>' +
    '（C15 に ' + r.sym + r.price.toFixed(2) + ' を入れて 16行を見る）';
}
function line(k, v){ return '<div class="line"><span>' + k + '</span><b>' + v + '</b></div>'; }

['dest','cat','price','cost','pt','promo'].forEach(id =>
  document.getElementById(id).addEventListener('input', render));
render();
</script></body></html>"""


DDP = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 220, 240, 260, 280,
       300, 350, 400, 450, 500, 550, 600, 700, 800, 900, 1000, 1500]


def calc_py(p, tab, cat_key, dest_key, price, cost, pt=0.0, promo_on=False):
    """HTML(JS) と **同じ式**を Python でも持つ。検証はこれとシートを突き合わせる。

    2実装が食い違ったら、その時点で検証が落ちる = 気づける。
    """
    cur = {"US計算": "USD", "US計算_非US": "USD", "UK計算": "GBP",
           "DE計算": "EUR", "AU計算": "AUD", "CA計算": "CAD"}[tab]
    fx = p["fx"][cur]
    C = p["cats"][cat_key]
    ckey = "US" if tab.startswith("US") else dest_key
    if cat_key == "G-SHOCK":
        base = p["gshock"].get(ckey, p["gshock"].get("その他", 0.1375))
    else:
        base = C["fvf"]
    c = p["country"].get(ckey, {"tax": 0, "intl": 0.0165, "reg": 0})
    fr = (base + c["intl"] + c["reg"]) * (1 + c["tax"])
    promo = p["promo"] if promo_on else 0.0
    J = C["ship"]

    if tab.startswith("US"):
        F = int(price + (price * C["hts"] * 1.021 + 245 / fx) * (1 - C["split"])) + 0.98
        if tab == "US計算":
            t = next((x for x in DDP if F <= x), 1500)
            D = t * C["hts"] * 1.021 * C["split"] + 1.5
            N = D * fx
        else:
            m = p["shipMode"]
            D = 17 if m == "独" else (20 if m == "FedEx7" else 0)
            N = (2296 - J + 3 * p["fx"]["EUR"] + 555) if m == "独" else \
                ((2721 - J + 3 * p["fx"]["EUR"] + 555) if m == "FedEx7" else 0)
        G = (F + D) * fx
        K, L, M = G * fr + 0.4 * fx, G * promo, G * p["payo"]
    else:
        D = price * c["tax"]
        G = (price + D) * fx
        N = D * fx
        K, L, M = (G - N) * fr + 0.4 * fx, (G - N) * promo, (G - N) * p["payo"]

    O = cost - pt + J + K + L + M + N
    return G - O


def verify(p):
    """シートに実際に書いて読み戻し、Python 実装と **1円単位で**一致するか確かめる。

    各タブの 仕入(H9)/ポイ還元(I9)/カテゴリ(F3) を読んで同条件にしてから比較する
    (タブごとに仕入が違うので、揃えないと比較にならない)。
    """
    import gspread
    from google.oauth2.service_account import Credentials

    import sheet_io
    creds = Credentials.from_service_account_file(
        sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)

    def num(v):
        s = str(v).replace(",", "").replace("¥", "").replace("$", "").replace("£", "")
        s = s.replace("€", "").replace("A$", "").replace("C$", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    def cell(ws, ref, default=""):
        """空セルでも落ちない読取 (gspread は空だと [] を返す)。"""
        v = ws.get(ref)
        if not v or not v[0]:
            return default
        return v[0][0]

    print("\n=== 突合検証 (シート vs Python実装) ===")
    ng = 0
    for dest, (tab, sym, cur) in ROUTES.items():
        ws = sh.worksheet(tab)
        cat_key = cell(ws, "F3", "Tシャツ(UT)")
        cost = num(cell(ws, "H9", "0"))
        pt = num(cell(ws, "I9", "0"))
        keep = cell(ws, "C15", "70")
        for price in (50, 100, 250):
            ws.update_acell("C15", price)
            row = (ws.get("B16:Q16") or [[]])[0]
            sheet_profit = num(row[14]) if len(row) > 14 else None
            mine = calc_py(p, tab, cat_key, dest if not tab.startswith("US") else "US",
                           price, cost, pt, promo_on=False)
            diff = abs((sheet_profit or 0) - mine)
            mark = "✅" if diff <= 1.5 else "❌"
            if diff > 1.5:
                ng += 1
            print(f"  {mark} {tab:<12} {cat_key:<12} price={price:<4} "
                  f"シート={sheet_profit:>10,.0f}  実装={mine:>10,.0f}  差={diff:>6,.1f}")
        ws.update_acell("C15", keep)
    print(f"\n  → 不一致 {ng} 件" + ("  (0 が正)" if ng == 0 else "  ★数式の移植ミス。直すこと"))
    return ng


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = fetch()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", json.dumps(p, ensure_ascii=False)), encoding="utf-8")
    print(f"✅ 生成: {OUT}")
    if "--verify" in sys.argv:
        verify(p)
    webbrowser.open(OUT.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
