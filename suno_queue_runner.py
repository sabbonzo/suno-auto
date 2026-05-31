# © Sabino Gervasio
"""
suno_queue_runner.py — Consuma 10 post dalla queue blog e genera canzoni su Suno.
Input:  suno_queue_master.json (tutti i blog) oppure suno_queue_from_blog.json
Output: MP3 in DISTRO_READY/, queue aggiornata (done=true), gumroad_music_queue.json

30 crediti/giorno (piano free, verificato 2026-05-31).
1 generazione = 2 canzoni = 10 crediti → 3 gen/giorno = 6 canzoni max.
"""
import os
import asyncio, json, sys, re, urllib.request
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

# Usa queue master se disponibile, altrimenti legacy
_QM = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/suno_queue_master.json")
_QL = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/suno_queue_from_blog.json")
QUEUE_FILE    = _QM if _QM.exists() else _QL
OUTPUT_DIR    = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/DISTRO_READY")
LOG_FILE      = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/suno_daily_log.json")
GUMROAD_QUEUE = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/gumroad_music_queue.json")
SUNO_PROFILE  = Path("os.getenv("USER_HOME", str(Path.home())) + "/AppData/Local/os.getenv("SUNO_PROFILE", "suno_profile")")
DEBUG_SS_DIR  = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/screenshots/suno")  # solo per errori gravi

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_SS_DIR.mkdir(parents=True, exist_ok=True)

DAILY_LIMIT     = 6    # canzoni per run (30 crediti / 10 per gen × 2 canzoni/gen)
PAGE_LOAD_WAIT  = 5000  # ms dopo goto /create — React lento a idratare
CUSTOM_WAIT     = 1000  # ms dopo click Custom Mode
FIELD_WAIT      = 300   # ms tra un campo e l'altro
GEN_POLL_MS     = 8000  # ms tra ogni check generazione
GEN_MAX_POLLS   = 45    # max 45 × 8s = 6 minuti (Free plan può essere lento)
BETWEEN_SONGS   = 5000  # ms di pausa cortesia tra una canzone e l'altra
MIN_CREDITS     = 10    # ferma se crediti < 10 (1 gen costa 10 crediti)


def load_cookies():
    if not COOKIES_FILE.exists():
        print(f"❌ Cookie mancanti: {COOKIES_FILE}")
        print("   Esegui: python os.getenv("USER_HOME", str(Path.home())) + "/renew_suno_cookies.py")
        return []
    raw = json.loads(COOKIES_FILE.read_text("utf-8"))
    cks = raw.get("cookies", raw) if isinstance(raw, dict) else raw
    m = {"lax":"Lax","strict":"Strict","none":"None","no_restriction":"None","unspecified":"Lax"}
    out = []
    for c in cks:
        c = dict(c)
        c["sameSite"] = m.get(c.get("sameSite","").lower(), "Lax") if isinstance(c.get("sameSite"), str) else "Lax"
        for k in ("hostOnly","session","storeId","id"):
            c.pop(k, None)
        out.append(c)
    return out


def load_queue(limit=DAILY_LIMIT):
    """Carica i prossimi N post non ancora processati."""
    data = json.loads(QUEUE_FILE.read_text("utf-8"))
    pending = [item for item in data if not item.get("done", False)]
    return pending[:limit], data


def mark_done(data, title):
    for item in data:
        if item.get("title") == title:
            item["done"] = True
            item["done_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    QUEUE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def sanitize(s):
    return re.sub(r'[<>:"/\\|?*]', "", s).strip()[:55]


def append_log(entry):
    logs = []
    if LOG_FILE.exists():
        logs = json.loads(LOG_FILE.read_text("utf-8"))
    logs.append(entry)
    LOG_FILE.write_text(json.dumps(logs, indent=2, ensure_ascii=False), "utf-8")


def append_gumroad_queue(title: str, files: list, style: str, blog: str):
    """Aggiunge MP3 creati alla coda di upload Gumroad."""
    entries = []
    if GUMROAD_QUEUE.exists():
        entries = json.loads(GUMROAD_QUEUE.read_text("utf-8"))
    for f in files:
        path = Path(f)
        if path.exists() and path.stat().st_size > 100_000:  # solo file validi >100KB
            entries.append({
                "title":    title,
                "file":     str(path),
                "style":    style,
                "blog":     blog,
                "price":    0.99,
                "currency": "EUR",
                "added":    datetime.now().strftime("%Y-%m-%d %H:%M"),
                "uploaded": False,
            })
    GUMROAD_QUEUE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), "utf-8")


async def click_first_visible(page, selectors, label="button"):
    """Cerca e clicca il primo selettore visibile dalla lista. Ritorna True se cliccato."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.click()
                return True
        except:
            continue
    return False


async def fill_first_visible(page, selectors, value, label="field"):
    """Riempie il primo campo visibile dalla lista.
    Strategia: fill() → Ctrl+A+type → JS injection (React onChange).
    Ritorna True se riempito."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.click()
                # Tentativo 1: fill() standard
                try:
                    await el.fill(value)
                    await page.wait_for_timeout(200)
                    current = await el.input_value() if label != "lyrics" else ""
                    if current and len(current) > 3:
                        return True
                except:
                    pass
                # Tentativo 2: Ctrl+A poi type (per React controlled inputs)
                try:
                    await el.press("Control+a")
                    await page.wait_for_timeout(100)
                    await el.press_sequentially(value, delay=15)
                    await page.wait_for_timeout(200)
                    return True
                except:
                    pass
                # Tentativo 3: JS injection — triggera React onChange
                try:
                    await page.evaluate("""(args) => {
                        const el = document.querySelector(args.sel);
                        if (!el) return;
                        const nativeInput = Object.getOwnPropertyDescriptor(
                            window[el.tagName === 'TEXTAREA' ? 'HTMLTextAreaElement' : 'HTMLInputElement'].prototype, 'value');
                        nativeInput.set.call(el, args.val);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""", {"sel": sel, "val": value})
                    await page.wait_for_timeout(200)
                    return True
                except:
                    pass
        except:
            continue
    return False


async def fill_style_field(page, style: str) -> bool:
    """Strategia dedicata per il campo Styles di Suno v4.5.
    Il campo appare sotto le Lyrics in Advanced mode e può richiedere
    un click sul header 'Styles' per espandersi."""
    # 1. Prova click sul bottone/header "Styles" per espandere la sezione
    for style_header in [
        'button:has-text("Styles")', 'div:has-text("Styles")',
        '[aria-label*="Style" i]', 'label:has-text("Style")',
    ]:
        try:
            h = page.locator(style_header).first
            if await h.count() > 0 and await h.is_visible():
                await h.click()
                await page.wait_for_timeout(600)
                break
        except:
            pass

    # 2. Selettori possibili per il campo stile in Suno v4.5
    style_sels = [
        'input[placeholder*="style" i]',
        'input[placeholder*="Style" i]',
        'input[placeholder*="genre" i]',
        'input[placeholder*="tag" i]',
        'textarea[placeholder*="style" i]',
        'input[aria-label*="style" i]',
        'input[aria-label*="Style" i]',
        'input[data-testid*="style" i]',
        # Suno v4.5: il campo potrebbe essere un input generico
        # dopo il textarea delle lyrics
        'div.style-input input',
        'section:has(h3:has-text("Style")) input',
        'section:has(span:has-text("Style")) input',
    ]
    ok = await fill_first_visible(page, style_sels, style, "style")
    if not ok:
        # 3. Fallback: trova tutti gli input visibili nella pagina e usa il secondo
        # (il primo è tipicamente il Lyrics o il Title)
        try:
            inputs = page.locator('input:visible, textarea:visible')
            count = await inputs.count()
            for i in range(count):
                inp = inputs.nth(i)
                ph = await inp.get_attribute("placeholder") or ""
                aria = await inp.get_attribute("aria-label") or ""
                if any(w in (ph + aria).lower() for w in ["style", "genre", "tag", "music"]):
                    await inp.click()
                    await inp.press("Control+a")
                    await inp.press_sequentially(style, delay=12)
                    await page.wait_for_timeout(200)
                    print(f"     ✅ Style compilato via fallback input #{i}")
                    return True
        except:
            pass
    return ok


async def generate_song(page, title, lyrics, style):
    """Genera canzone su Suno e scarica i 2 MP3. Nessuno screenshot — solo log."""
    safe = sanitize(title)
    t0 = datetime.now()
    print(f"\n  [{t0:%H:%M:%S}] {title[:50]!r}  ({len(lyrics)} chars)")

    # ── 1. Naviga su /create — domcontentloaded è più stabile di networkidle
    # Suno ha richieste continue in background che fanno scadere networkidle
    for _nav_attempt in range(3):
        try:
            await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=60000)
            break
        except Exception as nav_err:
            if _nav_attempt == 2:
                raise
            print(f"     ⚠️  goto timeout (tentativo {_nav_attempt+1}/3), riprovo...")
            await page.wait_for_timeout(3000)
    await page.wait_for_timeout(PAGE_LOAD_WAIT)
    # Reload esplicito: evita stato React stantio dopo molte canzoni consecutive
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except:
        pass
    await page.wait_for_timeout(3000)

    # ── 2. Attiva Advanced Mode (Suno v4.5: "Simple" | "Advanced") ───
    try:
        adv = page.locator('button[aria-label="Advanced"], button:has-text("Advanced")').first
        if await adv.count() > 0:
            # Controlla se già attivo (aria-pressed o aria-selected)
            pressed = (await adv.get_attribute("aria-pressed") or
                       await adv.get_attribute("aria-selected") or "false")
            if "true" not in pressed.lower():
                await adv.click()
                await page.wait_for_timeout(CUSTOM_WAIT)
    except:
        pass

    # ── 3. Click "Lyrics" per mostrare la textarea ────────────────────
    # In Advanced mode c'è un bottone "Lyrics" / "Add your own lyrics"
    for _ly_btn_attempt in range(3):
        try:
            ly_btn = page.locator(
                'button[aria-label*="your own lyrics" i], button:has-text("Lyrics")'
            ).first
            if await ly_btn.count() > 0 and await ly_btn.is_visible():
                await ly_btn.click()
                await page.wait_for_timeout(800)
            break
        except:
            await page.wait_for_timeout(1000)

    # ── 4. Compila Lyrics — con retry se campo non ancora renderizzato ────
    lyrics_sels = [
        'textarea[placeholder*="rics" i]',
        'textarea[placeholder*="Enter" i]',
        'textarea[placeholder*="testo" i]',
        'div[contenteditable="true"][aria-label*="rics" i]',
        'div[contenteditable="true"]',
    ]
    ok_lyrics = False
    for _lyrics_attempt in range(4):
        ok_lyrics = await fill_first_visible(page, lyrics_sels, lyrics, "lyrics")
        if ok_lyrics:
            break
        print(f"     ⏳ Lyrics field non ancora visibile (tentativo {_lyrics_attempt+1}/4)...")
        # Re-click Advanced e Lyrics per assicurarsi che il form sia aperto
        try:
            adv2 = page.locator('button[aria-label="Advanced"], button:has-text("Advanced")').first
            if await adv2.count() > 0:
                await adv2.click()
                await page.wait_for_timeout(1500)
        except:
            pass
        try:
            ly2 = page.locator(
                'button[aria-label*="your own lyrics" i], button:has-text("Lyrics")'
            ).first
            if await ly2.count() > 0:
                await ly2.click()
                await page.wait_for_timeout(1500)
        except:
            pass
        await page.wait_for_timeout(2000)

    await page.wait_for_timeout(FIELD_WAIT)
    if not ok_lyrics:
        print("     ⚠️  Lyrics field non trovato dopo 4 tentativi")

    # ── 5. Compila Style — usa strategia dedicata multi-tentativo ────────
    ok_style = await fill_style_field(page, style)
    if not ok_style:
        print("     ⚠️  Style field non trovato — canzone senza stile personalizzato")
    else:
        print(f"     ✅ Style: {style[:60]}...")
    await page.wait_for_timeout(FIELD_WAIT)

    # ── 6. Compila Title (opzionale) ──────────────────────────────────
    title_sels = [
        'input[placeholder*="itle" i]',
        'input[name="title"]',
    ]
    await fill_first_visible(page, title_sels, title[:50], "title")
    await page.wait_for_timeout(FIELD_WAIT)

    # ── 7. Click Create — aspetta che si abiliti ──────────────────────
    # Il bottone ha aria-label="Create song" ed è disabled finché il form è vuoto
    create_btn = page.locator('button[aria-label="Create song"]').first
    created = False

    # Aspetta max 8s che diventi abilitato (triplo check: disabled attr + aria-disabled + is_enabled)
    for _ in range(8):
        if await create_btn.count() > 0:
            disabled  = await create_btn.get_attribute("disabled")
            aria_dis  = await create_btn.get_attribute("aria-disabled")
            is_en     = await create_btn.is_enabled()
            if disabled is None and aria_dis != "true" and is_en:
                try:
                    await create_btn.click()
                    created = True
                    break
                except:
                    pass
        await page.wait_for_timeout(1000)

    if not created:
        # Fallback testuale
        created = await click_first_visible(page, [
            'button:has-text("Create"):not([disabled])',
            'button[aria-label*="create" i]:not([disabled])',
        ], "Create fallback")

    if not created:
        # Ultimo fallback JS — cerca il bottone Create abilitato
        try:
            done = await page.evaluate("""() => {
                const b = [...document.querySelectorAll('button')]
                    .find(b => b.getAttribute('aria-label') === 'Create song' && !b.disabled);
                if (b) { b.click(); return true; }
                return false;
            }""")
            created = bool(done)
        except:
            pass

    if not created:
        print("     ❌ Create non cliccato — salto")
        await page.screenshot(path=str(DEBUG_SS_DIR / f"ERR_{safe}_create_missing.png"))
        return []

    print(f"     Create cliccato — attendo generazione (max {GEN_MAX_POLLS * GEN_POLL_MS // 1000}s)...")

    # ── 7. Attendi generazione ────────────────────────────────────────
    # Suno Free: tipicamente 90-180s. Controlliamo la comparsa di card audio o progress
    GEN_SELECTORS = [
        'audio[src]',                          # audio player con src = generazione pronta
        '[class*="AudioPlayer"]',
        '[class*="audioPlayer"]',
        '[class*="SongCard"]',
        '[class*="songCard"]',
        '[class*="ClipCard"]',
        'button[aria-label*="play" i]',
        'button[aria-label*="download" i]',
        '[data-testid*="song"]',
        '[data-testid*="clip"]',
    ]
    generated = False
    for i in range(GEN_MAX_POLLS):
        await page.wait_for_timeout(GEN_POLL_MS)
        for sel in GEN_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    generated = True
                    break
            except:
                continue
        if generated:
            elapsed = (i + 1) * GEN_POLL_MS // 1000
            print(f"     Generata in ~{elapsed}s")
            break
        # Log ogni 40s
        if (i + 1) % 5 == 0:
            elapsed = (i + 1) * GEN_POLL_MS // 1000
            print(f"     Attendo... {elapsed}s")

    if not generated:
        print(f"     ⚠️  Timeout generazione — retry (reload pagina)...")
        await page.reload(wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        for i in range(5):
            await page.wait_for_timeout(GEN_POLL_MS)
            for sel in GEN_SELECTORS:
                try:
                    if await page.locator(sel).count() > 0:
                        generated = True
                        break
                except:
                    continue
            if generated:
                print(f"     Generata al retry in ~{(i+1)*GEN_POLL_MS//1000}s")
                break
        if not generated:
            print(f"     ❌ Timeout definitivo ({(GEN_MAX_POLLS+5) * GEN_POLL_MS // 1000}s)")
            await page.screenshot(path=str(DEBUG_SS_DIR / f"ERR_{safe}_gen_timeout.png"))
            return []

    # ── Attendi encoding CDN Suno (35s) ─────────────────────────────
    # La card appare subito ma il CDN non ha ancora encodato → 4844B stub.
    print(f"     ⏳ Attendo encoding CDN (35s)...")
    await page.wait_for_timeout(35000)

    # ── 8. Download con retry ────────────────────────────────────────
    downloaded = []

    GET_AUDIO_JS = """() => {
        const seen = new Set();
        const urls = [];
        document.querySelectorAll('audio[src]').forEach(el => {
            if (el.src && !seen.has(el.src)) { seen.add(el.src); urls.push(el.src); }
        });
        document.querySelectorAll('source[src]').forEach(el => {
            if (el.src && !seen.has(el.src)) { seen.add(el.src); urls.push(el.src); }
        });
        document.querySelectorAll('[data-src*=".mp3"],[src*="cdn.suno"],[src*="audiopipe"]').forEach(el => {
            const s = el.dataset?.src || el.src || el.getAttribute('src');
            if (s && !seen.has(s)) { seen.add(s); urls.push(s); }
        });
        return urls.slice(0, 4);
    }"""

    for dl_attempt in range(3):
        audio_urls = await page.evaluate(GET_AUDIO_JS)
        for idx, url in enumerate(audio_urls[:2]):
            if len(downloaded) >= 2:
                break
            fname = f"{safe}_v{idx+1}.mp3"
            dest = OUTPUT_DIR / fname
            if dest.exists() and dest.stat().st_size > 100_000:
                downloaded.append(str(dest))
                continue
            try:
                resp = await page.context.request.get(url, timeout=90000)
                ct = resp.headers.get("content-type", "")
                body = await resp.body()
                if len(body) > 100_000:
                    dest.write_bytes(body)
                    downloaded.append(str(dest))
                    print(f"     Salvato: {fname} ({len(body)//1024} KB)")
                else:
                    if dl_attempt < 2:
                        print(f"     ↺  URL {idx+1} stub ({len(body)}B) — retry in 30s")
                    else:
                        print(f"     ⚠️  URL {idx+1} fallito definitivamente ({len(body)}B)")
            except Exception as e:
                print(f"     ⚠️  Audio URL {idx+1}: {str(e)[:60]}")
        if len(downloaded) >= 1:
            break
        if dl_attempt < 2:
            await page.wait_for_timeout(30000)
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

    # Strategia B: bottoni Download con hover sulle card
    if len(downloaded) < 2:
        cards = await page.locator(
            '[class*="SongCard"], [class*="songCard"], [class*="ClipCard"], [class*="clipCard"]'
        ).all()
        for card in cards[:2]:
            if len(downloaded) >= 2:
                break
            try:
                await card.hover()
                await page.wait_for_timeout(600)
                # Bottone download diretto
                dl_btn = None
                for sel in ['button[aria-label*="download" i]', '[data-testid*="download"]',
                            'a[download]', 'a[href$=".mp3"]']:
                    el = card.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        dl_btn = el
                        break
                # Menu "..." come fallback
                if not dl_btn:
                    for msel in ['button[aria-label*="more" i]', 'button[aria-label*="options" i]',
                                 'button:has-text("⋯")', 'button:has-text("…")']:
                        mb = card.locator(msel).first
                        if await mb.count() > 0:
                            await mb.click()
                            await page.wait_for_timeout(400)
                            for isel in ['[role="menuitem"]:has-text("Download")',
                                         'a:has-text("Download")', 'button:has-text("Download")']:
                                el = page.locator(isel).first
                                if await el.count() > 0:
                                    dl_btn = el
                                    break
                            break
                if dl_btn:
                    idx = len(downloaded)
                    async with page.expect_download(timeout=45000) as dl_info:
                        await dl_btn.click()
                    dl = await dl_info.value
                    fname = f"{safe}_v{idx+1}.mp3"
                    dest = OUTPUT_DIR / fname
                    await dl.save_as(str(dest))
                    size_kb = dest.stat().st_size // 1024
                    downloaded.append(str(dest))
                    print(f"     Salvato (btn): {fname} ({size_kb} KB)")
                    await page.wait_for_timeout(1500)
            except Exception as e:
                print(f"     ⚠️  Card download: {str(e)[:70]}")

    elapsed_total = (datetime.now() - t0).seconds
    if downloaded:
        print(f"     {len(downloaded)} file in {elapsed_total}s")
    else:
        print(f"     ⚠️  Nessun download in {elapsed_total}s")
        await page.screenshot(path=str(DEBUG_SS_DIR / f"ERR_{safe}_no_download.png"))

    return downloaded


async def get_credits(page) -> int:
    """Legge i crediti rimanenti dalla UI Suno. Ritorna -1 se non trovato."""
    try:
        # Suno mostra i crediti nel menu utente o in un badge visibile
        for sel in [
            '[data-testid*="credit"]',
            'span:has-text("Credits")',
            'div:has-text("Credits")',
            '[class*="credit"]',
        ]:
            elems = page.locator(sel)
            if await elems.count() > 0:
                txt = await elems.first.text_content()
                nums = re.findall(r'\d+', txt or "")
                if nums:
                    return int(nums[0])
        # Fallback: cerca nel DOM qualsiasi numero vicino a "credit"
        content = await page.content()
        m = re.search(r'(\d+)\s*[Cc]redit', content)
        if m:
            return int(m.group(1))
    except:
        pass
    return -1


async def main():
    print("=" * 60)
    print(f"  SUNO QUEUE RUNNER — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Daily limit: {DAILY_LIMIT} canzoni (50 crediti)")
    print("=" * 60)

    batch, all_data = load_queue(DAILY_LIMIT)
    total_pending = sum(1 for i in all_data if not i.get("done"))
    print(f"  📋 Queue: {len(batch)} da processare oggi | {total_pending} totali pending")

    if not batch:
        print("  ✅ Queue vuota! Tutti i post processati.")
        return

    session_log = []

    async with async_playwright() as pw:
        # Usa profilo persistente per preservare localStorage+cookies Clerk
        ctx = await pw.chromium.launch_persistent_context(
            str(SUNO_PROFILE),
            headless=False,
            slow_mo=80,  # ridotto: meno attesa tra ogni azione
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Verifica login — cerca avatar utente o menu account
        await page.goto("https://suno.com", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        logged_in = False
        for sel in ['[data-testid="user-menu"]', 'button[aria-label*="account"]',
                    'img[alt*="avatar"]', 'a[href*="/profile"]', '.user-avatar',
                    '[class*="UserButton"]', 'button:has-text("soundbonzo")']:
            try:
                if await page.locator(sel).count() > 0:
                    logged_in = True
                    break
            except:
                pass
        if not logged_in:
            # Check if we see any sign of being logged in via page content
            content = await page.content()
            if any(k in content for k in ["soundbonzo", "my-library", "my_library"]):
                logged_in = True
        if not logged_in:
            print("  ❌ Suno: non loggato. Apri suno.com manualmente e fai login.")
            print("     Profile:", SUNO_PROFILE)
            await ctx.close()
            return
        print("  ✅ Suno login OK (profilo persistente)")

        for idx, item in enumerate(batch):
            title  = item.get("title", f"Canzone {idx+1}")
            lyrics = item.get("lyrics", item.get("excerpt", ""))
            style  = item.get("style",
                              "Italian pop cantautorale, voce maschile autentica, "
                              "chitarra acustica, piano, 90bpm, melodico, sincero")

            print(f"\n  [{idx+1}/{len(batch)}] {title}")

            # ── Controlla crediti rimanenti prima di ogni canzone ──────────────
            credits = await get_credits(page)
            if credits != -1:
                print(f"     💳 Crediti rimanenti: {credits}")
                if credits < MIN_CREDITS:
                    print(f"  ⛽ Crediti insufficienti ({credits} < {MIN_CREDITS}).")
                    print(f"     La schedulazione alle 09:00 riprenderà domani.")
                    session_log.append({
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "title": "__STOP__",
                        "status": "no_credits",
                        "credits_remaining": credits
                    })
                    break

            try:
                files = await generate_song(page, title, lyrics, style)
                mark_done(all_data, title)
                entry = {
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "title": title,
                    "files": files,
                    "status": "ok" if files else "no_download"
                }
                session_log.append(entry)
                if files:
                    append_gumroad_queue(title, files, style, item.get("blog", "sabbonzo"))
                print(f"  ✅ {title}: {len(files)} file scaricati")
            except Exception as e:
                print(f"  ❌ {title}: {e}")
                session_log.append({"date": datetime.now().strftime("%Y-%m-%d"),
                                   "title": title, "status": "error", "error": str(e)})

            await page.wait_for_timeout(BETWEEN_SONGS)

        await ctx.close()

    # Log sessione
    for entry in session_log:
        append_log(entry)

    print("\n" + "=" * 60)
    print("  SESSIONE COMPLETATA")
    ok = sum(1 for e in session_log if e.get("status") == "ok")
    print(f"  ✅ {ok}/{len(batch)} canzoni generate con successo")
    still_pending = sum(1 for i in all_data if not i.get("done"))
    print(f"  📋 Rimanenti in queue: {still_pending}/427")
    print(f"  📁 Output: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
