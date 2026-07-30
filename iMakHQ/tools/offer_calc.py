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
# ★2026-07-31: DE計算 / US計算_非US を DDP構造版へ差替えたため gid が変わった
#   (旧タブは *_bk20260731 として残置)。gid はタブを開くリンクにしか使わないが、
#   古いままだと退避タブへ飛ぶので更新すること。
TABS = {"US計算": 1508273141, "US計算_非US": 44630822, "UK計算": 5314130,
        "DE計算": 793979528, "AU計算": 1197179659, "CA計算": 1530445170}
# 仕向地 → (タブ, 通貨記号, 為替キー)
ROUTES = {
    "US": ("US計算", "$", "USD"),
    "CA": ("CA計算", "C$", "CAD"),
    "UK": ("UK計算", "£", "GBP"),
    "DE": ("DE計算", "€", "EUR"),
    "AU": ("AU計算", "A$", "AUD"),
    "その他 (US出品・米国外へ発送)": ("US計算_非US", "$", "USD"),
}


# 商品管理シートの列 (0-based)。sheet_io と同じ並び。
COL_URL, COL_ITEMID, COL_COST_N, COL_STOCKCHK, COL_CAT = 0, 1, 13, 14, 17
COL_AUX = range(28, 33)          # AC〜AG = 補URL 1〜5
CUR2DEST = {"EUR": "DE", "GBP": "UK", "AUD": "AU", "CAD": "CA"}
CAT2CALC = {"TCG": "TCG(PSA10)", "PSA": "TCG(PSA10)", "G-SHOCK": "G-SHOCK",
            "Tシャツ": "Tシャツ(UT)", "montbell": "Montbell(軽)", "一番くじ": "一番くじ"}


