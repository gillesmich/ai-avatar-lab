import re, json, asyncio, time, os
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

app = Flask(__name__)

@app.route("/scraper.js")
def scraper_js():
    with open("/workspace/scraper-api/scraper.js") as f:
        return make_response(f.read(), 200, {"Content-Type": "application/javascript"})

@app.route("/")
def index():
    with open("/workspace/scraper-api/scraper.html") as f:
        return make_response(f.read(), 200, {"Content-Type": "text/html"})


CORS(app)

# ── Helpers ────────────────────────────────────────────────

def parse_page(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script","style","noscript"]): tag.decompose()

    title    = (soup.title.string or "").strip() if soup.title else ""
    meta     = soup.find("meta", attrs={"name":"description"})
    meta_desc = meta["content"].strip() if meta and meta.get("content") else ""

    links = []
    for a in soup.find_all("a", href=True)[:200]:
        try:
            href = urljoin(base_url, a["href"])
            if href.startswith("http"):
                links.append({"text": a.get_text(strip=True)[:100], "href": href})
        except: pass

    images = []
    for img in soup.find_all("img", src=True)[:100]:
        try:
            src = urljoin(base_url, img["src"])
            images.append({"src": src, "alt": img.get("alt","")})
        except: pass

    headings = [{"level": h.name.upper(), "text": h.get_text(strip=True)[:300]}
                for h in soup.find_all(["h1","h2","h3","h4","h5","h6"])
                if h.get_text(strip=True)][:80]

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")
                  if len(p.get_text(strip=True)) > 30][:50]

    tables = []
    for i, tbl in enumerate(soup.find_all("table")[:10]):
        rows = [[td.get_text(strip=True) for td in tr.find_all(["th","td"])]
                for tr in tbl.find_all("tr")]
        rows = [r for r in rows if r]
        if rows: tables.append({"index": i+1, "rows": rows[:30]})

    text_body = soup.get_text(separator="\n")
    emails    = list(set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text_body)))[:30]
    phones    = list(set(p for p in re.findall(
        r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{0,4}", text_body)
        if len(re.sub(r"\D","",p)) >= 8))[:30]

    return dict(title=title, metaDesc=meta_desc, links=links, images=images,
                headings=headings, paragraphs=paragraphs, tables=tables,
                emails=emails, phones=phones)


def extract_selector(html, base_url, selector):
    soup = BeautifulSoup(html, "lxml")
    results = []
    for el in soup.select(selector)[:100]:
        results.append({
            "tag":  el.name.upper(),
            "text": el.get_text(strip=True)[:400],
            "html": str(el)[:600],
            "attrs": {k: str(v) for k,v in (el.attrs or {}).items()}
        })
    return results


# ── Routes ─────────────────────────────────────────────────

@app.route("/scrape", methods=["POST"])
def scrape():
    body     = request.json or {}
    url      = body.get("url","").strip()
    selector = body.get("selector","").strip()
    js_wait  = body.get("js_wait", True)   # attendre JS si True
    timeout  = int(body.get("timeout", 20000))

    if not url.startswith("http"):
        url = "https://" + url
    if not url:
        return jsonify({"error": "url manquante"}), 400

    async def fetch():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True,
                args=["--no-sandbox","--disable-setuid-sandbox",
                      "--disable-blink-features=AutomationControlled"])
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36",
                viewport={"width":1280,"height":800},
                locale="fr-FR"
            )
            page = await ctx.new_page()
            # masquer webdriver
            await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                if js_wait:
                    await page.wait_for_timeout(2500)  # laisser le JS s'exécuter
            except Exception as e:
                await browser.close()
                return None, str(e)
            html = await page.content()
            screenshot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            await browser.close()
            return html, screenshot

    try:
        html, screenshot = asyncio.run(fetch())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if html is None:
        return jsonify({"error": screenshot}), 500  # screenshot = message erreur ici

    import base64
    data = parse_page(html, url)
    data["rawHtml"]     = html
    data["screenshot"]  = "data:image/jpeg;base64," + base64.b64encode(screenshot).decode()

    if selector:
        data["selectorResult"] = extract_selector(html, url, selector)

    return jsonify(data)


@app.route("/selector", methods=["POST"])
def selector_only():
    body     = request.json or {}
    html     = body.get("html","")
    base_url = body.get("base_url","https://example.com")
    selector = body.get("selector","")
    if not selector:
        return jsonify({"error": "selector manquant"}), 400
    return jsonify({"results": extract_selector(html, base_url, selector)})


@app.route("/health")
def health():
    return jsonify({"status":"ok","port": """ + str(PORT) + """})


