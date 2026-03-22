#!/bin/bash
set -e
HTML=/workspace/scraper-api/scraper.html
BAK=$HTML.bak_$(date +%Y%m%d_%H%M%S)
cp $HTML $BAK
echo "Backup : $BAK"

# ── 1. Ajouter bouton btnDeep après btnAuto ───────────────────────────────────
python3 -c "
path='/workspace/scraper-api/scraper.html'
txt=open(path).read()
if 'btnDeep' in txt:
    print('btnDeep deja present, skip')
elif 'id=\"btnAuto\"' not in txt:
    print('ERREUR ancre btnAuto introuvable'); exit(1)
else:
    old=txt[txt.find('id=\"btnAuto\"')-20:txt.find('id=\"btnAuto\"')+200]
    old=old[old.find('<button'):]
    old=old[:old.find('</button>')+9]
    new=old+'\n    <button class=\"btn-gray\" id=\"btnDeep\" onclick=\"showDeepPanel()\" style=\"display:none\">🔗 Deep</button>'
    open(path,'w').write(txt.replace(old,new,1))
    print('btnDeep OK')
"

# ── 2. Afficher btnDeep dans scrape() après btnAuto ───────────────────────────
python3 - <<'PYEOF'
path = "/workspace/scraper-api/scraper.html"
txt  = open(path).read()
old  = "$('btnAuto').style.display='';"
new  = "$('btnAuto').style.display='';\n    $('btnDeep').style.display='';"
if "$('btnDeep').style.display" in txt:
    print("display btnDeep déjà présent, skip")
elif old not in txt:
    print("ERREUR : ancre display btnAuto introuvable")
    raise SystemExit(1)
else:
    open(path,"w").write(txt.replace(old, new, 1))
    print("display btnDeep OK")
PYEOF

# ── 3. Injecter modal Deep Scrape + JS avant </body> ─────────────────────────
python3 - <<'PYEOF'
path = "/workspace/scraper-api/scraper.html"
txt  = open(path).read()

if "deepModal" in txt:
    print("deepModal déjà présent, skip")
    raise SystemExit(0)

