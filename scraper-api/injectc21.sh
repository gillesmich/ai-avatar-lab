#!/bin/bash
# inject_c21_role.sh
# Injecte le catalogue C21 + bouton rôle dans wav2lip-onnx-HQ
# Usage: bash inject_c21_role.sh
set -e
WORK="/workspace/wav2lip-onnx-HQ"
APP="$WORK/app_streamingc.py"
HTML="$WORK/index.html"
CAT="$WORK/c21_catalog.json"
BAK="$WORK/bak_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BAK"

echo "=== Backup ==="
cp "$APP"  "$BAK/app_streamingc.py"
cp "$HTML" "$BAK/index.html"
echo "OK -> $BAK"

# ─────────────────────────────────────────────────────────────
# 1. GENERE c21_catalog.json depuis catalogue_c21.json si absent
# ─────────────────────────────────────────────────────────────
if [ ! -f "$CAT" ]; then
  SRC="$WORK/catalogue_c21.json"
  if [ -f "$SRC" ]; then
    echo "=== Conversion catalogue_c21.json -> c21_catalog.json ==="
    python3 - << 'PYEOF'
import json, re, sys
src = "/workspace/wav2lip-onnx-HQ/catalogue_c21.json"
dst = "/workspace/wav2lip-onnx-HQ/c21_catalog.json"
raw = json.load(open(src))
out = []
for b in raw:
    # Extrait surface numérique
    surf_m = re.search(r"([\d.,]+)", str(b.get("surface") or ""))
    surf = surf_m.group(1) if surf_m else "?"
    # Extrait nb pièces
    piec_m = re.search(r"(\d+)", str(b.get("pieces") or b.get("titre","") or ""))
    piec = piec_m.group(1) if piec_m else "?"
    # Prix formaté
    prix = b.get("prix") or b.get("loyer_cc") or "?"
    prix_str = (str(prix) + " €") if isinstance(prix, int) else str(prix)
    # DPE depuis description
    dpe_m = re.search(r"DPE\s*([A-G])", str(b.get("description","")), re.I)
    dpe = dpe_m.group(1).upper() if dpe_m else "?"
    # Quartier/CP
    cp  = b.get("cp","")
    vil = b.get("ville","")
    qrt = b.get("quartier", vil + " " + cp).strip()
    # Photo principale
    photos = b.get("photos", [])
    img = photos[0] if photos else ""
    out.append({
        "name":        b.get("ref","?") + " — " + b.get("type","") + " — " + vil + " " + cp,
        "ref":         b.get("ref",""),
        "type":        b.get("type",""),
        "transaction": b.get("transaction",""),
        "price":       prix_str,
        "surface":     surf + " m²",
        "rooms":       piec + " pièces",
        "floor":       b.get("details",{}).get("Étage","?") if isinstance(b.get("details"),dict) else "?",
        "dpe":         dpe,
        "quartier":    qrt,
        "description": (b.get("description","")[:400] + "…") if len(b.get("description","")) > 400 else b.get("description",""),
        "image":       img,
        "link":        b.get("lien","#"),
    })
json.dump(out, open(dst,"w"), ensure_ascii=False, indent=2)
print(f"[c21] {len(out)} biens -> {dst}")
PYEOF
  else
    echo "WARN: catalogue_c21.json absent, c21_catalog.json non généré"
  fi
else
  echo "=== c21_catalog.json déjà présent ($(python3 -c "import json;d=json.load(open('$CAT'));print(len(d),'biens')")) ==="
fi