@app.route("/detect", methods=["POST"])
def detect():
    from bs4 import BeautifulSoup
    from collections import Counter
    body = request.json or {}
    html = body.get("html", "")
    if not html:
        return jsonify({"error": "html manquant"}), 400
    soup = BeautifulSoup(html, "lxml")
    counter = Counter()
    for tag in soup.find_all(["article", "li", "div", "section", "ul"]):
        cls = tag.get("class")
        if cls:
            key = tag.name + "." + cls[0]
            counter[key] += 1
    candidates = []
    for sel, cnt in counter.most_common(50):
        if cnt < 2:
            continue
        try:
            els = soup.select(sel)
            sample = str(els[0])[:300] if els else ""
            candidates.append({"selector": sel, "count": cnt, "sample": sample})
        except Exception:
            pass
    return jsonify({"candidates": candidates})


@app.route("/autoscrape", methods=["POST"])
def autoscrape():
    from bs4 import BeautifulSoup
    from collections import Counter
    body = request.json or {}
    html  = body.get("html", "")
    base  = body.get("base_url", "")
    min_count = int(body.get("min_count", 2))
    if not html:
        return jsonify({"error": "html manquant"}), 400

    soup = BeautifulSoup(html, "lxml")

    # ── Collecte sélecteurs candidats ──
    counter = Counter()
    for tag in soup.find_all(["article","li","div","section"]):
        cls = tag.get("class")
        if cls:
            key = tag.name + "." + cls[0]
            counter[key] += 1

    candidates = [(sel, cnt) for sel, cnt in counter.most_common(60) if cnt >= min_count]

    def score_element(el):
        """Score un élément : plus il contient de texte/liens/prix, mieux c\'est."""
        text  = el.get_text(separator=" ", strip=True)
        links = el.find_all("a", href=True)
        imgs  = el.find_all("img", src=True)
        has_price = bool(re.search(r"[\d\s]+[€$£]|[€$£][\d\s]+", text))
        score = (
            min(len(text), 500) * 0.5 +
            len(links) * 20 +
            len(imgs)  * 10 +
            (200 if has_price else 0)
        )
        return score

    def extract_fields(el, base_url):
        """Extrait champs structurés d\'un élément annonce."""
        text = el.get_text(separator=" ", strip=True)
        links = []
        for a in el.find_all("a", href=True):
            try:
                from urllib.parse import urljoin
                href = urljoin(base_url, a["href"])
                links.append({"text": a.get_text(strip=True)[:100], "href": href})
            except: pass
        imgs = []
        for img in el.find_all("img", src=True):
            try:
                from urllib.parse import urljoin
                imgs.append({"src": urljoin(base_url, img["src"]), "alt": img.get("alt","")})
            except: pass
        prices = re.findall(r"[\d\s.,]+\s*[€$£]|[€$£]\s*[\d\s.,]+", text)
        # Champs nommés heuristique
        fields = {}
        for cls_name in ["title","prix","price","surface","rooms","location","address","desc","type","ref"]:
            found = el.find(class_=re.compile(cls_name, re.I))
            if found:
                fields[cls_name] = found.get_text(strip=True)
        return {
            "text":   text[:600],
            "links":  links[:5],
            "images": imgs[:3],
            "prices": prices[:3],
            "fields": fields,
            "html":   str(el)[:500]
        }

    results = []
    for sel, cnt in candidates:
        try:
            els = soup.select(sel)
            if not els: continue
            scores = [score_element(e) for e in els]
            avg_score = sum(scores) / len(scores)
            if avg_score < 30: continue  # trop pauvre
            items = [extract_fields(e, base) for e in els[:50]]
            results.append({
                "selector":  sel,
                "count":     cnt,
                "avg_score": round(avg_score, 1),
                "items":     items
            })
        except Exception:
            pass

    # Trie par score moyen desc
    results.sort(key=lambda x: x["avg_score"], reverse=True)

    return jsonify({
        "total_candidates": len(candidates),
        "results": results[:10]   # top 10 sélecteurs
    })


# ═══════════════════════════════════════════════════════════════════════════════
# DEEPSCRAPE — listing + détail de chaque annonce
# ═══════════════════════════════════════════════════════════════════════════════

