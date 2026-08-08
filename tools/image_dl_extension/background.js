// 商品画像ダウンローダー — アイコンクリックで現在ページの商品画像を一括DL。
// Shopify(/products/<handle>.json)の高解像度を優先、無ければ表示中 <img> を収集。

// ページ内で実行され、画像URL一覧を返す(async)。
async function collectImages() {
  const out = { handle: "", urls: [] };
  const seen = new Set();
  const add = (u) => { if (u && /^https?:\/\//.test(u)) seen.add(u.split("?")[0]); };

  // 0) graniph: 商品画像だけを **URL 構造で** 特定する (2026-08-08 実測)。
  //    https://cf.graniph.com/images/item/product_image/<9桁品番>.<3桁カラー>.-_<n>.jpg
  //    ページ URL /item-detail/019002010001 = 品番 019002010 + カラー 001。
  //    ★汎用フォールバックに任せると **クーポンバナー / フィード画像も落ちる**
  //      (実測: 商品10枚 + バナー2枚)。品番+カラー一致に絞れば混入しない。
  //    ★原寸は 1125x1575。_l / _org / product_image_l / ?width=2000 は全部 403 なので
  //      「もっと大きいのがあるはず」と探しに行かない (実測済み)。
  if (/(^|\.)graniph\.com$/.test(location.hostname)) {
    const g = location.pathname.match(/\/item-detail\/(\d{9})(\d{3})/);
    if (g) {
      const code = `${g[1]}.${g[2]}`;
      // GRANIPH_PATTERN (テストが同じ正規表現を読む。書式を変えたら test も落ちる)
      const re = new RegExp("https?://[^\"'\\s<>)\\\\]*?/images/item/product_image/"
                            + code.replace(".", "\\.") + "\\.-_(\\d+)\\.(?:jpe?g|png|webp|avif)", "gi");
      const html = document.documentElement.innerHTML;
      const hit = new Map();                       // 連番 → URL (重複排除 + 並べ替え用)
      let m3;
      while ((m3 = re.exec(html)) !== null) hit.set(Number(m3[1]), m3[0].split("?")[0]);
      if (hit.size) {
        out.handle = `graniph_${g[1]}${g[2]}`;
        out.urls = [...hit.keys()].sort((a, b) => a - b).map((k) => hit.get(k));
        return out;
      }
      // 1枚も取れなかったら **落とさない**。バナーだけ掴んで「取れた」と誤解するより、
      // 0件で赤バッジを出して人に気づかせる (fail-closed)。
      return out;
    }
  }

  // 1) Shopify 商品ページ: 公開JSON(右クリ禁止に無関係)。
  //    images + media + 説明文(body_html)埋め込み画像 を全部拾う。
  const m = location.pathname.match(/\/products\/([^/?#]+)/);
  if (m) {
    try {
      const r = await fetch(`${location.origin}/products/${m[1]}.json`, { credentials: "omit" });
      if (r.ok) {
        const p = (await r.json()).product || {};
        (p.images || []).forEach((i) => add(i.src));
        (p.media || []).forEach((md) => add(md.src || (md.preview_image && md.preview_image.src)));
        ((p.body_html || "").match(/https?:\/\/[^"'> )]+\.(?:jpe?g|png|webp|gif|avif)/gi) || []).forEach(add);
        if (seen.size) { out.handle = m[1]; out.urls = [...seen]; return out; }
      }
    } catch (e) { /* fallback へ */ }
  }

  // 2) フォールバック: 表示中 + 遅延読込(lazy)+ srcset最大 + 背景画像。
  const attrs = ["src", "data-src", "data-original", "data-lazy-src", "data-lazy",
                 "data-zoom-image", "data-large_image", "data-image", "data-flickity-lazyload"];
  document.querySelectorAll("img, [data-src], [data-original], [data-zoom-image], source").forEach((el) => {
    attrs.forEach((a) => { const v = el.getAttribute && el.getAttribute(a); if (v) add(v); });
    if (el.currentSrc) add(el.currentSrc);
    const ss = el.getAttribute && el.getAttribute("srcset");
    if (ss) { const c = ss.split(",").map((s) => s.trim().split(/\s+/)[0]).filter(Boolean); if (c.length) add(c[c.length - 1]); }
  });
  document.querySelectorAll("*").forEach((el) => {
    const bg = getComputedStyle(el).backgroundImage;
    const mm = bg && bg.match(/url\(["']?(https?:\/\/[^"')]+)/);
    if (mm) add(mm[1]);
  });
  out.urls = [...seen];
  return out;
}

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !/^https?:/.test(tab.url || "")) return;
  let result;
  try {
    [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectImages,
    });
  } catch (e) {
    badge("ERR", "#c00");
    return;
  }
  const urls = (result && result.urls) || [];
  if (!urls.length) { badge("0", "#c00"); return; }

  const stamp = new Date().toISOString().slice(0, 10);
  const folder = result.handle ? `images_${result.handle}` : `images_${stamp}_${tab.id}`;
  let i = 0;
  for (const u of urls) {
    i++;
    const ext = (u.match(/\.(jpe?g|png|webp|gif|avif)$/i) || [])[1] || "jpg";
    const name = `${folder}/${String(i).padStart(2, "0")}.${ext}`;
    chrome.downloads.download({ url: u, filename: name, conflictAction: "uniquify" });
  }
  badge(String(urls.length), "#0a0");
});

function badge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
}
