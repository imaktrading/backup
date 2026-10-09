// CPaSS (cpass.ebay.com) から SpeedPAK セラーポータルに入る (2026-10-09)。
//
// ★ユーザー「Cpass、ログイン切れたのでは？」: ポータル (ebay-jp.orangeconnex.com) を直接開くと、
//   ポータルのログインが切れていることがある。ポータルは CPaSS から入る作り
//   (⚙設定 → 配送業者設定 → 「SpeedPAKセラーポータルへ」→「確認」) なので、毎回ここから入る。
//   CPaSS は eBay のログインのまま。入った先のポータルで cpass_fees.js が明細を読む (同じ印 imakShipAt を見る)。
(() => {
  "use strict";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const visible = (el) => !!(el && (el.offsetParent || el.getClientRects().length));

  async function run() {
    let at = 0;
    for (let i = 0; i < 10 && !at; i++) {
      ({ imakShipAt: at = 0 } = await chrome.storage.local.get("imakShipAt"));
      if (!at) await sleep(300);
    }
    if (!at || Date.now() - at > 15 * 60 * 1000) return;
    let link = null;
    for (let i = 0; i < 40 && !link; i++) {
      link = [...document.querySelectorAll("a, span, button")].filter(visible).find((e) => /SpeedPAKセラーポータルへ/.test(txt(e)));
      if (!link) await sleep(500);
    }
    const api = (path, body) => new Promise((res) => {
      try { chrome.runtime.sendMessage({ type: "api", method: "POST", path, body }, (r) => res(r || {})); }
      catch (e) { res({}); }
    });
    if (!link) {                                               // ログインの画面などに飛ばされた (eBay のログインが要る)
      await api("/api/cpass/fees", { fees: {}, debug: { stage: "CPaSS に入口が無い", url: location.href,
        text: (document.body ? document.body.innerText : "").replace(/\s+/g, " ").slice(0, 800) } });
      return;
    }
    // <a href> ならそのまま同じタブで移る (新しい窓を開かない)
    const href = link.closest("a") && link.closest("a").getAttribute("href");
    if (href && /^https?:/.test(href)) { location.assign(href); return; }
    link.click();
    let ok = null;
    for (let i = 0; i < 20 && !ok; i++) {
      ok = [...document.querySelectorAll("button, a")].filter(visible).find((e) => /^(確認|OK|Confirm)$/i.test(txt(e).replace(/\s+/g, "")));   // 画面の文字は「確 認」(空白入り)
      if (!ok) await sleep(500);
    }
    if (ok) ok.click();
    await sleep(8000);                                         // ポータルが別のタブで開いたら、こちらは閉じる
    if (location.hostname === "cpass.ebay.com") chrome.runtime.sendMessage({ type: "close" });
  }

  run();
})();