async def _scrape_detail(page, url, cfg):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(cfg.get("js_wait", 2000))
    except Exception as e:
        return {"url": url, "_error": str(e)}

    import base64
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    html = await page.content()
    soup = BeautifulSoup(html, "lxml")

    def sel_text(sel, fallback=None):
        if sel:
            el = soup.select_one(sel)
            if el: return el.get_text(strip=True)
        for tag in (fallback or []):
            el = soup.find(tag)
            if el: return el.get_text(strip=True)
        return ""

    def sel_all(sel):
        if not sel: return []
        return [e.get_text(strip=True) for e in soup.select(sel) if e.get_text(strip=True)]

    title = sel_text(cfg.get("sel_title",""), ["h1","h2"])
    parts = sel_all(cfg.get("sel_desc","")) or \
            [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True))>40][:10]
    description = " ".join(parts)[:2000]

    price = sel_text(cfg.get("sel_price",""))
    if not price:
        found = re.findall(r"[\d\s.,]+\s*[€$£]|[€$£]\s*[\d\s.,]+", soup.get_text(" "))
        price = found[0].strip() if found else ""

    images = []
    for img in soup.select(cfg.get("sel_imgs","") or "img")[:20]:
        src = img.get("src","") or img.get("data-src","") or img.get("data-lazy","")
        if src:
            src = urljoin(url, src)
            if any(x in src.lower() for x in [".jpg",".jpeg",".png",".webp",".gif"]):
                images.append({"src": src, "alt": img.get("alt","")})

    named = {}
    for k in ["surface","pieces","ref","dpe","etage","loyer","charges","type","ville"]:
        el = soup.find(class_=re.compile(k, re.I))
        if el: named[k] = el.get_text(strip=True)[:100]

    og = {m.get("property","").replace("og:",""):m.get("content","")
          for m in soup.find_all("meta", property=re.compile("^og:"))}

    sc_b64 = ""
    try:
        sc = await page.screenshot(type="jpeg", quality=50,
                                   clip={"x":0,"y":0,"width":600,"height":400})
        sc_b64 = "data:image/jpeg;base64," + base64.b64encode(sc).decode()
    except: pass

    return {"url":url,"title":title or og.get("title",""),
            "description":description or og.get("description",""),
            "price":price,"images":images,"fields":named,"og":og,
            "screenshot":sc_b64,"_scraped_at":time.strftime("%Y-%m-%d %H:%M:%S")}


