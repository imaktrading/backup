// CPaSS のページ自身の中で動く小さな差し替え (2026-10-09)。
// 「SpeedPAKセラーポータルへ」→「確認」はポータルを新しい窓 (window.open) で開く作り。拡張から押すと
// ブラウザが新しい窓を止めるので、神風が #imak-ship 付きで開いた時だけ、同じタブでポータルへ移るようにする。
(() => {
  if (!/imak-ship/.test(location.hash)) return;
  const go = (u) => { if (u) location.assign(u); return window; };
  try { window.open = function (u) { return go(u); }; } catch (e) { /* noop */ }
})();