INJECT = """
<!-- ═══════════════════════════════ DEEP SCRAPE ════════════════════════════ -->
<style>
#deepModal{display:none;position:fixed;inset:0;background:#0009;z-index:200;overflow-y:auto;padding:16px}
#deepBox{background:#1e293b;border:1px solid #0e7490;border-radius:12px;padding:18px;max-width:600px;margin:auto}
#deepBox h2{font-size:14px;color:#7dd3fc;margin-bottom:14px}
.drow{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.drow label{font-size:10px;color:#64748b;min-width:90px}
.drow input{flex:1;background:#0f1117;border:1px solid #334155;border-radius:6px;color:#e2e8f0;padding:6px 10px;font-size:12px;font-family:monospace;outline:none}
.drow input:focus{border-color:#0e7490}
.dhint{font-size:9px;color:#475569;padding-left:98px;margin-top:-5px;margin-bottom:4px}
#deepBarWrap{background:#0f1117;border-radius:4px;overflow:hidden;margin-bottom:6px;height:8px}
#deepBar{height:8px;background:#0e7490;border-radius:4px;width:0%;transition:width .3s}
#deepLog{font-size:10px;color:#64748b;max-height:80px;overflow-y:auto;font-family:monospace}
#deepResults{margin-top:12px;max-height:320px;overflow-y:auto}
.ditem{background:#0f1117;border-radius:8px;padding:10px;margin-bottom:8px;display:flex;gap:10px}
.ditem img{width:70px;height:50px;object-fit:cover;border-radius:5px;flex-shrink:0}
.ditem .dinfo{flex:1;min-width:0}
.ditem .dtitle{font-size:12px;color:#e2e8f0;font-weight:600;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ditem .dprice{font-size:12px;color:#4ade80;margin-bottom:2px}
.ditem .ddesc{font-size:10px;color:#64748b;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.ditem .dlink{font-size:10px;color:#38bdf8;word-break:break-all;margin-top:2px}
</style>

<div id="deepModal">
  <div id="deepBox">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <h2>🔗 Deep Scrape — Listing + Détails</h2>
      <button onclick="document.getElementById('deepModal').style.display='none'"
        style="background:none;border:none;color:#64748b;font-size:18px;cursor:pointer">✕</button>
    </div>

    <div class="drow"><label>URL listing</label><input id="ds_url" placeholder="https://site.com/annonces"></div>
    <div class="drow"><label>Sél. items</label><input id="ds_items" placeholder="div.odd / article.listing / li.property"></div>
    <div class="dhint">Sélecteur CSS des blocs annonces sur la page listing</div>
    <div class="drow"><label>Sél. lien</label><input id="ds_links" value="a" placeholder="a / a.title-link"></div>
    <div class="dhint">Sélecteur du lien DANS chaque bloc (premier match)</div>

    <hr style="border-color:#334155;margin:10px 0">
    <div style="font-size:10px;color:#64748b;margin-bottom:8px">Page détail — laisser vide = heuristique auto</div>
    <div class="drow"><label>Sél. titre</label><input id="ds_title" placeholder="h1.title / .annonce-titre"></div>
    <div class="drow"><label>Sél. desc.</label><input id="ds_desc" placeholder=".description / .texte-annonce"></div>
    <div class="drow"><label>Sél. prix</label><input id="ds_price" placeholder=".price / .loyer"></div>
    <div class="drow"><label>Sél. images</label><input id="ds_imgs" placeholder=".slider img / .photos img"></div>

    <hr style="border-color:#334155;margin:10px 0">
    <div class="drow">
      <label>Max annonces</label><input id="ds_max" type="number" value="20" style="max-width:70px">
      <label style="min-width:60px">Délai ms</label><input id="ds_delay" type="number" value="1000" style="max-width:70px">
      <label style="min-width:60px">JS wait</label><input id="ds_js" type="number" value="2000" style="max-width:70px">
    </div>
    <div class="drow">
      <label>same_domain</label>
      <input type="checkbox" id="ds_same" checked style="width:auto;flex:none">
      <span style="font-size:10px;color:#64748b">Filtrer hors-domaine</span>
    </div>
    <div class="drow"><label>Sauvegarder</label><input id="ds_outfile" placeholder="/workspace/scraper-api/output.json (optionnel)"></div>

    <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
      <button id="btnRunDeep" onclick="runDeepScrape()"
        style="padding:9px 20px;background:#0e7490;border:none;border-radius:7px;color:#fff;cursor:pointer;font-size:13px;font-weight:700">
        🔗 Lancer</button>
      <button id="btnDeepExport" onclick="exportDeepJSON()" style="display:none;padding:9px 16px;background:#15803d;border:none;border-radius:7px;color:#fff;cursor:pointer;font-size:12px">⬇ JSON</button>
      <button id="btnDeepCSV" onclick="exportDeepCSV()" style="display:none;padding:9px 16px;background:#334155;border:none;border-radius:7px;color:#fff;cursor:pointer;font-size:12px">⬇ CSV</button>
    </div>

    <div id="deepProgress" style="display:none;margin-top:10px">
      <div id="deepBarWrap"><div id="deepBar"></div></div>
      <div id="deepLog"></div>
    </div>
    <div id="deepResults"></div>
  </div>
</div>

<script>
var _deepData=null;

function showDeepPanel(){
  var u=document.getElementById('urlInput').value.trim();
  if(u) document.getElementById('ds_url').value=u;
  if(window._autoResults&&window._autoResults.length)
    document.getElementById('ds_items').value=window._autoResults[0].selector;
  document.getElementById('deepModal').style.display='block';
}

function _deepLog(msg){
  var el=document.getElementById('deepLog');
  el.innerHTML+=msg+'<br>'; el.scrollTop=el.scrollHeight;
}

function _desc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

async function runDeepScrape(){
  var btn=document.getElementById('btnRunDeep');
  var apiBase=document.getElementById('apiBase').value;
  var body={
    url:        document.getElementById('ds_url').value.trim(),
    sel_items:  document.getElementById('ds_items').value.trim(),
    sel_links:  document.getElementById('ds_links').value.trim()||'a',
    sel_title:  document.getElementById('ds_title').value.trim(),
    sel_desc:   document.getElementById('ds_desc').value.trim(),
    sel_price:  document.getElementById('ds_price').value.trim(),
    sel_imgs:   document.getElementById('ds_imgs').value.trim(),
    max_items:  parseInt(document.getElementById('ds_max').value)||20,
    delay_ms:   parseInt(document.getElementById('ds_delay').value)||1000,
    js_wait:    parseInt(document.getElementById('ds_js').value)||2000,
    same_domain:document.getElementById('ds_same').checked,
    output_file:document.getElementById('ds_outfile').value.trim()
  };
  if(!body.url){alert('URL listing manquante');return;}
  btn.disabled=true; btn.textContent='⏳ En cours…';
  document.getElementById('deepProgress').style.display='block';
  document.getElementById('deepLog').innerHTML='';
  document.getElementById('deepBar').style.width='5%';
  document.getElementById('deepResults').innerHTML='';
  document.getElementById('btnDeepExport').style.display='none';
  document.getElementById('btnDeepCSV').style.display='none';
  _deepData=null;
  _deepLog('⏳ Listing : '+body.url);
  var prog=5;
  var total_ms=(body.max_items*body.delay_ms+body.js_wait*2);
  var progTimer=setInterval(function(){
    prog=Math.min(prog+2,85);
    document.getElementById('deepBar').style.width=prog+'%';
  }, total_ms/40);
  try{
    var res=await fetch(apiBase+'/deepscrape',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    var data=await res.json();
    clearInterval(progTimer);
    if(data.error){_deepLog('❌ '+data.error);return;}
    _deepData=data;
    document.getElementById('deepBar').style.width='100%';
    _deepLog('✅ '+data._meta.total+' annonces · '+data._meta.errors+' erreurs · '+data._meta.scraped_at);
    if(data._saved_to) _deepLog('💾 '+data._saved_to);
    _renderDeepResults(data.items);
    document.getElementById('btnDeepExport').style.display='';
    document.getElementById('btnDeepCSV').style.display='';
  }catch(e){
    clearInterval(progTimer);
    _deepLog('❌ '+e.message);
  }finally{
    btn.disabled=false; btn.textContent='🔗 Lancer';
  }
}

function _renderDeepResults(items){
  var el=document.getElementById('deepResults');
  if(!items.length){el.innerHTML='<div style="font-size:11px;color:#475569;padding:10px">Aucun résultat.</div>';return;}
  el.innerHTML='<div style="font-size:10px;color:#64748b;margin-bottom:8px">'+items.length+' annonces</div>'+
    items.map(function(item){
      var img=item.images&&item.images.length?item.images[0].src:'';
      return '<div class="ditem">'+(img?'<img src="'+_desc(img)+'" onerror="this.style.display=\'none\'">':'')+
        '<div class="dinfo">'+
        '<div class="dtitle">'+_desc(item.title||'(sans titre)')+'</div>'+
        (item.price?'<div class="dprice">'+_desc(item.price)+'</div>':'')+
        '<div class="ddesc">'+_desc(item.description||'')+'</div>'+
        '<div class="dlink">'+_desc(item.url)+'</div>'+
        '</div></div>';
    }).join('');
}

function exportDeepJSON(){
  if(!_deepData)return;
  var blob=new Blob([JSON.stringify(_deepData,null,2)],{type:'application/json'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='deep_'+((_deepData._meta.scraped_at)||'').replace(/[\\s:]/g,'-')+'.json';
  a.click();
}

function exportDeepCSV(){
  if(!_deepData||!_deepData.items.length)return;
  var cols=['url','title','price','description','_scraped_at'];
  var rows=[cols.join(',')].concat(_deepData.items.map(function(it){
    return cols.map(function(c){return '"'+String(it[c]||'').replace(/"/g,'""')+'"';}).join(',');
  })).join('\\n');
  var blob=new Blob([rows],{type:'text/csv'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='deep_'+((_deepData._meta.scraped_at)||'').replace(/[\\s:]/g,'-')+'.csv';
  a.click();
}
</script>
<!-- ══════════════════════════════ END DEEP SCRAPE ══════════════════════════ -->
"""

txt = txt.replace("</body>", INJECT + "\n</body>", 1)
open(path,"w").write(txt)
print("deepModal injecté OK")
PYEOF

echo "Done. Reload : pkill -f 'python3 app.py'; cd /workspace/scraper-api && python3 app.py &"
