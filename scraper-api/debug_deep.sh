#!/bin/bash
python3 -c "
path='/workspace/scraper-api/scraper.html'
txt=open(path).read()

# Injecte un overlay debug visible au tap sur le bouton Lancer
old='onclick=\"runDeepScrape()\"'
new='onclick=\"debugDeep()\"'
if old not in txt:
    print('ERREUR ancre btnRunDeep introuvable')
    exit(1)
txt=txt.replace(old,new,1)

# Injecte la fonction debugDeep + overlay avant </body>
inject='''
<div id=\"dbgOverlay\" style=\"display:none;position:fixed;inset:0;background:#000d;z-index:9999;padding:16px;overflow-y:auto\">
<div style=\"background:#1e293b;border:1px solid #0e7490;border-radius:10px;padding:14px;max-width:500px;margin:auto\">
<div style=\"display:flex;justify-content:space-between;margin-bottom:10px\">
<span style=\"color:#7dd3fc;font-size:13px;font-weight:700\">🐛 Debug Deep</span>
<button onclick=\"document.getElementById(chr(39)+'dbgOverlay'+chr(39)).style.display=chr(39)+'none'+chr(39)\" style=\"background:none;border:none;color:#64748b;font-size:18px;cursor:pointer\">x</button>
</div>
<pre id=\"dbgLog\" style=\"font-size:11px;color:#94a3b8;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow-y:auto\"></pre>
</div>
</div>
<script>
function dbgLog(msg){ var el=document.getElementById(\"dbgLog\"); el.textContent+=msg+\"\\n\"; el.scrollTop=el.scrollHeight; }
async function debugDeep(){
  document.getElementById(\"dbgOverlay\").style.display=\"block\";
  document.getElementById(\"dbgLog\").textContent=\"\";
  var apiBase=(document.getElementById(\"apiBase\").value.trim()||window.location.origin);
  dbgLog(\"apiBase: \"+apiBase);
  dbgLog(\"url: \"+document.getElementById(\"ds_url\").value);
  dbgLog(\"sel_items: \"+document.getElementById(\"ds_items\").value);
  dbgLog(\"window.origin: \"+window.location.origin);
  dbgLog(\"--- ping /health ---\");
  try{
    var r=await fetch(apiBase+\"/health\");
    dbgLog(\"status: \"+r.status);
    var j=await r.json();
    dbgLog(\"health: \"+JSON.stringify(j));
  }catch(e){ dbgLog(\"health ERROR: \"+e.message); }
  dbgLog(\"--- POST /deepscrape ---\");
  var body={
    url: document.getElementById(\"ds_url\").value.trim(),
    sel_items: document.getElementById(\"ds_items\").value.trim(),
    sel_links: document.getElementById(\"ds_links\").value.trim()||\"a\",
    max_items: 2, delay_ms: 500, js_wait: 2000
  };
  dbgLog(\"body: \"+JSON.stringify(body));
  try{
    var res=await fetch(apiBase+\"/deepscrape\",{
      method:\"POST\",headers:{\"Content-Type\":\"application/json\"},
      body:JSON.stringify(body)
    });
    dbgLog(\"status: \"+res.status);
    var txt=await res.text();
    dbgLog(\"response (500c): \"+txt.slice(0,500));
  }catch(e){ dbgLog(\"fetch ERROR: \"+e.message); }
}
</script>
'''
txt=txt.replace('</body>', inject+'</body>', 1)
open(path,'w').write(txt)
print('debug overlay OK')
"
