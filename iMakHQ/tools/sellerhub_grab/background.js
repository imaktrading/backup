// 経過の記録とタブ閉じ (2026-09-26)。
// 起動は出品くん Console (1日1回): Downloads を #shg-auto 付きでEdge で開く (2026-10-05 Chrome から Edge へ)。
// あとは content.js が作成 → 完成待ち → 取得 → 品質レポートまで進め、"done" を送ってくる。
// 経過は ダウンロード フォルダの sellerhub_grab_log.txt に書く (うまく行かなかった時に読む)。

// ★Service worker は待ち時間中に止まるので、経過は変数でなく storage に貯める
async function addLine(t) {
  const { shgLines = [] } = await chrome.storage.local.get("shgLines");
  shgLines.push(t);
  await chrome.storage.local.set({ shgLines: shgLines.slice(-300) });
}

async function writeLog() {
  const { shgLines = [] } = await chrome.storage.local.get("shgLines");
  const b64 = btoa(unescape(encodeURIComponent(shgLines.join("\r\n") + "\r\n")));
  chrome.downloads.download({
    url: "data:text/plain;charset=utf-8;base64," + b64,
    filename: "sellerhub_grab_log.txt", conflictAction: "overwrite", saveAs: false,
  });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg) return;
  if (msg.type === "start") {
    chrome.storage.local.set({ shgLines: [`${new Date().toLocaleString()} 自動 開始`] });
  } else if (msg.type === "log") {
    addLine(`${new Date().toLocaleTimeString()} ${msg.msg}`);
  } else if (msg.type === "dump") {
    // ★2026-10-04 トラフィックの画面の作りを控える (HQ が押す所を作るため)
    const b64 = btoa(unescape(encodeURIComponent(msg.text || "")));
    chrome.downloads.download({
      url: "data:text/plain;charset=utf-8;base64," + b64,
      filename: `${msg.name || "sellerhub_traffic_dump"}_${msg.n || 1}.txt`, conflictAction: "overwrite", saveAs: false,
    });
  } else if (msg.type === "done") {
    addLine(`${new Date().toLocaleString()} 終了 (${msg.ok ? "成功" : "失敗"})`).then(writeLog);
    if (sender.tab && sender.tab.id != null) setTimeout(() => chrome.tabs.remove(sender.tab.id), 5000);
  }
});