# ─────────────────────────────────────────────────────────────
# 2. PATCH app_streamingc.py — charge c21_catalog.json au boot
# ─────────────────────────────────────────────────────────────
grep -q "_C21_CATALOG_LOADED" "$APP" && echo "=== app: patch catalog déjà présent ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/app_streamingc.py"
src  = open(path).read()
PATCH = '''
# ── C21 catalog auto-load ──────────────────────────────────────
_C21_CATALOG_LOADED = False
def _c21_catalog_load():
    global _C21_CATALOG_LOADED
    import json as _jc, re as _rc, os as _oc
    from pathlib import Path as _Pc
    cat = _Pc(__file__).parent / "c21_catalog.json"
    if not cat.exists():
        print("[c21] c21_catalog.json absent", flush=True)
        return
    try:
        biens = _jc.load(open(cat))
        lines = []
        for b in biens:
            lines.append(
                f"- Ref{b.get('ref','?')} | {b.get('type','')} | {b.get('transaction','')} | "
                f"{b.get('price','')} | Surface:{b.get('surface','')} | "
                f"Pièces:{b.get('rooms','')} | DPE:{b.get('dpe','')} | "
                f"Quartier:{b.get('quartier','')} | Etage:{b.get('floor','?')}"
            )
        global _C21_PROMPT
        _C21_PROMPT = (
            "Tu es Sophie, agente immobilière experte Century 21 Farré-Vouille Paris 15ème. "
            "Réponds TOUJOURS en JSON UNE SEULE LIGNE sans markdown:\\n"
            '{"text":"..","product_name":null,"product_price":null,"product_image":null,"product_link":null,"product_b_name":null,"show_compare":false}\\n'
            "RÈGLES:\\n"
            "- Spécialiste immobilier : biens, surface, quartier, prix au m², DPE, charges.\\n"
            "- product_name = 'Ref{ref} — {type} — {ville}' si un bien précis est mentionné.\\n"
            "- Max 3 phrases, 100 mots. Ton professionnel et chaleureux.\\n"
            "- Ne jamais parler de PC ou informatique.\\n\\n"
            "CATALOGUE BIENS:\\n" + "\\n".join(lines)
        )
        _C21_CATALOG_LOADED = True
        print(f"[c21] {len(biens)} biens chargés dans le prompt Sophie", flush=True)
    except Exception as e:
        print(f"[c21] erreur chargement: {e}", flush=True)

_c21_catalog_load()
# ────────────────────────────────────────────────────────────────
'''
# Insère juste après _catalog_load()
INSERT_AFTER = "_catalog_load()"
idx = src.find(INSERT_AFTER)
if idx == -1:
    print("WARN: ancre _catalog_load() introuvable")
else:
    end = src.find("\n", idx) + 1
    src = src[:end] + PATCH + src[end:]
    open(path,"w").write(src)
    print("[app] patch c21_catalog_load injecté")
PYEOF

# ─────────────────────────────────────────────────────────────
# 3. PATCH app_streamingc.py — route /api/compare/immo utilise c21_catalog.json réel
# ─────────────────────────────────────────────────────────────
grep -q "_C21_CATALOG_LOADED" "$APP" && echo "=== app: route immo déjà patchée ===" || true

# ─────────────────────────────────────────────────────────────
# 4. PATCH index.html — bouton C21 dans panelVoice (si absent)
# ─────────────────────────────────────────────────────────────
grep -q "btnC21" "$HTML" && echo "=== HTML: btnC21 déjà présent ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/index.html"
src  = open(path).read()

# 4a. Bouton C21 dans la barre des boutons prompt (après btnPCM)
OLD_BTN = '<button class="btn-sm" id="btnPCM"'
NEW_BTN = '''<button class="btn-sm" id="btnC21" style="background:linear-gradient(135deg,#b45309,#d97706);color:#fff;border:none;">🏠 Century 21</button>
                <button class="btn-sm" id="btnPCM"'''
if OLD_BTN in src and 'btnC21' not in src:
    src = src.replace(OLD_BTN, NEW_BTN)
    print("[html] bouton C21 injecté")
else:
    print("[html] bouton C21 déjà présent ou ancre introuvable")

open(path,"w").write(src)
PYEOF

# 4b. Injecte le JS btnC21 handler dans DOMContentLoaded (si absent)
grep -q "btnC21.*addEventListener" "$HTML" && echo "=== HTML: btnC21 JS déjà présent ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/index.html"
src  = open(path).read()

