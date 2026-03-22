#!/usr/bin/env python3
"""
Scraper Century21 Vouillé — catalogue complet JSON avec photos
Usage: python3 scraper_c21.py
Output: catalogue_c21.json
"""
import json, re, asyncio
from playwright.async_api import async_playwright

BASE = "https://www.century21-farre-vouille-paris-15.com"
URLS = {"vente": f"{BASE}/annonces/achat/", "location": f"{BASE}/annonces/location/"}

async def get_links(page, url):
    await page.goto(url, wait_until="networkidle")
    links = await page.eval_on_selector_all(
        'a[href*="/trouver_logement/detail/"]',
        'els => [...new Set(els.map(e => e.href))]'
    )
    return links

def extract_section(text, heading):
    """Extrait le texte après ## Heading jusqu'au prochain ##"""
    m = re.search(rf'##\s*{heading}\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
    return m.group(1).strip() if m else ""

def safe(text):
    return text.strip() if text else ""

async def scrape_detail(page, url, transaction):
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(1000)

    # Texte brut complet de la page
    body = await page.inner_text("body")

    # Ref
    ref = ""
    m = re.search(r'Ref\s*:\s*(\d+)', body)
    if m: ref = m.group(1)

    # Titre (h1)
    titre = await page.locator("h1").first.inner_text()

    # Prix — ligne après "Ref : XXXXX"
    prix = ""
    m = re.search(r'Ref\s*:\s*\d+\s*\n([^\n]+)', body)
    if m: prix = m.group(1).strip()

    # Description complète
    desc = extract_section(body, "Description")

    # Vue globale (pièces + surfaces)
    vue = extract_section(body, "Vue globale")

    # Équipements
    equip = extract_section(body, r'[ÉE]quipements')

    # À savoir (charges, taxe)
    asavoir = extract_section(body, r'[ÀA]\s*savoir')

    # Copropriété
    copro = extract_section(body, r'Copropri[eé]t[eé]')

    # DPE — cherche lettre après pattern kWh
    dpe = ""
    m = re.search(r'(\d+)\s*kWh/m.*?(\d+)\s*kg', body, re.DOTALL)
    # Simpler: cherche "classé X" ou "DPE.*?([A-G])"
    m2 = re.search(r'class[eé]\s+([A-G])\b', body)
    if m2: dpe = m2.group(1)

    # Photos — img avec src dans le HTML rendu
    photos = await page.eval_on_selector_all(
        'img',
        '''els => [...new Set(
            els.map(e => e.src || e.dataset.src || e.dataset.lazySrc || "")
               .filter(s => s.includes("/imagesBien/") && !s.includes("data:"))
        )]'''
    )
    # Photo principale toujours présente (format s3)
    m3 = re.search(r'(https://[^\s"]+/imagesBien/s3/[^\s"]+\.jpg)', body)
    if m3 and m3.group(1) not in photos:
        photos.insert(0, m3.group(1))

    return {
        "ref": ref,
        "titre": safe(titre),
        "transaction": transaction,
        "prix": prix,
        "description": desc,
        "vue_globale": vue,
        "equipements": equip,
        "a_savoir": asavoir,
        "copropriete": copro,
        "dpe": dpe,
        "photos": photos,
        "lien": url,
    }

async def main():
    catalogue = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        page = await ctx.new_page()

        for transaction, url in URLS.items():
            print(f"\n=== {transaction.upper()} ===")
            links = await get_links(page, url)
            # Déduplique et filtre les ?came_from=
            links = list(dict.fromkeys(l.split('?')[0] for l in links))
            print(f"{len(links)} biens")

            for i, link in enumerate(links):
                print(f"  [{i+1}/{len(links)}] {link}")
                try:
                    bien = await scrape_detail(page, link, transaction)
                    print(f"    → ref={bien['ref']} | {len(bien['photos'])} photos | desc={len(bien['description'])} chars")
                    catalogue.append(bien)
                except Exception as e:
                    print(f"    ERREUR: {e}")
                    catalogue.append({"lien": link, "transaction": transaction, "erreur": str(e)})
                await asyncio.sleep(0.5)

        await browser.close()

    with open("catalogue_c21.json", "w", encoding="utf-8") as f:
        json.dump(catalogue, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {len(catalogue)} biens → catalogue_c21.json")

if __name__ == "__main__":
    asyncio.run(main())
