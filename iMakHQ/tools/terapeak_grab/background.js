// CSV を保存する係。
// ★content script から a.click() で落とすと、Chrome の「保存場所を確認する」設定が
//   オンの時に毎回「名前を付けて保存」の窓が出る。downloads API に saveAs:false で
//   渡すと、その設定に関わらず黙って保存される (2026-09-18 ユーザー要望)。
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "download") return;
  // 大きい CSV でも壊れないよう base64 で渡す (service worker では Blob URL が作れない)
  const url = "data:text/csv;charset=utf-8;base64," + msg.b64;
  chrome.downloads.download({ url, filename: msg.name, saveAs: false }, (id) => {
    sendResponse({ ok: !chrome.runtime.lastError, error: String(chrome.runtime.lastError || "") , id });
  });
  return true; // 非同期で返す
});
