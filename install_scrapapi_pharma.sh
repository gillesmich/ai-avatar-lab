#!/bin/bash

cd ~/scrape_gpt || exit

echo "🚀 Patch ScrapAPI → pharma_scraper.py"

cat > patch_scrapapi_pharma.py << 'PYEOF'
import re

FILE = "pharma_scraper.py"

with open(FILE, "r", encoding="utf-8") as f:
    script = f.read()

# ─────────────────────────────────────────────
# 1️⃣ Imports nécessaires
# ─────────────────────────────────────────────
if "urllib.parse" not in script:
    script = re.sub(
        r"(import requests.*?\n)",
        r"\1import urllib.parse\nimport os\n",
        script,
        flags=re.DOTALL
    )

# ─────────────────────────────────────────────
# 2️⃣ Adapter ScrapAPI
# ─────────────────────────────────────────────
if "fetch_with_scrapapi" not in script:

    scrapapi_block = '''

# ─────────────────────────────────────────────
# ScrapAPI Adapter
# ─────────────────────────────────────────────
SCRAPAPI_KEY = os.getenv("SCRAPAPI_KEY")

def fetch_with_scrapapi(url):

    if not SCRAPAPI_KEY:
        print("⚠️ SCRAPAPI_KEY absente")
        return None

    encoded_url = urllib.parse.quote_plus(url)

    api_url = (
        "https://api.scrapapi.com/"
        f"?api_key={SCRAPAPI_KEY}"
        f"&url={encoded_url}"
        "&render_js=true"
    )

    try:
        r = requests.get(api_url, timeout=60)

        if r.status_code == 200:
            return r.text

        print(f"⚠️ ScrapAPI HTTP {r.status_code}")
        return None

    except Exception as e:
        print(f"⚠️ ScrapAPI exception: {e}")
        return None
'''

    script = scrapapi_block + "\n" + script

# ─────────────────────────────────────────────
# 3️⃣ Smart fetch hybride
# ─────────────────────────────────────────────
smart_fetch_block = '''

def smart_fetch(url, headers, delay):

    # 1️⃣ Requests rapide
    try:
        r = requests.get(url, headers=headers, timeout=30)

        if r.status_code == 200 and len(r.text) > 2000:
            return r.text

        print("🔁 Requests bloqué → ScrapAPI")

    except Exception as e:
        print(f"🔁 Requests error → ScrapAPI ({e})")

    # 2️⃣ ScrapAPI robuste
    html = fetch_with_scrapapi(url)
    if html:
        return html

    # 3️⃣ Fallback Playwright
    print("🔁 ScrapAPI bloqué → Playwright")
    return fetch_with_playwright(url, headers, delay)
'''

script = re.sub(
    r"def smart_fetch.*?return .*?\n",
    smart_fetch_block,
    script,
    flags=re.DOTALL
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(script)

print("✅ Patch ScrapAPI appliqué")
PYEOF

python3 patch_scrapapi_pharma.py

echo "✅ Installation terminée"
