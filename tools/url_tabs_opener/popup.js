// コピーした文字から URL を全部拾って、順番どおりに新しいタブで開く (Pasty と同じ動き)。
function urlsIn(text) {
  const found = (text || "").match(/https?:\/\/[^\s"'<>]+/g) || [];
  return found.map(u => u.replace(/[),.;]+$/, ""));
}

function openAll(urls) {
  urls.forEach((u, i) => chrome.tabs.create({ url: u, active: i === 0 }));
}

function showBox(msg) {
  document.getElementById("msg").textContent = msg;
  document.getElementById("box").style.display = "block";
  document.getElementById("go").style.display = "inline-block";
  document.getElementById("box").focus();
}

document.getElementById("go").addEventListener("click", () => {
  const urls = urlsIn(document.getElementById("box").value);
  if (!urls.length) { document.getElementById("msg").textContent = "URL が見つかりません"; return; }
  openAll(urls);
  window.close();
});

(async () => {
  let text = "";
  try {
    text = await navigator.clipboard.readText();
  } catch (e) {
    showBox("クリップボードを読めませんでした。下に貼り付けてください。");
    return;
  }
  const urls = urlsIn(text);
  if (!urls.length) { showBox("コピーした中に URL がありません。下に貼り付けることもできます。"); return; }
  openAll(urls);
  window.close();
})();
