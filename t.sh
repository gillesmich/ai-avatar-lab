#!/bin/bash
APP="/workspace/wav2lip-onnx-HQ/app_streamingc.py"
HTML="/workspace/wav2lip-onnx-HQ/index.html"
cp "$APP"  "$APP.bak_radar2"
cp "$HTML" "$HTML.bak_radar2"

# ══════════════════════════════════════════════════════
# 1. Génère c21_catalog.json depuis le scrape
# ══════════════════════════════════════════════════════
SCRAPED=$(ls /workspace/wav2lip-onnx-HQ/catalogs/*.json 2>/dev/null | head -1)
if [ -z "$SCRAPED" ]; then
  echo "❌ Aucun fichier JSON dans catalogs/ — vérifie le chemin"
  exit 1
fi
echo "📂 Scrape source: $SCRAPED"

python3 - << PYEOF
import json, re
from pathlib import Path

raw = json.load(open("$SCRAPED", encoding="utf-8"))
items = raw.get("items", raw) if isinstance(raw, dict) else raw
catalog = []

IMG = {
    "Parking": "https://images.unsplash.com/photo-1590674899484-d5640e854abe?w=300&q=80",
    "Studio":  "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=300&q=80",
    "F2":      "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=300&q=80",
    "F3":      "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=300&q=80",
    "F4":      "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=300&q=80",
}

for item in items:
    text   = item.get("text", "")
    prices = item.get("prices", [])
    links  = item.get("links", [])

    ref_m = re.search(r"Ref\s*:\s*(\d+)", text)
    ref   = ref_m.group(1) if ref_m else ""

    loc_m    = re.search(r"(PARIS\s+\d{5})", text)
    ville    = loc_m.group(1).strip() if loc_m else "PARIS"
    arr_m    = re.search(r"75(\d{3})", ville)
    arr      = int(arr_m.group(1)) if arr_m else 0
    quartier = f"Paris {arr}ème" if arr > 1 else "Paris 1er"

    surf_m     = re.search(r"([\d,\.]+)\s*m\s*2", text)
    surface_s  = surf_m.group(1).replace(",",".") if surf_m else "0"
    surface_f  = float(surface_s)

    pieces_m = re.search(r"(\d+)\s*pièces?", text)
    rooms    = int(pieces_m.group(1)) if pieces_m else (1 if surface_f < 20 else 0)

    if re.search(r"parking|box|emplacement", text, re.I):
        categorie = "Parking"
    elif re.search(r"studio", text, re.I):
        categorie = "Studio"
    elif rooms >= 4: categorie = "F4"
    elif rooms == 3: categorie = "F3"
    elif rooms == 2: categorie = "F2"
    else: categorie = "Appartement"

    price_str = ""
    if prices:
        p = prices[0].strip()
        price_str = re.sub(r"\s+"," ",p).strip()
        if "€" not in price_str: price_str += " €"
        price_str += "/mois"
    price_num_m = re.search(r"([\d\s\xa0]+)", price_str)
    price_num   = int(re.sub(r"[\s\xa0]","", price_num_m.group(1))) if price_num_m else 0

    pm2 = round(price_num / surface_f) if surface_f > 0 else 0

    floor_m = re.search(r"(\d+)[eè][rèm]+\s*(?:et\s*dernier\s*)?étage|(\d+)ème|(RDC|rez[- ]de[- ]chaussée)", text, re.I)
    if floor_m:
        if floor_m.group(3): floor = "RDC"
        else:
            n = floor_m.group(1) or floor_m.group(2)
            floor = f"{n}ème"
            if "dernier" in text[floor_m.start():floor_m.start()+30].lower():
                floor += " (dernier)"
    else: floor = "?"

    dpe_m = re.search(r"DPE\s*([A-G])|classe\s*([A-G])\b|DPE([A-G])", text, re.I)
    dpe   = next((g for g in (dpe_m.groups() if dpe_m else []) if g), "?")
    if dpe != "?": dpe = dpe.upper()

    # Extérieurs
    has_balcon  = bool(re.search(r"balcon", text, re.I))
    has_terasse = bool(re.search(r"terrasse|terasse", text, re.I))
    has_jardin  = bool(re.search(r"jardin", text, re.I))
    ext_score   = (40 if has_jardin else 0) + (30 if has_terasse else 0) + (20 if has_balcon else 0)
    ext_label   = " + ".join(filter(None,[
        "Jardin" if has_jardin else "",
        "Terrasse" if has_terasse else "",
        "Balcon" if has_balcon else ""
    ])) or "Aucun"

    rue_m = re.search(r"(?:RUE|AVENUE|BOULEVARD|IMPASSE|PLACE|ALLÉE)[^,\n\.]{3,35}", text, re.I)
    rue   = rue_m.group(0).strip().title() if rue_m else ""

    link = ""
    for l in links:
        if "detail" in l.get("href",""): link = l["href"]; break
    if not link and links: link = links[-1].get("href","")

    name = f"{categorie} — {quartier}"
    if rue: name += f" — {rue[:28]}"
    name += f" — Ref{ref}"

    desc = " ".join(text.split()[:50]) + "…"

    catalog.append({
        "ref": ref, "name": name, "categorie": categorie,
        "ville": ville, "quartier": quartier, "rue": rue,
        "surface": f"{surface_s} m²", "surface_m2": surface_f,
        "rooms": rooms, "floor": floor, "dpe": dpe,
        "price": price_str, "price_num": price_num, "price_m2": pm2,
        "balcon": has_balcon, "terasse": has_terasse, "jardin": has_jardin,
        "ext_score": ext_score, "ext_label": ext_label,
        "link": link,
        "image": IMG.get(categorie, IMG["F2"]),
        "description": desc,
    })

out = Path("/workspace/wav2lip-onnx-HQ/c21_catalog.json")
json.dump(catalog, open(out,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"✅ {len(catalog)} biens → {out}")
for b in catalog:
    print(f"  [{b['ref']}] {b['name']} | {b['surface']} | {b['price']} | DPE:{b['dpe']} | Ext:{b['ext_label']}")
PYEOF

# ══════════════════════════════════════════════════════
# 2. Met à jour /api/compare/immo : vrai catalogue
#    + critères extérieurs + fix find_bien
# ══════════════════════════════════════════════════════
python3 - << 'PYEOF'
import re
from pathlib import Path

path = Path("/workspace/wav2lip-onnx-HQ/app_streamingc.py")
src  = path.read_text()

old_route = src[src.find("@app.route(\"/api/compare/immo\")"):
                src.find("\n\n@app.route", src.find("@app.route(\"/api/compare/immo\")"))]

new_route = '''@app.route("/api/compare/immo")
def api_compare_immo():
    import json as _j, re as _ri
    from pathlib import Path as _P
    p1 = request.args.get("p1","").strip()
    p2 = request.args.get("p2","").strip()
    if not p1 or not p2:
        return jsonify({"ok": False, "error": "p1 et p2 requis"}), 400

    cat_path = _P(__file__).parent / "c21_catalog.json"
    catalog  = _j.load(open(cat_path)) if cat_path.exists() else []

    def find_bien(name):
        q = name.lower().strip()
        # 1. Correspondance exacte ref
        ref_m = _ri.search(r"ref(\d+)", q)
        if ref_m:
            for b in catalog:
                if b.get("ref") == ref_m.group(1): return b
        # 2. Correspondance nom
        for b in catalog:
            if q in b.get("name","").lower(): return b
        # 3. Tokens
        tokens = [t for t in q.split() if len(t) > 3]
        best, bscore = None, 0
        for b in catalog:
            sc = sum(1 for t in tokens if t in b.get("name","").lower())
            if sc > bscore: best, bscore = b, sc
        return best

    pa = find_bien(p1)
    pb = find_bien(p2)
    if not pa or not pb:
        return jsonify({"ok": False, "error": "Bien(s) introuvable(s) dans le catalogue"}), 404

    def score_surface(b):
        return min(int(b.get("surface_m2",0) * 100 // 120), 100)

    def score_prix(b, max_p):
        n = b.get("price_num", 0)
        return max(0, 100 - int(n * 100 / max_p)) if max_p else 50

    def score_dpe(b):
        return {"A":100,"B":85,"C":70,"D":55,"E":35,"F":20,"G":5}.get(
            str(b.get("dpe","?")).upper()[:1], 50)

    def score_rooms(b):
        return min(b.get("rooms",0) * 20, 100)

    def score_floor(b):
        f = str(b.get("floor","")).lower()
        if "rdc" in f or "rez" in f: return 25
        if "dernier" in f: return 95
        m = _ri.search(r"(\d+)", f)
        return min(int(m.group(1)) * 20, 90) if m else 50

    max_p = max(pa.get("price_num",0), pb.get("price_num",0), 1)

    specs = [
        {"label": "Surface",
         "a_val": pa.get("surface","?"),      "b_val": pb.get("surface","?"),
         "a_score": score_surface(pa),         "b_score": score_surface(pb)},
        {"label": "Loyer",
         "a_val": pa.get("price","?"),         "b_val": pb.get("price","?"),
         "a_score": score_prix(pa, max_p),     "b_score": score_prix(pb, max_p)},
        {"label": "DPE",
         "a_val": "DPE " + str(pa.get("dpe","?")), "b_val": "DPE " + str(pb.get("dpe","?")),
         "a_score": score_dpe(pa),             "b_score": score_dpe(pb)},
        {"label": "Pièces",
         "a_val": str(pa.get("rooms","?")) + " p.", "b_val": str(pb.get("rooms","?")) + " p.",
         "a_score": score_rooms(pa),           "b_score": score_rooms(pb)},
        {"label": "Étage",
         "a_val": pa.get("floor","?"),         "b_val": pb.get("floor","?"),
         "a_score": score_floor(pa),           "b_score": score_floor(pb)},
        {"label": "Extérieurs",
         "a_val": pa.get("ext_label","Aucun"), "b_val": pb.get("ext_label","Aucun"),
         "a_score": pa.get("ext_score", 0),    "b_score": pb.get("ext_score", 0)},
    ]

    total_a = sum(s["a_score"] for s in specs)
    total_b = sum(s["b_score"] for s in specs)
    if total_a > total_b:   verdict = pa["name"][:40] + " présente le meilleur rapport global."
    elif total_b > total_a: verdict = pb["name"][:40] + " présente le meilleur rapport global."
    else:                   verdict = "Les deux biens sont équivalents."

    return jsonify({
        "ok": True, "mode": "immo",
        "product_a": {"name": pa["name"], "price": pa.get("price",""),
                      "link": pa.get("link",""), "image": pa.get("image","")},
        "product_b": {"name": pb["name"], "price": pb.get("price",""),
                      "link": pb.get("link",""), "image": pb.get("image","")},
        "specs": specs, "verdict": verdict,
    })'''

if '@app.route("/api/compare/immo")' in src:
    # Remplace l'ancienne route entière
    start = src.find('@app.route("/api/compare/immo")')
    # Cherche le prochain @app.route ou fin de bloc
    end = src.find('\n\n\n', start)
    if end == -1: end = src.find('\n@app.route', start + 10)
    if end == -1: end = start + len(old_route)
    src = src[:start] + new_route + src[end:]
    print("✅ /api/compare/immo remplacée")
else:
    anchor = "# ═══════════════════════════════════════════════════════════════\n#  HELPERS — LLM / AUDIO / VIDEO"
    src = src.replace(anchor, new_route + "\n\n" + anchor, 1)
    print("✅ /api/compare/immo injectée")

path.write_text(src)
print("✅ app_streamingc.py écrit")
PYEOF

python3 -c "import py_compile; py_compile.compile('$APP', doraise=True)" \
  && echo "✅ Syntaxe Python OK" \
  || { echo "❌ Syntaxe KO — restauration"; cp "$APP.bak_radar2" "$APP"; exit 1; }

# ══════════════════════════════════════════════════════
# 3. HTML : fix isC21 passé à renderCmp depuis
#    openCompareModal / openExportRadar / _pendingCompare
# ══════════════════════════════════════════════════════
python3 - << 'PYEOF'
from pathlib import Path
src = Path("/workspace/wav2lip-onnx-HQ/index.html").read_text()

# openCmp : ajoute paramètre isC21
old = """function openCmp(p1,p2){
  document.getElementById('compareModal').style.display='block';
  document.getElementById('cmpResult').style.display='none';
  document.getElementById('cmpLoading').style.display='none';
  document.getElementById('btnExportPDF').style.display='none';
  if(p1)document.getElementById('cmpP1').value=p1;
  else if(curProd)document.getElementById('cmpP1').value=curProd;
  if(p2)document.getElementById('cmpP2').value=p2;
  else if(curProdB)document.getElementById('cmpP2').value=curProdB;"""

new = """function openCmp(p1,p2){
  document.getElementById('compareModal').style.display='block';
  document.getElementById('cmpResult').style.display='none';
  document.getElementById('cmpLoading').style.display='none';
  document.getElementById('btnExportPDF').style.display='none';
  /* Titre selon mode */
  var _sp=document.getElementById('sysPrompt');
  var _c21=_sp&&_sp.value==='MODE_VENDEUR_C21';
  var mh=document.querySelector('#compareModal h2');
  if(mh)mh.innerHTML=_c21?'🏠 Comparatif biens immobiliers':'⚖️ Comparatif produits';
  if(p1)document.getElementById('cmpP1').value=p1;
  else if(curProd)document.getElementById('cmpP1').value=curProd;
  if(p2)document.getElementById('cmpP2').value=p2;
  else if(curProdB)document.getElementById('cmpP2').value=curProdB;"""

if old in src:
    src = src.replace(old, new, 1)
    print("✅ openCmp titre dynamique")

# runCompare → passe isC21 à fetchCmp
old2 = "function runCompare(){var p1=document.getElementById('cmpP1').value.trim(),p2=document.getElementById('cmpP2').value.trim();if(!p1||!p2){alert('Remplis les 2 produits');return;}fetchCmp(p1,p2);}"
new2 = "function runCompare(){var p1=document.getElementById('cmpP1').value.trim(),p2=document.getElementById('cmpP2').value.trim();if(!p1||!p2){alert('Remplis les 2 produits');return;}var _sp=document.getElementById('sysPrompt');fetchCmp(p1,p2,_sp&&_sp.value==='MODE_VENDEUR_C21');}"
if old2 in src:
    src = src.replace(old2, new2, 1)
    print("✅ runCompare patché")

# fetchCmp : accepte isC21 en 3ème arg (déjà patché mais on force)
old3 = "function fetchCmp(p1,p2){"
new3 = "function fetchCmp(p1,p2,isC21){"
src  = src.replace(old3, new3, 1)

# openCompareModal → passe isC21
old4 = """function openCompareModal(){
  function tryOpen(attempts){
    var p1=curProd,p2=curProdB;
    if(!p2&&attempts>0){return setTimeout(function(){tryOpen(attempts-1);},150);}
    openCmp(p1,p2);
    if(p1&&p2)fetchCmp(p1,p2);
  }
  tryOpen(5);
}"""
new4 = """function openCompareModal(){
  var _sp=document.getElementById('sysPrompt');
  var _c21=_sp&&_sp.value==='MODE_VENDEUR_C21';
  function tryOpen(attempts){
    var p1=curProd,p2=curProdB;
    if(!p2&&attempts>0){return setTimeout(function(){tryOpen(attempts-1);},150);}
    openCmp(p1,p2);
    if(p1&&p2)fetchCmp(p1,p2,_c21);
  }
  tryOpen(5);
}"""
if old4 in src:
    src = src.replace(old4, new4, 1)
    print("✅ openCompareModal patché isC21")

# openExportRadar → passe isC21
old5 = """function openExportRadar(){
  function tryOpen(attempts){
    var p1=curProd,p2=curProdB;
    if(!p2&&attempts>0){return setTimeout(function(){tryOpen(attempts-1);},150);}
    openCmp(p1,p2);
    if(p1&&p2)fetchCmp(p1,p2);
  }
  tryOpen(5);
}"""
new5 = """function openExportRadar(){
  var _sp=document.getElementById('sysPrompt');
  var _c21=_sp&&_sp.value==='MODE_VENDEUR_C21';
  function tryOpen(attempts){
    var p1=curProd,p2=curProdB;
    if(!p2&&attempts>0){return setTimeout(function(){tryOpen(attempts-1);},150);}
    openCmp(p1,p2);
    if(p1&&p2)fetchCmp(p1,p2,_c21);
  }
  tryOpen(5);
}"""
if old5 in src:
    src = src.replace(old5, new5, 1)
    print("✅ openExportRadar patché isC21")

# _pendingCompare → passe isC21
old6 = "document.getElementById('cmpP1').value=pc.p1;\n                document.getElementById('cmpP2').value=pc.p2;\n                openCmp();\n                fetchCmp(pc.p1,pc.p2);"
new6 = "document.getElementById('cmpP1').value=pc.p1;\n                document.getElementById('cmpP2').value=pc.p2;\n                var _sp2=document.getElementById('sysPrompt');\n                var _c21b=_sp2&&_sp2.value==='MODE_VENDEUR_C21';\n                openCmp();\n                fetchCmp(pc.p1,pc.p2,_c21b);"
if old6 in src:
    src = src.replace(old6, new6, 1)
    print("✅ _pendingCompare patché isC21")

Path("/workspace/wav2lip-onnx-HQ/index.html").write_text(src)
print("✅ index.html écrit")
PYEOF

# ══════════════════════════════════════════════════════
# 4. Recharge prompt Sophie avec vrai catalogue
# ══════════════════════════════════════════════════════
python3 - << 'PYEOF'
import json, re
from pathlib import Path

cat  = json.load(open("/workspace/wav2lip-onnx-HQ/c21_catalog.json"))
path = Path("/workspace/wav2lip-onnx-HQ/app_streamingc.py")
src  = path.read_text()

lines = []
for b in cat:
    ext = b.get("ext_label","Aucun")
    lines.append(
        f"- {b['name']} | {b['price']} | {b['surface']} | "
        f"{b['rooms']}p | Étage:{b['floor']} | DPE:{b['dpe']} | Ext:{ext}"
    )
catalog_block = "\\n".join(lines).replace('"', '\\"')

new_c21 = (
    '_C21_PROMPT = (\n'
    '    "Tu es Sophie, agent immobilier Century 21 Farré-Vouille Paris 15.\\n"\n'
    '    "Reponds TOUJOURS en JSON UNE SEULE LIGNE sans markdown:\\n"\n'
    '    \'{"text":"..","product_name":"..","product_b_name":null,"show_compare":false}\\n\'\n'
    '    "REGLES:\\n"\n'
    '    "- Utilise UNIQUEMENT les biens du CATALOGUE ci-dessous.\\n"\n'
    '    "- product_name = valeur exacte du champ name du bien.\\n"\n'
    '    "- Si comparaison demandée: show_compare=true, product_b_name=bienB.\\n"\n'
    '    "- Max 3 phrases 100 mots. Mentionne balcon/terrasse/jardin si dispo.\\n\\n"\n'
    '    "CATALOGUE (nom|loyer|surface|pièces|étage|DPE|extérieurs):\\n"\n'
    f'    "{catalog_block}"\n'
    ')\n'
)

src, n = re.subn(r'_C21_PROMPT\s*=\s*\([\s\S]*?\n\)\n', new_c21, src, count=1)
if not n:
    src, n = re.subn(r'_C21_PROMPT\s*=\s*None.*\n', new_c21, src, count=1)
print(f"✅ _C21_PROMPT rechargé ({len(cat)} biens, {n}x)")
path.write_text(src)
PYEOF

python3 -c "import py_compile; py_compile.compile('$APP', doraise=True)" \
  && echo "✅ Syntaxe finale OK" \
  || { echo "❌ KO — restauration"; cp "$APP.bak_radar2" "$APP"; exit 1; }

pm2 restart wav2lip 2>/dev/null || pm2 restart all 2>/dev/null || echo "⚠ pm2 restart manuel"
echo "=== DONE ==="
