# © Sabino Gervasio
"""
Suno Daily Credits Wizard
Consuma SOLO i crediti giornalieri gratuiti (30/day, verificato 2026-05-31).
1 gen = 2 canzoni = 10 crediti → 3 generazioni = 6 canzoni al giorno.
Input: prompt/lirics + titolo + stile → Output: 2 versioni MP3 scaricate.
"""
import os
import asyncio
import json
import sys
import re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness")))

from playwright.async_api import async_playwright

SUNO_COOKIES = Path(os.getenv("SUNO_COOKIES", str(Path.home() / "suno_cookies.json")))
OUTPUT_DIR   = MUSIC_DIR / "DISTRO_READY"
SS_DIR       = MUSIC_DIR / "screenshots/suno"
LOG_FILE     = MUSIC_DIR / "suno_daily_log.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SS_DIR.mkdir(parents=True, exist_ok=True)


# ─── CONFIG ──────────────────────────────────────────────────────────────────
DEFAULT_STYLE = "Italian Pop, melodico, voce femminile, produzione moderna"

SONG_QUEUE = [
    # Aggiungi qui canzoni da generare oggi
    # {"title": "Titolo", "lyrics": "...", "style": "..."},
]


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def load_cookies() -> list:
    if not SUNO_COOKIES.exists():
        return []
    raw = json.loads(SUNO_COOKIES.read_text("utf-8"))
    cks = raw.get("cookies", raw) if isinstance(raw, dict) else raw
    out = []
    for c in cks:
        c = dict(c)
        ss = c.get("sameSite", "")
        c["sameSite"] = {"lax": "Lax", "strict": "Strict", "none": "None",
                         "no_restriction": "None", "unspecified": "Lax"}.get(
                             ss.lower() if isinstance(ss, str) else "", "Lax")
        for k in ("hostOnly", "session", "storeId", "id"):
            c.pop(k, None)
        out.append(c)
    return out


def save_log(entries: list):
    existing = []
    if LOG_FILE.exists():
        existing = json.loads(LOG_FILE.read_text("utf-8"))
    existing.extend(entries)
    LOG_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), "utf-8")


def sanitize_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", s).strip()[:60]


# ─── CORE ────────────────────────────────────────────────────────────────────
async def check_credits(page) -> int:
    """Leggi i crediti rimanenti dalla UI di Suno."""
    try:
        await page.wait_for_timeout(2000)
        # Cerca il contatore crediti nella sidebar
        for sel in ['[class*="credit"]', '[data-testid*="credit"]',
                    'span:has-text("credits")', 'div:has-text("/ 50")']:
            el = await page.query_selector(sel)
            if el:
                txt = await el.inner_text()
                nums = re.findall(r'\d+', txt)
                if nums:
                    return int(nums[0])
    except Exception:
        pass
    return -1  # unknown


