# -*- coding: utf-8 -*-
"""目視HTML 共通の「現物 | 候補」並列拡大(虫眼鏡) — 2026-07-28.

psa_resource_confirm で入れて有効だったので、他の目視ビューアにも同じ物を出す。
目視の目的は**見比べ**なので、拡大時こそ2枚が並んでいる必要がある(候補1枚を全画面にすると
比較できない、というのが初版の失敗)。

使い方:
    from viewer_zoom import ZOOM_CSS, ZOOM_JS, ZOOM_OVERLAY, zoom_button
    css = "...既存CSS..." + ZOOM_CSS
    html = ... + zoom_button(候補画像URL, 現物画像URL) + ...
    body末尾 = ZOOM_OVERLAY + f"<script>{ZOOM_JS}</script>"

設計上の注意:
- ボタンは <label> や クリック可能な親の中に置かれることがあるので、
  **preventDefault + stopPropagation 必須**(拡大しただけでチェックが外れる誤爆を防ぐ)。
- 現物URLが空なら候補ペインだけ出す(現物画像が無い行がある)。
"""
import html as _html

ZOOM_CSS = """
.zm{font-size:13px;padding:0 6px;border:1px solid #bbb;border-radius:3px;background:#fff;
    color:#333;cursor:zoom-in;line-height:1.6}
#zov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9999;
     align-items:center;justify-content:center;cursor:zoom-out;gap:16px}
#zov.on{display:flex}
#zov img{max-width:46vw;max-height:88vh;object-fit:contain;background:#fff;display:block}
#zref,#zcand{text-align:center}
#zov .zc{color:#fff;font-size:15px;font-weight:bold;margin-bottom:6px}
"""

ZOOM_JS = """
function zoom(ev,btn){ev.preventDefault(); ev.stopPropagation();
  var o=document.getElementById('zov');
  var L=o.querySelector('#zref'), R=o.querySelector('#zcand');
  var ref=btn.dataset.ref||'';
  if(ref){L.querySelector('img').src=ref; L.style.display='block';} else {L.style.display='none';}
  R.querySelector('img').src=btn.dataset.img;
  o.classList.add('on');}
function zclose(ev){ev.preventDefault(); document.getElementById('zov').classList.remove('on');}
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){var o=document.getElementById('zov'); if(o) o.classList.remove('on');}});
"""

ZOOM_OVERLAY = ("<div id='zov' onclick='zclose(event)'>"
                "<div id='zref'><div class='zc'>① 現物</div><img alt=''></div>"
                "<div id='zcand'><div class='zc'>候補</div><img alt=''></div></div>")


def zoom_button(cand_image, ref_image="", label="🔍"):
    """候補画像を現物と並べて拡大するボタン。候補画像が無ければ空文字(純関数)。"""
    if not cand_image:
        return ""
    return (f"<button type='button' class='zm' title='現物と並べて拡大' "
            f"data-img=\"{_html.escape(str(cand_image))}\" "
            f"data-ref=\"{_html.escape(str(ref_image or ''))}\" "
            f"onclick='zoom(event,this)'>{label}</button>")