@app.route("/deepscrape", methods=["POST"])
def deepscrape():
    """
    {
      "url":         "https://site.com/annonces",
      "sel_items":   "div.odd",
      "sel_links":   "a",
      "sel_title":   "h1",
      "sel_desc":    ".description",
      "sel_price":   ".price",
      "sel_imgs":    ".slider img",
      "max_items":   20,
      "delay_ms":    1000,
      "js_wait":     2000,
      "same_domain": true,
      "output_file": "/workspace/scraper-api/output.json"
    }
    """
    body = request.json or {}
    url  = body.get("url","").strip()
    if not url: return jsonify({"error":"url manquante"}), 400
    if not url.startswith("http"): url = "https://"+url

    sel_items   = body.get("sel_items","")
    sel_links   = body.get("sel_links","a")
    max_items   = min(int(body.get("max_items",20)),100)
    delay_ms    = int(body.get("delay_ms",1000))
    js_wait     = int(body.get("js_wait",2000))
    same_domain = body.get("same_domain", True)
    output_file = body.get("output_file","").strip()
    detail_cfg  = {k:body.get(k,"") for k in
                   ["sel_title","sel_desc","sel_price","sel_imgs"]}
    detail_cfg["js_wait"] = js_wait

    from urllib.parse import urlparse
    base_domain = urlparse(url).netloc

    async def run():
        results, errors = [], []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True,
                args=["--no-sandbox","--disable-setuid-sandbox",
                      "--disable-blink-features=AutomationControlled"])
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                viewport={"width":1280,"height":800}, locale="fr-FR")
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            # 1. page listing
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(js_wait)
            except Exception as e:
                await browser.close()
                return [], [], str(e)

            html = await page.content()
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            soup = BeautifulSoup(html, "lxml")

            # 2. collecte liens
            links = []
            if sel_items:
                for item in soup.select(sel_items):
                    a = item.select_one(sel_links) if sel_links else item.find("a", href=True)
                    if a and a.get("href"):
                        href = urljoin(url, a["href"])
                        if href.startswith("http") and href not in links:
                            if not same_domain or urlparse(href).netloc == base_domain:
                                links.append(href)
            if not links:
                for a in soup.select(sel_links or "a[href]")[:200]:
                    href = urljoin(url, a.get("href",""))
                    if href.startswith("http") and href not in links and href != url:
                        if not same_domain or urlparse(href).netloc == base_domain:
                            links.append(href)

            links = links[:max_items]

            # 3. scrape détail
            dpage = await ctx.new_page()
            for i, lnk in enumerate(links):
                item = await _scrape_detail(dpage, lnk, detail_cfg)
                results.append(item)
                if delay_ms > 0 and i < len(links)-1:
                    await dpage.wait_for_timeout(delay_ms)

            await browser.close()
        return results, errors, None

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results, errors, fatal = loop.run_until_complete(run())
        finally:
            loop.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if fatal:
        return jsonify({"error": fatal}), 500

    payload = {
        "_meta": {
            "url": url, "total": len(results),
            "errors": len(errors),
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "items": results
    }

    if output_file:
        try:
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            payload["_saved_to"] = output_file
        except Exception as e:
            payload["_save_error"] = str(e)

    return jsonify(payload)



@app.route("/pivot", methods=["POST"])
def pivot():
    import re
    body = request.json or {}
    raw  = body.get("items") or body
    if isinstance(raw, dict):
        if "results" in raw:
            raw = raw["results"][0].get("items", []) if raw["results"] else []
        elif "items" in raw:
            raw = raw["items"]
    if not isinstance(raw, list):
        return jsonify({"error": "items introuvable"}), 400
    mode = body.get("mode", "auto")

    def _best_image(it):
        og = it.get("og", {})
        if og.get("image"): return og["image"]
        imgs = it.get("images", [])
        for img in imgs:
            src = img.get("src","") if isinstance(img, dict) else str(img)
            if any(x in src.lower() for x in ["estate","sweepbright","cloudimg","property"]):
                return src
        for img in imgs[1:]:
            src = img.get("src","") if isinstance(img, dict) else str(img)
            if src.startswith("http") and "logo" not in src.lower():
                return src
        return imgs[0].get("src","") if imgs else ""

    def _best_link(it):
        og = it.get("og",{})
        if og.get("url"): return og["url"]
        lks = it.get("links",[])
        if lks:
            l = lks[1] if len(lks)>1 else lks[0]
            return l.get("href","") if isinstance(l,dict) else str(l)
        return it.get("url","")

    def _clean_name(it):
        og = it.get("og",{})
        t = og.get("title","")
        if t:
            t = t.split("|")[0].strip()
            t = re.sub(r"\d[\d\s]*[\u20ac$\xa3].*","",t).strip()
            t = re.sub(r"\s+"," ",t).strip()
            if t: return t
        lks = it.get("links",[])
        if len(lks)>1:
            n = lks[1].get("text","").split(",")[0].strip() if isinstance(lks[1],dict) else ""
            if n: return n
        return (it.get("title") or str(it.get("text",""))[:80] or "").strip()

    def _price(it):
        p = it.get("price","")
        if isinstance(p, list): p = p[0] if p else ""
        return str(p).strip().lstrip(", ")

    def _detect_mode(items):
        sample = " ".join(
            str(it.get("description",""))+str(it.get("fields",""))+str(it.get("text",""))
            for it in items[:5]
        ).lower()
        if any(k in sample for k in ["surface","dpe","pi\u00e8ce","m\u00b2","loyer","appartement","vente"]):
            return "immo"
        if any(k in sample for k in ["ram","ssd","processeur","ghz","reconditionne"]):
            return "pcmarket"
        return "generic"

    if mode == "auto":
        mode = _detect_mode(raw)

    out = []
    for it in raw:
        name  = _clean_name(it)
        if not name: continue
        price = _price(it)
        image = _best_image(it)
        link  = _best_link(it)
        desc  = str(it.get("description") or it.get("text",""))[:500]
        fields = it.get("fields",{}) or {}
        og     = it.get("og",{}) or {}
        entry = {"name":name,"price":price,"image":image,"link":link,"description":desc}
        if mode == "immo":
            dpe_m     = re.search(r"class[e\s]+([A-G])\b", desc, re.I) \
                     or re.search(r"DPE\s*:?\s*([A-G])\b", str(fields.get("dpe","")), re.I) \
                     or re.search(r"ABCDEF.*?([A-G])\b", str(fields.get("dpe","")))
            surface_m = re.search(r"(\d+)\s*m[\u00b22]", desc)
            pieces_m  = re.search(r"T-?(\d+)", og.get("title","")) \
                     or re.search(r"(\d+)\s*pi[e\u00e8]ce", desc) \
                     or re.search(r"(\d+)\s*pi\u00e8ces?", og.get("description",""))
            ref_raw   = og.get("url","").rstrip("/").split("/")[-1]
            ref_m     = re.search(r"([a-f0-9\-]{8,})", ref_raw)
            entry.update({
                "surface": surface_m.group(1)+"m\u00b2" if surface_m else str(fields.get("surface","")),
                "pieces":  pieces_m.group(1) if pieces_m else str(fields.get("pieces","")),
                "DPE":     dpe_m.group(1) if dpe_m else "",
                "ref":     ref_m.group(1)[:12] if ref_m else str(fields.get("ref","")),
            })
        elif mode == "pcmarket":
            entry.update({
                "processeur": str(fields.get("processeur","") or fields.get("cpu","")),
                "ram":        str(fields.get("ram","")),
                "ssd":        str(fields.get("ssd","") or fields.get("stockage","")),
                "ecran":      str(fields.get("ecran","")),
                "grade":      str(fields.get("grade","")),
            })
        else:
            entry.update({k: str(v) for k,v in fields.items() if v})
        out.append(entry)

    return jsonify({
        "ok":True,"mode":mode,"count":len(out),"items":out,
        "_meta":{"source_count":len(raw),"converted":len(out),"mode":mode}
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