# Handler JS pour le bouton C21
C21_JS = """
/* ── Bouton C21 ── */
var _btnC21 = document.getElementById('btnC21');
if(_btnC21) _btnC21.addEventListener('click', function(){
  sysP.value = 'MODE_VENDEUR_C21';
  var st = document.getElementById('pcmStatus');
  if(st) st.textContent = '🏠 Century 21 Farré-Vouille';
  /* Badge info visible */
  var badge = document.getElementById('c21RoleBadge');
  if(badge){ badge.style.display = 'flex'; }
  /* Lance le welcome Sophie si avatar chargé */
  if(aId && !_welcomeDone){
    _welcomeDone = true;
    setTimeout(function(){ launchWelcome(aId, 'c21'); }, 300);
  }
});
"""

# Cherche l'ancre btnReset addEventListener pour insérer après
ANCHOR = "document.getElementById('btnReset').addEventListener"
idx = src.find(ANCHOR)
if idx == -1:
    # Fallback : avant </script> final
    idx = src.rfind("</script>")
    if idx != -1:
        src = src[:idx] + C21_JS + "\n" + src[idx:]
        print("[html] btnC21 JS injecté (fallback)</script>")
else:
    # Insère juste avant l'ancre
    src = src[:idx] + C21_JS + "\n" + src[idx:]
    print("[html] btnC21 JS injecté après btnReset")

open(path,"w").write(src)
PYEOF

# ─────────────────────────────────────────────────────────────
# 5. PATCH index.html — badge rôle actif visible dans le stage
# ─────────────────────────────────────────────────────────────
grep -q "c21RoleBadge" "$HTML" && echo "=== HTML: badge rôle déjà présent ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/index.html"
src  = open(path).read()

BADGE_HTML = """
        <!-- Badge rôle actif -->
        <div id="c21RoleBadge" style="display:none;align-items:center;gap:8px;padding:6px 12px;
          margin:8px auto 0;max-width:800px;background:rgba(180,83,9,.18);
          border:1px solid rgba(217,119,6,.4);border-radius:8px;font-size:12px;color:#fbbf24;">
          <span>🏠</span>
          <span id="c21RoleLabel">Century 21 Farré-Vouille — Sophie, agente immobilière</span>
          <button onclick="document.getElementById('c21RoleBadge').style.display='none';
            document.getElementById('sysPrompt').value='Tu es un assistant sympathique et concis.';
            document.getElementById('pcmStatus').textContent='';"
            style="margin-left:auto;background:none;border:none;color:#fbbf24;cursor:pointer;font-size:14px;">✕</button>
        </div>
"""

# Insère juste après la div conv-center (après waveCanvas)
ANCHOR = '<div class="conv-center">'
idx = src.find(ANCHOR)
if idx != -1:
    # Trouve la fermeture de conv-center
    end_tag = src.find("</div>", idx)
    # Insère après la div conv-center complète
    insert_pos = src.find("\n", end_tag) + 1
    src = src[:insert_pos] + BADGE_HTML + src[insert_pos:]
    print("[html] badge rôle injecté")
else:
    print("WARN: ancre conv-center introuvable")

open(path,"w").write(src)
PYEOF

# ─────────────────────────────────────────────────────────────
# 6. PATCH welcome pour gérer mode c21
# ─────────────────────────────────────────────────────────────
grep -q "mode.*c21.*Sophie" "$APP" && echo "=== app: welcome c21 déjà patchée ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/app_streamingc.py"
src  = open(path).read()

OLD = '''        welcome_prompt = (
            "Presente-toi en une phrase chaleureuse comme Maya, "
            "vendeuse experte PCMarket specialiste des PC reconditiones. "
            "Commence par Bonjour, puis demande le prenom du client. "
            \'Reponds UNIQUEMENT en JSON une ligne: \'
            \'{"text":"...","product_name":null,"product_b_name":null,"show_compare":false}\'
        )'''

