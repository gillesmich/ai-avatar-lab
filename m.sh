#!/bin/bash
DIR="/workspace/wav2lip-onnx-HQ/catalogs/century vouille "
F_RIGHT="${DIR}autoscrape_div_c_the_property_thumbnail_with_content__col_right.json"
F_FULL="${DIR}autoscrape_div_c_the_property_thumbnail_with_content.json"
OUT="/workspace/wav2lip-onnx-HQ/c21_catalog.json"
APP="/workspace/wav2lip-onnx-HQ/app_streamingc.py"
cp "$APP" "$APP.bak_c21v2"

python3 - << 'PYEOF'
import json, re
from pathlib import Path

DIR   = "/workspace/wav2lip-onnx-HQ/catalogs/century vouille /"
F_R   = DIR + "autoscrape_div_c_the_property_thumbnail_with_content__col_right.json"
F_F   = DIR + "autoscrape_div_c_the_property_thumbnail_with_content.json"
OUT   = "/workspace/wav2lip-onnx-HQ/c21_catalog.json"

right = json.load(open(F_R, encoding="utf-8"))
full  = json.load(open(F_F, encoding="utf-8"))

items_r = right.get("items", [])
items_f = full.get("items",  [])

# ── Construit index ref → image depuis fichier full
# L'URL image contient la ref : c21_202_452_23301_8_...jpg → ref=23301
img_by_ref = {}
for item in items_f:
    html = item.get("html", "")
    # Extrait toutes les src d'images
    imgs = re.findall(r'src="(https://[^"]+\.(?:jpg|jpeg|png|webp))"', html)
    # Extrait ref depuis data-uid ou depuis l'URL image
    ref_m = re.search(r'data-uid="(\d+)"', html)
    ref_uid = ref_m.group(1) if ref_m else None
    # Ref courte depuis URL image (ex: _23301_)
    for img_url in imgs:
        ref_img_m = re.search(r'_(\d{4,6})_\d+_', img_url)
        if ref_img_m:
            r = ref_img_m.group(1)
            if r not in img_by_ref:
                img_by_ref[r] = img_url
    # Aussi indexe par uid
    if ref_uid and imgs:
        # uid long → cherche ref courte dans l'url
        for img_url in imgs:
            ref_img_m = re.search(r'_(\d{4,6})_\d+_', img_url)
            if ref_img_m:
                img_by_ref[ref_img_m.group(1)] = img_url
                break

print(f"📸 {len(img_by_ref)} images indexées par ref: {list(img_by_ref.items())[:5]}")

# Fallback images par catégorie
IMG_FB = {
    "Parking": "https://images.unsplash.com/photo-1590674899484-d5640e854abe?w=300&q=80",
    "Studio":  "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=300&q=80",
    "F2":      "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=300&q=80",
    "F3":      "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=300&q=80",
    "F4":      "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=300&q=80",
}

