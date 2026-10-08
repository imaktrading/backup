// メルカリの購入履歴を神風に渡す (2026-10-09)。
//
// ★ユーザー「メルカリ購入履歴_ログインし直す.bat を押すって、アナログ過ぎない？」→「単純に購入履歴を読み取ればいい」。
//   それまでは専用の Chrome で読んでいて、メルカリから別の端末に見えるため1日ほどでログインが切れていた。
//   いつも使っている Edge (ログインしたまま) の拡張が読む。
//
// 流れ: 注文の取り込み (order_purchase_sync) が購入履歴を #imak-buys 付きで Edge に開く →
//   ここが一覧の HTML を神風 (/api/mercari/purchases) に渡す → タブを閉じる。
//   ログインの画面に飛ばされた時は、神風に「ログインが要る」と知らせてタブは残す (その場でログインしてもらう)。
(() => {
  "use strict";
  const FLAG = "imakBuysAt";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const api = (path, body) => new Promise((res) => {
    try {
      chrome.runtime.sendMessage({ type: "api", method: "POST", path, body }, (r) => res(r || {}));
    } catch (e) { res({ ok: false }); }
  });

  async function onPurchases() {
    if (location.hash === "#imak-buys") {
      await chrome.storage.local.set({ [FLAG]: Date.now() });
      history.replaceState(null, "", location.pathname + location.search);
    }
    const { [FLAG]: at = 0 } = await chrome.storage.local.get(FLAG);
    if (!at || Date.now() - at > 15 * 60 * 1000) return;          // 神風が開いた時だけ動く
    for (let i = 0; i < 40; i++) {                                 // 一覧が出るまで (最大20秒)
      if (document.querySelector('a[href^="/transaction/"]')) break;
      await sleep(500);
    }
    await sleep(1000);
    const r = await api("/api/mercari/purchases", { html: document.documentElement.outerHTML });
    await chrome.storage.local.remove(FLAG);
    if (r && r.ok) chrome.runtime.sendMessage({ type: "close" });
  }

  async function onLogin() {
    const { [FLAG]: at = 0 } = await chrome.storage.local.get(FLAG);
    if (!at || Date.now() - at > 15 * 60 * 1000) return;
    await api("/api/mercari/purchases", { login_required: true });  // タブは閉じない (ここでログインしてもらう)
  }

  if (location.hostname === "login.jp.mercari.com") onLogin();
  else onPurchases();
})();