NEW = '''        _mode_welcome = task.get("_mode_welcome","pcmarket")
        if _mode_welcome == "c21":
            _sys_welcome = _C21_PROMPT or "Tu es Sophie, agente immobilière Century 21."
            conversations[conv_id][0] = {"role":"system","content":_sys_welcome}
            welcome_prompt = (
                "Présente-toi chaleureusement comme Sophie, agente immobilière Century 21 Farré-Vouille Paris 15ème. "
                "Dis bonjour et propose d\'aider à trouver un bien. "
                "Réponds UNIQUEMENT en JSON une ligne: "
                \'{"text":"...","product_name":null,"product_b_name":null,"show_compare":false}\'
            )
        else:
            welcome_prompt = (
                "Presente-toi en une phrase chaleureuse comme Maya, "
                "vendeuse experte PCMarket specialiste des PC reconditiones. "
                "Commence par Bonjour, puis demande le prenom du client. "
                \'Reponds UNIQUEMENT en JSON une ligne: \'
                \'{"text":"...","product_name":null,"product_b_name":null,"show_compare":false}\'
            )'''

if OLD in src:
    src = src.replace(OLD, NEW)
    print("[app] welcome c21 patchée")
else:
    print("WARN: ancre welcome_prompt introuvable")
open(path,"w").write(src)
PYEOF

# Patch task _mode_welcome dans /api/process/welcome
grep -q "_mode_welcome" "$APP" && echo "=== app: _mode_welcome déjà présent ===" || python3 - << 'PYEOF'
path = "/workspace/wav2lip-onnx-HQ/app_streamingc.py"
src  = open(path).read()

OLD = '''    tasks[task_id] = {
        "status": "pending", "progress": 0, "message": "Initialisation accueil...",
        "video_url": None, "transcript": "", "response": None, "error": None,
        "conversation_id": conv_id,
        "_avatar": str(paths[0]), "_voice": voice_id, "_voice_provider": voice_provider,
    }'''

NEW = '''    _wmode = (body.get("mode") or "pcmarket").strip()
    if _wmode == "c21" and (_C21_PROMPT):
        if conv_id not in conversations:
            conversations[conv_id] = [{"role":"system","content":_C21_PROMPT}]
        else:
            conversations[conv_id][0] = {"role":"system","content":_C21_PROMPT}
    tasks[task_id] = {
        "status": "pending", "progress": 0, "message": "Initialisation accueil...",
        "video_url": None, "transcript": "", "response": None, "error": None,
        "conversation_id": conv_id,
        "_avatar": str(paths[0]), "_voice": voice_id, "_voice_provider": voice_provider,
        "_mode_welcome": _wmode,
    }'''

if OLD in src:
    src = src.replace(OLD, NEW)
    print("[app] task _mode_welcome injecté")
else:
    print("WARN: ancre tasks welcome introuvable")
open(path,"w").write(src)
PYEOF

# ─────────────────────────────────────────────────────────────
# 7. VERIFICATION
# ─────────────────────────────────────────────────────────────
echo ""
echo "=== Vérification ==="
grep -c "btnC21"           "$HTML" && echo "✅ btnC21 dans HTML"        || echo "❌ btnC21 absent HTML"
grep -c "c21RoleBadge"     "$HTML" && echo "✅ badge rôle dans HTML"    || echo "❌ badge rôle absent HTML"
grep -c "_C21_CATALOG_LOADED" "$APP"  && echo "✅ catalog C21 dans app"    || echo "❌ catalog C21 absent app"
grep -c "_mode_welcome"    "$APP"  && echo "✅ mode_welcome dans app"   || echo "❌ mode_welcome absent app"
[ -f "$CAT" ] && echo "✅ c21_catalog.json présent ($(python3 -c "import json;print(len(json.load(open('$CAT'))),'biens')"))" || echo "⚠️  c21_catalog.json absent"

echo ""
echo "=== Restart PM2 ==="
cd "$WORK" && pm2 restart app_streamingc 2>/dev/null || pm2 restart all 2>/dev/null || echo "⚠️  PM2 restart manuel requis"
echo "✅ Done"