catalog = []
for item in items_r:
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

    surf_m    = re.search(r"([\d,\.]+)\s*m\s*2", text)
    surface_s = surf_m.group(1).replace(",", ".") if surf_m else "0"
    surface_f = float(surface_s)

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
        price_str = re.sub(r"\s+", " ", p).strip()
        if "€" not in price_str: price_str += " €"
        price_str += "/mois"
    price_num_m = re.search(r"([\d\s\xa0]+)", price_str)
    price_num   = int(re.sub(r"[\s\xa0]", "", price_num_m.group(1))) if price_num_m else 0
    pm2 = round(price_num / surface_f) if surface_f > 0 else 0

    floor_m = re.search(r"(\d+)[eèè][rèm]+\s*(?:et\s*dernier\s*)?étage|(\d+)ème|(RDC|rez[- ]de[- ]chaussée)", text, re.I)
    if floor_m:
        if floor_m.group(3): floor = "RDC"
        else:
            n = floor_m.group(1) or floor_m.group(2)
            floor = f"{n}ème"
            if "dernier" in text[max(0,floor_m.start()-5):floor_m.start()+35].lower():
                floor += " (dernier)"
    else: floor = "?"

    dpe_m = re.search(r"DPE\s*([A-G])|classe\s*([A-G])\b|DPE([A-G])", text, re.I)
    dpe   = next((g for g in (dpe_m.groups() if dpe_m else []) if g), "?")
    if dpe != "?": dpe = dpe.upper()

    has_balcon  = bool(re.search(r"balcon", text, re.I))
    has_terasse = bool(re.search(r"terrasse|terasse", text, re.I))
    has_jardin  = bool(re.search(r"jardin", text, re.I))
    ext_score   = (40 if has_jardin else 0) + (30 if has_terasse else 0) + (20 if has_balcon else 0)
    ext_label   = " + ".join(filter(None, [
        "Jardin"   if has_jardin  else "",
        "Terrasse" if has_terasse else "",
        "Balcon"   if has_balcon  else ""
    ])) or "Aucun"

    rue_m = re.search(r"(?:RUE|AVENUE|BOULEVARD|IMPASSE|PLACE|ALLÉE)[^,\n\.]{3,35}", text, re.I)
    rue   = rue_m.group(0).strip().title() if rue_m else ""

    link = ""
    for l in links:
        if "detail" in l.get("href", ""): link = l["href"]; break
    if not link and links: link = links[-1].get("href", "")

    name = f"{categorie} — {quartier}"
    if rue: name += f" — {rue[:28]}"
    name += f" — Ref{ref}"

    # ── Image : vrai catalogue en priorité, fallback Unsplash
    image = img_by_ref.get(ref, "") or IMG_FB.get(categorie, IMG_FB["F2"])

    catalog.append({
        "ref": ref, "name": name, "categorie": categorie,
        "ville": ville, "quartier": quartier, "rue": rue,
        "surface": f"{surface_s} m²", "surface_m2": surface_f,
        "rooms": rooms, "floor": floor, "dpe": dpe,
        "price": price_str, "price_num": price_num, "price_m2": pm2,
        "balcon": has_balcon, "terasse": has_terasse, "jardin": has_jardin,
        "ext_score": ext_score, "ext_label": ext_label,
        "link": link, "image": image,
        "description": " ".join(text.split()[:50]) + "…",
    })

json.dump(catalog, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ {len(catalog)} biens → {OUT}")
for b in catalog:
    has_img = "📸" if "century21" in b["image"] else "🖼"
    print(f"  {has_img} [{b['ref']}] {b['name'][:55]} | {b['price']} | Ext:{b['ext_label']}")
PYEOF

# ── Recharge prompt Sophie
python3 - << 'PYEOF'
import json, re
from pathlib import Path

cat  = json.load(open("/workspace/wav2lip-onnx-HQ/c21_catalog.json"))
path = Path("/workspace/wav2lip-onnx-HQ/app_streamingc.py")
src  = path.read_text()

lines = []
for b in cat:
    ext = b.get("ext_label", "Aucun")
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
    '    "- Si comparaison: show_compare=true, product_b_name=bienB.\\n"\n'
    '    "- Max 3 phrases 100 mots. Mentionne balcon/terrasse/jardin si dispo.\\n\\n"\n'
    '    "CATALOGUE (nom|loyer|surface|pièces|étage|DPE|extérieurs):\\n"\n'
    f'    "{catalog_block}"\n'
    ')\n'
)

src, n = re.subn(r'_C21_PROMPT\s*=\s*\([\s\S]*?\n\)\n', new_c21, src, count=1)
if not n:
    src, n = re.subn(r'_C21_PROMPT\s*=\s*None.*\n', new_c21, src, count=1)
print(f"✅ _C21_PROMPT rechargé ({len(cat)} biens)")
path.write_text(src)
PYEOF

python3 -c "import py_compile; py_compile.compile('$APP', doraise=True)" \
  && echo "✅ Syntaxe OK" \
  || { echo "❌ KO"; cp "$APP.bak_c21v2" "$APP"; exit 1; }

pm2 restart wav2lip 2>/dev/null || pm2 restart all 2>/dev/null || echo "⚠ pm2 restart manuel"
echo "=== DONE ==="