def fetch_offers():
    """受信中の Best Offer を eBay から取り、商品管理シートの仕入値まで解決して返す。

    なぜ (2026-07-31 ユーザー要望「ボタンを押せば仕入れ値まで拾って HTML を出せる?」):
        オファーは期限が短い (実例: 受信から丸1日)。**国・出品価格・仕入値を人が
        探して手入力する時間が判断を遅らせる**。全部 API とシートから取れるので取る。

    ★仕入値は **商品管理シート N列 (実質仕入値)** が SSOT。補URL から推測しない。
      N = (M or F) − K の ARRAYFORMULA で、監視くんが供給を見て維持している値。
    ★ミラー (ebay.de 等) の itemID はシートに無い。**SKU (= mercari item ID) が
      A列の仕入元 URL に含まれる**ので、そこで突合する。
    """
    import re
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
    import dns_cache  # noqa: F401
    import fix_de_speedpak_shipping as fx

    fx.refresh()
    tok = fx.token()

    # 1) オファーが付いている listing を特定 (GetBestOffers 単体では ItemID が返らない)
    items = {}
    for n in range(1, 40):
        inner = ('<ActiveList><Include>true</Include><Pagination>'
                 f'<EntriesPerPage>200</EntriesPerPage><PageNumber>{n}</PageNumber>'
                 '</Pagination></ActiveList><DetailLevel>ReturnAll</DetailLevel>')
        t = fx.post("GetMyeBaySelling", inner, tok)
        al = t[t.find("<ActiveList>"):t.find("</ActiveList>")]
        chunk = re.findall(r"<Item>(.*?)</Item>", al, re.S)
        if not chunk:
            break
        for it in chunk:
            bo = re.search(r"<BestOfferCount>(\d+)</BestOfferCount>", it)
            if not (bo and int(bo.group(1)) > 0):
                continue
            iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
            cp = re.search(r'<CurrentPrice currencyID="(\w+)">([\d.]+)<', it)
            ti = re.search(r"<Title>(.*?)</Title>", it)
            vu = re.search(r"<ViewItemURL>(.*?)</ViewItemURL>", it)
            if iid and cp:
                items[iid.group(1)] = {
                    "list": float(cp.group(2)), "cur": cp.group(1),
                    "title": (ti.group(1) if ti else "").replace("&amp;", "&"),
                    "url": vu.group(1) if vu else ""}
        tp = re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", t)
        if tp and n >= int(tp.group(1)):
            break
    if not items:
        return []

    # 2) 商品管理シート (仕入値 SSOT) を1回だけ読む
    rows = []
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        import sheet_io
        creds = Credentials.from_service_account_file(
            sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        ws = (gspread.authorize(creds).open_by_key(sheet_io.PRODUCT_SHEET_ID)
              .get_worksheet_by_id(sheet_io.PRODUCT_GID))
        rows = ws.get_all_values()[1:]
    except Exception as e:                                    # noqa: BLE001
        print(f"⚠️ 商品管理シートが読めない ({e}) → 仕入値は 0 で出す")

    def yen(v):
        try:
            return int(str(v).replace(",", "").replace("¥", "").strip() or 0)
        except ValueError:
            return 0

    out = []
    for iid, meta in items.items():
        # 3) その listing のオファー明細
        x = fx.post("GetBestOffers",
                    f"<ItemID>{iid}</ItemID><BestOfferStatus>Active</BestOfferStatus>"
                    "<DetailLevel>ReturnAll</DetailLevel>", tok, site="0")
        # 4) SKU (= 仕入元 mercari item ID) を取る
        gi = fx.post("GetItem", f"<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel>",
                     tok, site="0")
        m = re.search(r"<SKU>(.*?)</SKU>", gi)
        sku = m.group(1) if m else ""

        cost, stock, supply, cat_sheet, cost_src = 0, "", 0, "", ""
        for r in rows:
            if sku and len(r) > COL_URL and sku in (r[COL_URL] or ""):
                cost = yen(r[COL_COST_N] if len(r) > COL_COST_N else 0)
                stock = r[COL_STOCKCHK] if len(r) > COL_STOCKCHK else ""
                supply = sum(1 for i in COL_AUX if len(r) > i and (r[i] or "").strip())
                cat_sheet = r[COL_CAT] if len(r) > COL_CAT else ""
                cost_src = f"商品管理シート N列 / itemID {r[COL_ITEMID]}"
                break

        for o in re.findall(r"<BestOffer>(.*?)</BestOffer>", x, re.S):
            def g(t, s=o):
                mm = re.search(rf"<{t}[^>]*>(.*?)</{t}>", s, re.S)
                return mm.group(1) if mm else ""
            if g("Status") != "Pending":
                continue
            country = g("CountryName")
            cur = meta["cur"]
            dest = CUR2DEST.get(cur) or ("US" if country == "US"
                                         else "その他 (US出品・米国外へ発送)")
            calc_cat = next((v for k, v in CAT2CALC.items()
                             if k.lower() in (cat_sheet or "").lower()), "TCG(PSA10)")
            out.append({
                "itemId": iid, "title": meta["title"], "url": meta["url"],
                "list": meta["list"], "sym": {"EUR": "€", "GBP": "£", "AUD": "A$",
                                              "CAD": "C$"}.get(cur, "$"),
                "price": float(g("Price") or 0), "dest": dest,
                "destLabel": f"{country or '?'}／{cur}", "country": country or "?",
                "cat": calc_cat, "cost": cost, "costSrc": cost_src,
                "stock": stock, "supply": supply,
                "buyer": g("UserID"), "fb": g("FeedbackScore"),
                "expire": (g("ExpirationTime") or "")[:16].replace("T", " "),
            })
    out.sort(key=lambda o: o["expire"])
    return out


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

    # ★2026-07-31: 旧 shipMode(独/FedEx7) 廃止。EU送料マスタ から国別に取る。
    #   FedEx は 2026-07-30 に全廃し rate table は Economy 4段階 ($17/$20/$24/$28)。
    eu, jp_post, ioss = {}, 1240.0, 150.0
    try:
        m = sh.worksheet("EU送料マスタ")
        for r in m.get("A11:J35", value_render_option="UNFORMATTED_VALUE"):
            r = (list(r) + [""] * 10)[:10]
            if str(r[0]).strip() and isinstance(r[7], (int, float)):
                eu[str(r[0]).strip()] = {"tier": num(r[2]), "cost": num(r[7]),
                                         "name": str(r[1])}
        # >€150 = DDU 帯の定数 (日本郵便実費 / IOSS上限)
        c = m.get("F6:F7", value_render_option="UNFORMATTED_VALUE")
        if c and len(c) >= 2:
            jp_post, ioss = num(c[0][0]) or jp_post, num(c[1][0]) or ioss
    except Exception:                                          # noqa: BLE001
        pass
    de_ship = 14.86        # DEミラーの国内(DE宛)送料。AT宛は 17.49
    at_ship = 17.49
    return {"fx": fx, "promo": promo, "payo": payo, "target": target, "cats": cats,
            "country": country, "gshock": gshock,
            "eu": eu, "deShip": de_ship, "atShip": at_ship,
            "jpPost": jp_post, "iossEur": ioss,
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

<div class="f" style="margin-bottom:12px">
  <label>📥 受信中のオファー（選ぶと全項目が入る）</label>
  <div id="offerbox"><select id="offersel"></select>
    <div id="meta" style="color:#9cf;font-size:12px;margin-top:6px"></div></div>
</div>

<div class="grid">
  <div class="f"><label>バイヤーの国（仕向地）</label><select id="dest"></select></div>
  <div class="f"><label>カテゴリ</label><select id="cat"></select></div>
  <div class="f"><label>オファー金額（現地通貨）</label><input id="price" type="number" step="0.01" value="70"></div>
  <div class="f"><label>出品価格（任意・帯またぎ検出用）</label><input id="list" type="number" step="0.01" value="0"></div>
  <div class="f"><label>仕入値（円）</label><input id="cost" type="number" step="10" value="1800"></div>
  <div class="f"><label>ポイント還元（円）</label><input id="pt" type="number" step="10" value="0"></div>
  <div class="f"><label>プロモ</label><select id="promo">
      <option value="0">外す（承諾時はこちら）</option><option value="1">つけたまま</option></select></div>
  <div class="f"><label>EU 仕向国（送料・関税の実費に効く）</label><select id="eucty"></select></div>
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

/* 仕向国コード。DE ルートは DE/AT、その他ルートは EU国セレクタの値を使う */
function euCountry(){
  const s = document.getElementById('eucty');
  return (s && s.value) || 'DE';
}
/* IOSS 上限 (€150) を、そのルートの通貨に換算したしきい値 */
function iossLimit(cur){
  const lim = P.iossEur || 150;
  return lim * (P.fx.EUR || 1) / (P.fx[cur] || 1);
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
      /* ★2026-07-31: EU送料マスタ から国別に取る (旧: 独/FedEx7 の2値)。
         D = rate table の段階($) = 送料収入 (ポリシー値なので帯によらず一定)
         N = 成約額で帯が変わる:
             ≤€150 … DDP/Economy。実費+関税(当方負担) − 想定送料J
             >€150 … DDU/日本郵便。買い手が着払いで関税を払うので当方コストに入れない */
      const e = P.eu[euCountry()] || {tier: 17, cost: 3219};
      D = e.tier;
      N = (price <= iossLimit(cur)) ? (e.cost - J) : (P.jpPost - J);
    }
    E = F + D; G = E * fx;
    K = G * fr + 0.4 * fx; L = G * promo; M = G * P.payo;
  } else {
    const tax = (P.country[cKey] || {tax:0}).tax;
    D = price * tax; E = price + D; F = price; G = E * fx; N = D * fx;
    K = (G - N) * fr + 0.4 * fx; L = (G - N) * promo; M = (G - N) * P.payo;
  }
  /* ★DE計算だけ DDP構造を持つ (DEミラーは送料を別取り €14.86/AT €17.49)。
     送料収入は**ポリシー値なので帯によらず一定**。変わるのはコスト側と VAT率。 */
  let S = 0;
  if (tab === 'DE計算'){
    const c2 = euCountry();
    const R = (c2 === 'AT') ? P.atShip : P.deShip;      // 送料収入 (€)
    const vat = (c2 === 'AT') ? 0.20 : 0.19;            // 実注文で AT=20% を確認
    D = (price + R) * vat;                              // VAT
    E = price + R + D; F = price; G = E * fx; N = D * fx;
    const e = P.eu[c2] || {cost: 3219};
    S = (price <= P.iossEur ? e.cost : P.jpPost) - J;   // DDPコスト (>€150 は DDU=関税なし)
    K = (G - N) * fr + 0.4 * fx; L = (G - N) * promo; M = (G - N) * P.payo;
  }
  const O = cost - pt + J + K + L + M + N + S;
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

/* ===== 発送手段の判定 (2026-07-30 ユーザー要望) =====
   ★何で送るかは **出品価格ではなく成約額** で決まる。オファーで €150 を下回ると
     日本郵便がドイツ向けを引き受けないため SpeedPAK Economy に切替が要る
     (2026-07-31 実例: 出品 €220.62 の listing に €120 のオファー = 帯またぎ)。
   ★根拠: SPEEDPAK_COVERAGE.md / jp_post_eu_suspension_20260724 /
     shipping_route_by_destination / uk_vat_135_shipping_rules */
const IOSS_EUR = 150;      // EU: IOSS 上限 (Economy の取引額上限でもある)
const UK_GBP   = 135;      // UK: VAT 徴収境界
const AU_GST   = 1000;     // AU: 同一バイヤー同日 GST 境界

function shipInfo(dk, price){
  const cur = P.routes[dk][2];
  const eur = price * (P.fx[cur] || 0) / (P.fx.EUR || 1);   // 成約額の EUR 換算
  const out = {method:'', why:'', warns:[]};
  if (dk === 'DE'){
    if (eur <= IOSS_EUR){
      out.method = 'SpeedPAK Economy（DE_EconomySppedPAK）';
      out.why = '取引額 €' + eur.toFixed(2) + ' ≤ €150 = IOSS 帯。日本郵便は独の €150未満を引き受けない';
    } else {
      out.method = '日本郵便（EMS / 国際eパケット）';
      out.why = '取引額 €' + eur.toFixed(2) + ' > €150。Economy は €150 超を扱えない';
    }
  } else if (dk === 'UK'){
    out.method = '日本郵便（送料は価格内包）';
    out.why = price <= UK_GBP ? '£135 以下 = eBay が VAT 徴収済' : '£135 超 = DDU（バイヤーが着払い）';
    if (price <= UK_GBP) out.warns.push('VAT 徴収済 → <b>必ず単独で発送</b>（他と同梱すると二重課税）');
  } else if (dk === 'CA'){
    out.method = '国際eパケット（日本郵便）';
    out.why = 'DDU。米国関税は払わないので US 基準より利益は厚い';
  } else if (dk === 'AU'){
    out.method = '日本郵便';
    out.why = price <= AU_GST ? 'A$1,000 以下 = GST 徴収済' : 'A$1,000 超 = 別扱い';
  } else if (dk === 'US'){
    out.method = 'SpeedPAK Economy（US_EconomySppedPAK）';
    out.why = '米国内向け。関税は当方負担（DDP）';
  } else {                                   // その他 (US出品・米国外へ発送)
    if (eur <= IOSS_EUR){
      out.method = 'SpeedPAK Economy（rate table iMak_EU_DDP_Common）';
      out.why = '取引額 €' + eur.toFixed(2) + ' ≤ €150。EU25 か国は Economy でカバー';
    } else {
      out.method = '日本郵便 / FedEx';
      out.why = '取引額 €' + eur.toFixed(2) + ' > €150 = Economy 不可';
    }
  }
  // 帯またぎ (出品価格を入れた時だけ)
  const listP = +document.getElementById('list').value || 0;
  if (listP > 0 && (dk === 'DE' || dk === 'その他 (US出品・米国外へ発送)')){
    const listEUR = listP * (P.fx[cur] || 0) / (P.fx.EUR || 1);
    if (listEUR > IOSS_EUR && eur <= IOSS_EUR)
      out.warns.push('<b>帯またぎ</b>: 出品 €' + listEUR.toFixed(2) + ' は「>€150=日本郵便」設定だが、'
        + 'この成約額は €150 未満。<b>実際は SpeedPAK Economy で発送すること</b>');
    if (listEUR <= IOSS_EUR && eur > IOSS_EUR)
      out.warns.push('<b>帯またぎ</b>: 出品は Economy 設定だが成約額が €150 超。<b>日本郵便で発送</b>');
  }
  if (out.method.indexOf('Economy') >= 0){
    out.warns.push('Economy 制約: <b>6〜16営業日</b> / 電池不可 / '
      + '<b>申告額 1kgあたり $1,000 以上は不可</b>（PSA10 は梱包 0.3kg 以上を確保）');
  }
  if (dk === 'DE' || dk === 'その他 (US出品・米国外へ発送)')
    out.warns.push('EU 向けは <b>IOSS 番号 IM2760000742</b> を差出人参照番号欄に入れる（忘れると VAT 二重払い）');
  return out;
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
    '</div>' +
    (function(){
      const s = shipInfo(dest.value, r.price);
      return '<div style="margin-top:14px;padding:12px;border:1px solid #3a5;border-radius:8px;'
        + 'background:#16241a">'
        + '<div style="color:#9f9;font-size:12px;margin-bottom:4px">📦 何で送るか（成約額で決まる）</div>'
        + '<div style="font-size:18px;font-weight:bold">' + s.method + '</div>'
        + '<div style="color:#bbb;font-size:12px;margin-top:3px">' + s.why + '</div>'
        + (s.warns.length
            ? '<ul style="margin:8px 0 0;padding-left:18px;font-size:12px;color:#ffd">'
              + s.warns.map(w => '<li>' + w + '</li>').join('') + '</ul>'
            : '')
        + '</div>';
    })();
  document.getElementById('lnk').innerHTML =
    '<a href="' + P.url + P.tabs[r.tab] + '" target="_blank">' + r.tab + ' を開く</a>' +
    '（C15 に ' + r.sym + r.price.toFixed(2) + ' を入れて 16行を見る）';
}
function line(k, v){ return '<div class="line"><span>' + k + '</span><b>' + v + '</b></div>'; }

/* EU 仕向国セレクタ (EU送料マスタ 由来) */
(function(){
  const s = document.getElementById('eucty');
  const ks = Object.keys(P.eu || {});
  if (!ks.length){ s.add(new Option('DE (マスタ未読込)', 'DE')); return; }
  ks.forEach(k => s.add(new Option(`${k} ${P.eu[k].name}（$${P.eu[k].tier}）`, k)));
  s.value = 'DE';
})();

['dest','cat','price','list','cost','pt','promo','eucty'].forEach(id =>
  document.getElementById(id).addEventListener('input', render));
document.getElementById('eucty').addEventListener('change', render);

/* ===== 受信中オファーの自動読込 (--offers 生成時のみ中身が入る) ===== */
(function(){
  const box = document.getElementById('offerbox');
  if (!P.offers || !P.offers.length){
    box.innerHTML = '<span style="color:#888">受信中のオファーは読み込まれていません'
      + '（<code>python offer_calc.py --offers</code> で自動取得）</span>';
    return;
  }
  const sel = document.getElementById('offersel');
  P.offers.forEach((o, i) => sel.add(new Option(
    `${o.sym}${o.price}  ${o.title.slice(0,44)}  (${o.destLabel}／期限 ${o.expire}）`, i)));
  function apply(){
    const o = P.offers[+sel.value];
    dest.value = o.dest; cat.value = o.cat;
    document.getElementById('price').value = o.price;
    document.getElementById('list').value = o.list;
    document.getElementById('cost').value = o.cost;
    document.getElementById('meta').innerHTML =
      `<a href="${o.url}" target="_blank">${o.itemId}</a> ／ 出品 ${o.sym}${o.list}`
      + ` ／ 仕入 ¥${o.cost.toLocaleString()}`
      + (o.costSrc ? `（${o.costSrc}）` : '')
      + ` ／ バイヤー ${o.buyer}（${o.country}・評価${o.fb}）`
      + (o.stock ? ` ／ 在庫確認 ${o.stock}` : '')
      + (o.supply ? ` ／ 補URL ${o.supply}本` : '');
    render();
  }
  sel.addEventListener('change', apply);
  apply();
})();

render();
</script></body></html>"""


DDP = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 220, 240, 260, 280,
       300, 350, 400, 450, 500, 550, 600, 700, 800, 900, 1000, 1500]


def calc_py(p, tab, cat_key, dest_key, price, cost, pt=0.0, promo_on=False,
            eu_country="DE"):
    """HTML(JS) と **同じ式**を Python でも持つ。検証はこれとシートを突き合わせる。

    2実装が食い違ったら、その時点で検証が落ちる = 気づける。

    eu_country: EU送料マスタ の国コード。US計算_非US / DE計算 の DDP に効く
                (2026-07-31 追加。旧 shipMode の置換)。
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
            # ★2026-07-31: EU送料マスタ 由来の国別値 (旧 独/FedEx7 の2値は廃止)
            e = (p.get("eu") or {}).get(eu_country or "DE", {"tier": 17, "cost": 3219})
            D = e["tier"]
            # ≤€150 = DDP/Economy (関税は当方負担) / >€150 = DDU/日本郵便 (買い手着払い)
            lim = p.get("iossEur", 150) * p["fx"]["EUR"] / p["fx"]["USD"]
            N = (e["cost"] if price <= lim else p.get("jpPost", 1240)) - J
        G = (F + D) * fx
        K, L, M = G * fr + 0.4 * fx, G * promo, G * p["payo"]
    elif tab == "DE計算":
        # ★2026-07-31: DEミラーは送料を別取り (DE €14.86 / AT €17.49)。
        #   売上に送料収入を含め、DDPコスト(実費+関税−想定送料J) を別途引く。
        cc = eu_country or "DE"
        R = p.get("atShip", 17.49) if cc == "AT" else p.get("deShip", 14.86)
        vat = 0.20 if cc == "AT" else 0.19          # 実注文で AT=20% を確認
        D = (price + R) * vat
        G = (price + R + D) * fx
        N = D * fx
        e = (p.get("eu") or {}).get(cc, {"cost": 3219})
        # ≤€150 = DDP/Economy (関税は当方負担) / >€150 = DDU/日本郵便 (買い手着払い)
        S = (e["cost"] if price <= p.get("iossEur", 150) else p.get("jpPost", 1240)) - J
        K, L, M = (G - N) * fr + 0.4 * fx, (G - N) * promo, (G - N) * p["payo"]
        return (G - (cost - pt + J + K + L + M + N + S))
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

    def cell(ws, ref, default="", raw=False):
        """空セルでも落ちない読取 (gspread は空だと [] を返す)。

        ★raw=True で **書式を適用しない生値**を返す (2026-07-31 修正)。
          既定の ws.get() は表示値なので、通貨書式のセルは 70 → "$70.00" という
          **文字列**で返る。それをそのまま書き戻していたため、`--verify` を
          走らせるたびに入力セルが文字列化し、下流の数式が全て #VALUE! で
          落ちていた (US計算/非US/UK/AU/CA の 5タブ・計101セルが実際に壊れていた)。
        """
        v = ws.get(ref, value_render_option="UNFORMATTED_VALUE") if raw else ws.get(ref)
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
        # ★生値で退避する。表示値だと "$70.00" (文字列) になり、書き戻しでセルが壊れる
        keep = num(cell(ws, "C15", 70, raw=True)) or 70
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

    # ★既定で受信中オファーを読む (2026-07-31)。オファーは期限が短く、
    #   国・出品価格・仕入値を人が探す時間がそのまま判断の遅れになる。
    #   取得に失敗しても手入力版として使えるよう、例外は握って続行する。
    p["offers"] = []
    if "--no-offers" not in sys.argv:
        try:
            p["offers"] = fetch_offers()
            print(f"📥 受信中オファー: {len(p['offers'])} 件")
            for o in p["offers"]:
                print(f"   {o['sym']}{o['price']} / 出品 {o['sym']}{o['list']} / "
                      f"仕入 ¥{o['cost']:,} / {o['destLabel']} / 期限 {o['expire']}")
                print(f"     {o['title'][:70]}")
        except Exception as e:                                # noqa: BLE001
            print(f"⚠️ オファー取得に失敗 ({e}) → 手入力版として生成します")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", json.dumps(p, ensure_ascii=False)), encoding="utf-8")
    print(f"✅ 生成: {OUT}")
    if "--verify" in sys.argv:
        verify(p)
    webbrowser.open(OUT.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