async def generate_song(page, title: str, lyrics: str, style: str = DEFAULT_STYLE) -> list[str]:
    """
    Genera una canzone su Suno e restituisce i path dei 2 MP3 scaricati.
    Ogni generazione usa 5 crediti → 2 varianti.
    """
    print(f"\n[SUNO] Generazione: {title!r}")

    # Naviga alla pagina create
    await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    await page.screenshot(path=str(SS_DIR / f"{sanitize_filename(title)}_01_create.png"))

    # Attiva "Custom Mode" se non attivo
    try:
        custom_btn = await page.query_selector('button:has-text("Custom")')
        if custom_btn:
            is_active = await custom_btn.get_attribute("aria-pressed") or ""
            if "true" not in is_active.lower():
                await custom_btn.click()
                await page.wait_for_timeout(1000)
                print("[SUNO] Custom mode attivato")
    except Exception:
        pass

    # Inserisci lyrics
    for sel in ['textarea[placeholder*="Enter"]', 'textarea[placeholder*="lyrics"]',
                'textarea[placeholder*="Lyrics"]', 'textarea']:
        lyrics_field = await page.query_selector(sel)
        if lyrics_field and await lyrics_field.is_visible():
            await lyrics_field.fill(lyrics)
            print(f"[SUNO] Lyrics inserite ({len(lyrics)} chars)")
            break

    # Inserisci stile
    for sel in ['input[placeholder*="style"]', 'input[placeholder*="Style"]',
                'textarea[placeholder*="style"]']:
        style_field = await page.query_selector(sel)
        if style_field and await style_field.is_visible():
            await style_field.fill(style)
            print(f"[SUNO] Stile: {style[:50]}")
            break

    # Inserisci titolo
    for sel in ['input[placeholder*="title"]', 'input[placeholder*="Title"]',
                'input[name="title"]']:
        title_field = await page.query_selector(sel)
        if title_field and await title_field.is_visible():
            await title_field.fill(title)
            print(f"[SUNO] Titolo: {title}")
            break

    await page.screenshot(path=str(SS_DIR / f"{sanitize_filename(title)}_02_filled.png"))

    # Clicca Create
    created = False
    for sel in ['button:has-text("Create")', 'button:has-text("Generate")',
                'button[type="submit"]']:
        btn = await page.query_selector(sel)
        if btn and await btn.is_visible():
            await btn.click()
            print("[SUNO] Create cliccato, attendo generazione...")
            created = True
            break

    if not created:
        print("[SUNO] ERRORE: bottone Create non trovato")
        return []

    # Attendi completamento (max 3 minuti)
    for i in range(36):
        await page.wait_for_timeout(5000)
        # Cerca indicatori di completamento
        done_sels = ['button:has-text("Download")', '[aria-label*="Download"]',
                     'button:has-text("Share")', '.song-card', '[class*="songCard"]']
        for ds in done_sels:
            el = await page.query_selector(ds)
            if el:
                print(f"[SUNO] Generazione completata (~{(i+1)*5}s)")
                break
        else:
            if i % 6 == 5:
                print(f"[SUNO] Attendo... {(i+1)*5}s")
            continue
        break

    await page.screenshot(path=str(SS_DIR / f"{sanitize_filename(title)}_03_generated.png"))

    # Download entrambe le versioni
    downloaded = []
    download_btns = await page.query_selector_all('button:has-text("Download"), [aria-label*="Download"]')
    print(f"[SUNO] Trovati {len(download_btns)} bottoni download")

    for i, btn in enumerate(download_btns[:2]):
        try:
            version = i + 1
            fname = sanitize_filename(f"{title}_v{version}_{datetime.now().strftime('%Y%m%d')}.mp3")
            fpath = OUTPUT_DIR / fname

            async with page.expect_download() as dl_info:
                await btn.click()
            download = await dl_info.value
            await download.save_as(str(fpath))
            downloaded.append(str(fpath))
            print(f"[SUNO] Scaricata versione {version}: {fpath.name}")
        except Exception as e:
            print(f"[SUNO] Errore download v{i+1}: {e}")

    return downloaded


# ─── MAIN ────────────────────────────────────────────────────────────────────
async def main(songs: list[dict] = None):
    if songs is None:
        songs = SONG_QUEUE

    if not songs:
        print("[WIZARD] Nessuna canzone in coda. Aggiungi a SONG_QUEUE o passa lista.")
        print("Esempio:")
        print('  python suno_daily_wizard.py')
        print('  Oppure importa e chiama: asyncio.run(main([{"title":"X","lyrics":"...","style":"..."}]))')
        return

    cookies = load_cookies()
    log_entries = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=100)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})

        if cookies:
            try:
                await ctx.add_cookies(cookies)
                print(f"[AUTH] {len(cookies)} cookies caricati")
            except Exception as e:
                print(f"[AUTH] Cookie error: {e}")

        page = await ctx.new_page()

        # Login check
        await page.goto("https://suno.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if "login" in page.url.lower() or "sign" in page.url.lower():
            print("[AUTH] Sessione scaduta. Aggiorna suno_cookies.json")
            print("[AUTH] Esegui: python capture_suno_cookies.py")
            await browser.close()
            return

        credits = await check_credits(page)
        print(f"[CREDITS] Crediti disponibili: {credits if credits >= 0 else 'n/a'}")

        credits_needed = len(songs) * 5
        if credits >= 0 and credits < credits_needed:
            print(f"[WARN] Crediti insufficienti: hai {credits}, servono {credits_needed}")
            songs = songs[:credits // 5]
            print(f"[WARN] Genero solo {len(songs)} canzoni")

        for song in songs:
            title  = song.get("title", f"Track_{datetime.now().strftime('%H%M%S')}")
            lyrics = song.get("lyrics", "")
            style  = song.get("style", DEFAULT_STYLE)

            files = await generate_song(page, title, lyrics, style)

            log_entries.append({
                "timestamp": datetime.now().isoformat(),
                "title": title,
                "style": style,
                "files": files,
                "ok": len(files) > 0,
            })

            await page.wait_for_timeout(2000)

        await browser.close()

    save_log(log_entries)
    ok = [e for e in log_entries if e["ok"]]
    print(f"\n[DONE] {len(ok)}/{len(log_entries)} canzoni generate con successo")
    for e in ok:
        for f in e["files"]:
            print(f"  → {f}")


if __name__ == "__main__":
    asyncio.run(main())
