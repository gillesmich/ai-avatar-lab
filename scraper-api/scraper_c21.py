#!/usr/bin/env python3
"""
Scraper Century21 Vouillé — catalogue complet JSON avec photos
Usage: python3 scraper_c21.py
Output: catalogue_c21.json
"""
import json, re, asyncio
from playwright.async_api import async_playwright

BASE = "https://www.century21-farre-vouille-paris-15.com"
URLS = {
    "vente":    f"{BASE}/annonces/achat/",
    "location": f"{BASE}/annonces/location/",
}

async def get_links(page, url):
    await page.goto(url, wait_until="networkidle")
    links = await page.eval_on_selector_all(
        'a[href*="/trouver_logement/detail/"]',
        'els => [...new Set(els.map(e => e.href))]'
    )
    return links

async def scrape_detail(page, url, transaction):
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(1500)  # laisser le lazy-load se déclencher

    def txt(sel):
        try:
            el = page.locator(sel).first
            return asyncio.get_event_loop().run_until_complete(el.inner_text()) if el else ""
        except: return ""

    # Ref
    ref = await page.locator("text=/Ref\s*:\s*\d+/").first.inner_text()
    ref = re.search(r'\d+', ref).group() if ref else ""

    # Titre / type
    titre = await page.locator("h1").first.inner_text()

    # Prix
    prix_raw = await page.locator(".c-the-property-overview__price, [class*='price']").first.inner_text()

    # Description complète
    desc = await page.locator("#description, .c-the-property-description, [class*='description'] p").first.inner_text()

    # Pièces détails (liste)
    pieces_els = await page.locator(".c-the-property-overview__rooms li, [class*='rooms'] li").all()
    pieces = [await el.inner_text() for el in pieces_els]

    # Surface, étage, construction
    details_els = await page.locator(".c-the-property-overview__details li, [class*='global'] li").all()
    details = {}
    for el in details_els:
        t = await el.inner_text()
        if ':' in t:
            k, v = t.split(':', 1)
            details[k.strip()] = v.strip()

    # Équipements
    equip_els = await page.locator(".c-the-property-equipment li, [class*='equipment'] li").all()
    equipements = [await el.inner_text() for el in equip_els]

    # DPE
    dpe = await page.locator("[class*='dpe'] [class*='letter'], [class*='energy'] strong").first.inner_text()

    # Charges / taxe
    charges = await page.locator("text=/Charges/").first.inner_text()
    taxe    = await page.locator("text=/Taxe foncière/").first.inner_text()

    # Copropriété
    copro_lots   = await page.locator("text=/Nombre de Lots/").first.inner_text()
    copro_charg  = await page.locator("text=/Charges courantes/").first.inner_text()

    # Photos — toutes les img avec src réel
    photos = await page.eval_on_selector_all(
        'img[src*="/imagesBien/"]',
        'els => [...new Set(els.map(e => e.src).filter(s => s && !s.includes("data:")))]'
    )
    # Aussi les data-src lazy
    photos_lazy = await page.eval_on_selector_all(
        'img[data-src*="/imagesBien/"]',
        'els => [...new Set(els.map(e => e.dataset.src).filter(Boolean))]'
    )
    all_photos = list(dict.fromkeys(photos + photos_lazy))

    return {
        "ref": ref,
        "titre": titre.strip(),
        "transaction": transaction,
        "prix_brut": prix_raw.strip(),
        "description": desc.strip(),
        "pieces_detail": pieces,
        "details": details,
        "equipements": equipements,
        "dpe": dpe.strip() if dpe else "",
        "charges": charges.strip() if charges else "",
        "taxe_fonciere": taxe.strip() if taxe else "",
        "copropriete": {
            "lots": copro_lots.strip() if copro_lots else "",
            "charges_annuelles": copro_charg.strip() if copro_charg else ""
        },
        "photos": all_photos,
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
            print(f"{len(links)} biens trouvés")
            for i, link in enumerate(links):
                print(f"  [{i+1}/{len(links)}] {link}")
                try:
                    bien = await scrape_detail(page, link, transaction)
                    print(f"    → {bien['ref']} | {len(bien['photos'])} photos")
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
