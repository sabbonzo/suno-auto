# © Sabino Gervasio
"""
suno_blog_pipeline.py — Scrapa tutti i blog di Sabino, inferisce lo stile,
merge post corti, rima, traduzione EN opzionale → suno_queue_master.json

Blog target:
  1. sabbonzo.blogspot.com      (poesie/diario personale)
  2. rainboworlds.blogspot.com  (fantasy narrativo)
  3. lisiaskycloud.blogspot.com (fantasy RPG)
  4. darksun2009.blogspot.com   (Dark Sun D&D)
"""
import os
import json, re, html, time, urllib.request, sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── Percorsi ──────────────────────────────────────────────────────────────────
QUEUE_MASTER  = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/suno_queue_master.json")
QUEUE_LEGACY  = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/suno_queue_from_blog.json")
GUMROAD_QUEUE = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/gumroad_music_queue.json")

# ── Blog da scrapare ──────────────────────────────────────────────────────────
BLOGS = [
    {"id": "sabbonzo",     "url": "https://sabbonzo.blogspot.com",     "theme": "diary"},
    {"id": "rainboworlds", "url": "https://rainboworlds.blogspot.com",  "theme": "fantasy"},
    {"id": "lisiaskycloud","url": "https://lisiaskycloud.blogspot.com", "theme": "fantasy"},
    {"id": "darksun2009",  "url": "https://darksun2009.blogspot.com",   "theme": "dark_fantasy"},
]

MIN_CHARS      = 250   # soglia merge: post < MIN_CHARS vengono uniti al successivo
MAX_MERGE      = 3     # max post da unire
EN_RATIO       = 0.15  # ~15% canzoni tradotte in inglese
RHYME_RATE     = 0.80  # 80% delle canzoni devono avere rima
FANTASY_RATIO  = 0.25  # 25% dei post riceve trattamento fantasy/creativo casuale
LYRICS_MAX     = 2400  # chars massimi di lyrics (safe per durata Suno ~4min)


# ═════════════════════════════════════════════════════════════════════════════
# HTML CLEANER
# ═════════════════════════════════════════════════════════════════════════════
def clean_html(raw: str) -> str:
    """Rimuove tag HTML, decode entità, normalizza spazi."""
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\xa0', ' ', text)          # &nbsp;
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ═════════════════════════════════════════════════════════════════════════════
# STYLE INFERRER
# ═════════════════════════════════════════════════════════════════════════════
def infer_style(title: str, text: str, blog_theme: str, lang: str) -> str:
    """Regola: ogni stile DEVE includere voce, strumenti, bpm/energia, genere."""
    t = (title + " " + text).lower()

    if lang == "en":
        if any(w in t for w in ["dragon", "sword", "quest", "dark", "magic", "warrior"]):
            return ("English epic fantasy metal, male baritone vocals, orchestra strings, "
                    "power guitar, cinematic drums, 140bpm, dramatic, powerful")
        if any(w in t for w in ["love", "heart", "kiss", "dream", "soul", "forever"]):
            return ("English indie pop, male tenor vocals, acoustic guitar, light piano, "
                    "soft drums, 88bpm, warm, emotional, intimate")
        return ("English indie folk, male vocals, acoustic guitar, fingerpicking, "
                "ambient synth, 75bpm, introspective, lo-fi warmth")

    # Dark / gothic
    if any(w in t for w in ["tenebre", "morte", "buio", "oscuro", "sangue",
                             "diavolo", "male", "ombra", "paura", "caduto"]):
        return ("Italian dark pop, voce maschile bassa intensa, chitarra distorta, "
                "basso pesante, batteria incalzante, 100bpm, atmosfera notturna, tensione")

    # Fantasy / adventure
    if blog_theme in ("fantasy", "dark_fantasy") or any(
            w in t for w in ["drago", "elfi", "guerriero", "magia", "regno",
                             "spada", "destino", "missione", "arena"]):
        if "dark" in blog_theme:
            return ("Italian dark epic metal, cori drammatici maschili e femminili, "
                    "chitarre pesanti drop-D, archi orchestrali, organo, 135bpm, maestoso")
        return ("Italian epic fantasy, voce tenore maschile eroica, archi e cori orchestrali, "
                "tamburi cinematici, flauto celtico, 120bpm, epico, avventuroso")

    # Spiritual / religious
    if any(w in t for w in ["dio", "anima", "preghiera", "cielo", "fede",
                             "signore", "grazia", "eterno", "divino"]):
        return ("Italian cantautore spirituale, voce maschile raccolta e intensa, "
                "chitarra acustica fingerpicking, cori gospel femminili, piano, 70bpm, devoto")

    # Sea / summer / nature
    if any(w in t for w in ["mare", "sole", "estate", "vento", "spiaggia",
                             "onda", "azzurro", "cielo", "primavera"]):
        return ("Italian pop mediterraneo, voce maschile calda, chitarra acustica, "
                "percussioni leggere, basso caldo, fisarmonica, 105bpm, solare, gioioso")

    # Anger / pain / betrayal
    if any(w in t for w in ["rabbia", "tradimento", "bugiardo", "odio",
                             "dolore", "pianto", "lacrime", "ferito", "tradita"]):
        return ("Italian rock emotivo, voce maschile graffiante intensa, chitarra elettrica, "
                "basso distorto, batteria potente, 118bpm, teso, sfogo emotivo")

    # Love / romantic
    if any(w in t for w in ["amore", "cuore", "ti amo", "bacio", "abbraccio",
                             "innamorat", "passione", "tenerezza", "carezze"]):
        return ("Italian romantic pop, voce maschile calda e vellutata, piano melodico, "
                "archi d'arco, basso soft, 80bpm, sensuale, intimo, commovente")

    # Philosophical / introspective
    if any(w in t for w in ["vita", "senso", "mondo", "esistenza", "pensiero",
                             "verità", "libertà", "tempo", "memoria", "sogno"]):
        return ("Italian cantautore, voce maschile riflessiva e profonda, piano e archi, "
                "chitarra acustica, violino, 85bpm, introspettivo, testo filosofico")

    # Youth / urban / rap
    if any(w in t for w in ["strada", "gente", "quartiere", "urban", "flow",
                             "rispetto", "soldi", "amici", "party"]):
        return ("Italian urban trap-pop, voce maschile rap fluida, beat 808, "
                "synth moderno, hi-hat rapido, 125bpm, energico, hook catchy")

    # Default diary/personal
    return ("Italian pop cantautorale, voce maschile vera e autentica, chitarra acustica, "
            "piano, leggero pad ambient, 90bpm, sincero, melodico, arrangiamento essenziale")


# ═════════════════════════════════════════════════════════════════════════════
# SONG STRUCTURE BUILDER — trasforma testo blog in lirica strutturata
# ═════════════════════════════════════════════════════════════════════════════

# Frasi musicali di riempimento — modalità normale
FILLER_IT = [
    "e il tempo scorre via, lento come il mare",
    "nell'anima rimane ciò che il cuore ha detto",
    "ogni parola vale più di mille silenzi",
    "e ancora qui, a cercare il senso vero",
    "la vita corre, io resto fermo a guardare",
    "nel buio trovo sempre la mia luce",
    "non esiste distanza che separi le anime",
    "ogni respiro è un verso che non ho scritto",
]

FILLER_EN = [
    "and time flows slow like rivers to the sea",
    "every word I've spoken echoes back to me",
    "in the silence between us something always stays",
    "I keep searching for the meaning of these days",
    "hold on to the feeling that you can't explain",
    "every scar a story, every loss a gain",
]

# Frasi fantasy/creative — per la frazione casuale (25%)
FILLER_FANTASY_IT = [
    "nel regno dove i sogni diventano profezie",
    "le stelle cadono come lacrime di divinità",
    "tra le rovine del tempo nasce una leggenda",
    "il vento porta voci di mondi perduti",
    "cavalco l'ombra verso l'orizzonte infinito",
    "ogni silenzio è una porta verso l'ignoto",
    "il cielo brucia d'oro mentre cado nell'abisso",
    "sono il custode di segreti che il mondo ha dimenticato",
    "danza con me tra i frammenti del possibile",
    "oltre il confine del reale esiste il mio nome",
]

FILLER_FANTASY_EN = [
    "I ride the storm through worlds beyond the veil",
    "ancient stars remember what the living have forgot",
    "the dragon speaks in tongues of fire and fate",
    "beneath the silver moon we forge our destinies",
    "shadows bow before the light I carry in my chest",
    "between the cracks of time your voice still calls to me",
]

# Stili potenziati per modalità fantasy
FANTASY_STYLE_MAP = {
    "diary":       "Italian epic cantautorale, archi drammatici, voce intensa, dinamiche forti",
    "fantasy":     "Italian epic metal orchestrale, cori epici, chitarre power, batteria cinematica",
    "dark_fantasy":"Italian dark epic, organo gotico, voci corali, atmosfera oscura e maestosa",
}


def smart_truncate(text: str, max_chars: int) -> str:
    """Tronca al limite massimo senza spezzare righe o frasi."""
    if len(text) <= max_chars:
        return text
    # Trova l'ultimo newline prima del limite
    cut = text.rfind('\n', 0, max_chars)
    if cut < max_chars * 0.7:  # se troppo indietro, taglia all'ultimo punto/virgola
        for sep in ['. ', '? ', '! ', ', ']:
            c = text.rfind(sep, 0, max_chars)
            if c > max_chars * 0.7:
                cut = c + 1
                break
    if cut <= 0:
        cut = max_chars
    return text[:cut].rstrip()

def pick_hook(lines: list, title: str) -> str:
    """Sceglie la frase-hook più impattante: la più corta non banale."""
    candidates = [l for l in lines if 8 < len(l) < 60]
    if not candidates:
        return title
    # Preferisci linee con verbi forti o parole emotive
    EMOTIVE = {"amore","cuore","vita","morte","cielo","mai","sempre","solo","ancora",
                "love","heart","life","never","always","only","soul","tears"}
    scored = sorted(candidates,
                    key=lambda l: sum(1 for w in l.lower().split() if w in EMOTIVE),
                    reverse=True)
    return scored[0] if scored else candidates[0]


def lyrify(text: str, title: str, lang: str = "it",
           want_rhyme: bool = True, is_fantasy: bool = False) -> str:
    """
    Trasforma testo blog in lirica strutturata per Suno — target 3-4 minuti.

    Struttura: V1 + PreChorus + C + V2 + PreChorus + C + [Instrumental] (break)
               + Bridge + C + C + Outro(lungo)
    ~30-36 righe di testo = 1800-2400 chars = 3-4 min su Suno.
    [Instrumental] è un BREAK al centro, NON alla fine (evita chiusura prematura).
    """
    import random
    random.seed(hash(title) % 9999)

    if is_fantasy:
        filler = FILLER_FANTASY_EN if lang == "en" else FILLER_FANTASY_IT
    else:
        filler = FILLER_EN if lang == "en" else FILLER_IT

    lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 4]

    # ── Espansione: porta a minimo 16 righe per avere tutte le sezioni ────────
    while len(lines) < 16:
        lines.insert(random.randint(1, max(1, len(lines))), random.choice(filler))

    # ── Hook principale (chorus anchor) ───────────────────────────────────────
    hook = pick_hook(lines, title)

    # ── Sezioni di testo ──────────────────────────────────────────────────────
    n = len(lines)
    v1          = lines[:4]
    pre_chorus  = lines[4:6]                         # 2 righe pre-ritornello
    v2          = lines[6:10]
    bridge_src  = lines[10:14] if n > 10 else v1[:4]
    outro_src   = lines[14:18] if n > 14 else (lines[-4:] if n >= 4 else lines)

    # ── Rima per sezione ──────────────────────────────────────────────────────
    def rhyme_section(sec_lines):
        if not want_rhyme or len(sec_lines) < 2:
            return sec_lines
        result, i = [], 0
        while i < len(sec_lines):
            if i + 1 < len(sec_lines):
                l1, l2 = make_rhyming_couplet(sec_lines[i], sec_lines[i + 1])
                result.extend([l1, l2])
                i += 2
            else:
                result.append(sec_lines[i])
                i += 1
        return result

    v1         = rhyme_section(v1)
    v2         = rhyme_section(v2)
    bridge     = rhyme_section(bridge_src[:4])
    outro      = rhyme_section(outro_src[:4])

    # Chorus a 4 righe reali (non hook×3) — più contenuto = più durata
    def build_chorus():
        lines_c = [hook]
        for fl in random.sample(filler, min(3, len(filler))):
            lines_c.append(fl)
            if len(lines_c) >= 4:
                break
        while len(lines_c) < 4:
            lines_c.append(hook)
        return rhyme_section(lines_c[:4])

    chorus = build_chorus()

    # ── Assembla struttura target 3-4 min ────────────────────────────────────
    # V1 + PreC + C + V2 + PreC + C + [break] + Bridge + C + C + Outro
    song = []

    song.append("[Verse 1]")
    song.extend(v1)
    song.append("")

    if pre_chorus:
        song.append("[Pre-Chorus]")
        song.extend(pre_chorus)
        song.append("")

    song.append("[Chorus]")
    song.extend(chorus)
    song.append("")

    if v2:
        song.append("[Verse 2]")
        song.extend(v2)
        song.append("")

    if pre_chorus:
        song.append("[Pre-Chorus]")
        song.extend(pre_chorus)
        song.append("")

    song.append("[Chorus]")
    song.extend(chorus)
    song.append("")

    # [Instrumental] come BREAK nel mezzo — NON segnale di fine
    song.append("[Instrumental]")
    song.append("")

    song.append("[Bridge]")
    song.extend(bridge)
    song.append("")

    song.append("[Chorus]")
    song.extend(chorus)
    song.append("")

    # Chorus finale ripetuto per chiudere forte
    song.append("[Chorus]")
    song.extend(chorus)
    song.append("")

    # Outro lungo (4 righe) — non troncare la canzone
    song.append("[Outro]")
    song.extend(outro if outro else [hook, hook])
    song.append("")

    return '\n'.join(song)


# ═════════════════════════════════════════════════════════════════════════════
# RHYME DETECTION & MAKER
# ═════════════════════════════════════════════════════════════════════════════
def last_word(line: str) -> str:
    words = re.findall(r'\b\w+\b', line.lower())
    return words[-1] if words else ""


def shares_rhyme(a: str, b: str, n=3) -> bool:
    la, lb = last_word(a), last_word(b)
    return len(la) >= n and len(lb) >= n and la[-n:] == lb[-n:]


def has_rhyme(text: str) -> bool:
    """Vero se almeno 30% delle coppie di versi rimano."""
    lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 4]
    if len(lines) < 4:
        return True  # troppo corto, non forziamo
    pairs = sum(shares_rhyme(lines[i], lines[i+1]) for i in range(0, len(lines)-1, 2))
    return pairs / max(len(lines) // 2, 1) >= 0.25


ITALIAN_ENDINGS = [
    ("amo","ato"), ("era","era"), ("ire","ire"), ("ente","ente"),
    ("are","are"), ("ore","ore"), ("ione","ione"), ("anza","anza"),
    ("ito","ito"), ("ura","ura"), ("enza","enza"), ("etto","etto"),
]

def make_rhyming_couplet(line1: str, line2: str) -> tuple:
    """Tenta di far rimare due versi modificando la desinenza del secondo."""
    w1 = last_word(line1)
    if not w1:
        return line1, line2
    # cerca un pattern di rima già nel line1
    for end1, end2 in ITALIAN_ENDINGS:
        if w1.endswith(end1):
            w2 = last_word(line2)
            if w2 and not w2.endswith(end2):
                # sostituisci desinenza di w2 con end2
                root = w2[:-min(len(w2), len(end2))] if len(w2) > len(end2) else w2
                new_w2 = root + end2
                new_line2 = re.sub(r'\b' + re.escape(w2) + r'\b', new_w2, line2)
                return line1, new_line2
    return line1, line2


def enforce_rhyme(text: str) -> str:
    """Riscrive i versi cercando struttura AABB."""
    lines = [l for l in text.split('\n') if l.strip()]
    result = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            l1, l2 = lines[i], lines[i+1]
            if not shares_rhyme(l1, l2):
                l1, l2 = make_rhyming_couplet(l1, l2)
            result.extend([l1, l2])
            i += 2
        else:
            result.append(lines[i])
            i += 1
    return '\n'.join(result)


# ═════════════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTOR (basic)
# ═════════════════════════════════════════════════════════════════════════════
EN_WORDS = {"the","and","you","your","my","is","are","was","were","for",
            "this","that","with","have","from","they","not","but","his","her"}

def detect_lang(text: str) -> str:
    words = set(re.findall(r'\b[a-zA-Z]{2,}\b', text.lower()))
    en_count = len(words & EN_WORDS)
    return "en" if en_count >= 4 else "it"


# ═════════════════════════════════════════════════════════════════════════════
# BLOGGER ATOM FEED SCRAPER
# ═════════════════════════════════════════════════════════════════════════════
def fetch_atom(blog_url: str, max_posts=500) -> list:
    """Recupera tutti i post tramite Atom feed paginato."""
    posts = []
    base = blog_url.rstrip('/') + "/feeds/posts/default"
    start = 1
    while True:
        params = {"alt": "json", "max-results": "50", "start-index": str(start)}
        url = base + "?" + urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"    ⚠️  Feed error ({start}): {e}")
            break

        feed = data.get("feed", {})
        entries = feed.get("entry", [])
        if not entries:
            break

        total = int(feed.get("openSearch$totalResults", {}).get("$t", 0))
        print(f"    Fetched {start}-{start+len(entries)-1} / {total}")

        for e in entries:
            title = e.get("title", {}).get("$t", "Senza titolo")
            # Prendi content o summary
            raw = e.get("content", {}).get("$t", "") or e.get("summary", {}).get("$t", "")
            pub  = e.get("published", {}).get("$t", "")[:10]
            link = next((l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"), "")
            posts.append({"title": title, "raw": raw, "date": pub, "url": link})

        start += len(entries)
        if start > max_posts or start > total:
            break
        time.sleep(0.3)

    return posts


# ═════════════════════════════════════════════════════════════════════════════
# POST PROCESSOR: merge corti + stile + rima + lang
# ═════════════════════════════════════════════════════════════════════════════
def process_posts(raw_posts: list, blog_meta: dict, en_counter: list,
                  total_counter: list) -> list:
    """Converte raw posts in voci queue con stile, rima e merge."""
    cleaned = []
    for p in raw_posts:
        text = clean_html(p["raw"])
        cleaned.append({"title": p["title"], "text": text,
                        "date": p["date"], "url": p["url"]})

    result = []
    i = 0
    while i < len(cleaned):
        item = cleaned[i]
        text = item["text"]

        # Merge post corti con i successivi
        merge_count = 0
        merged_titles = [item["title"]]
        while len(text) < MIN_CHARS and merge_count < MAX_MERGE and i + merge_count + 1 < len(cleaned):
            merge_count += 1
            nxt = cleaned[i + merge_count]
            text += "\n\n" + nxt["text"]
            merged_titles.append(nxt["title"])

        i += merge_count + 1

        if len(text) < 80:  # troppo corto anche dopo merge
            continue

        # Lingua
        lang = detect_lang(text)

        # Decide se questo post va in inglese (~15% dei totali, solo se già EN o soglia)
        total_counter[0] += 1
        want_en = (lang == "en") or (total_counter[0] % round(1/EN_RATIO) == 0)
        final_lang = "en" if want_en else "it"

        # Modalità fantasy casuale (~25% dei post, deterministico per titolo)
        is_fantasy = (blog_meta["theme"] in ("fantasy", "dark_fantasy") or
                      abs(hash(item["title"])) % 100 < int(FANTASY_RATIO * 100))

        # Style — potenziato se fantasy
        if is_fantasy and blog_meta["theme"] in FANTASY_STYLE_MAP:
            style = FANTASY_STYLE_MAP[blog_meta["theme"]]
        else:
            style = infer_style(item["title"], text, blog_meta["theme"], final_lang)
            if is_fantasy:
                style = (style
                    .replace("pop cantautorale", "epic cantautorale, archi cinematici")
                    .replace("melodico", "epico e drammatico")
                    .replace("arrangiamento moderno", "orchestrazione epica"))

        # Rima (80% regola)
        want_rhyme = (total_counter[0] % round(1/RHYME_RATE) != 0)

        # LYRIFY: struttura canzone completa + espansione corti + fantasy mode
        lyrics = lyrify(text, item["title"], final_lang, want_rhyme, is_fantasy)

        # Troncatura intelligente — no spezzature a metà riga (limite durata Suno)
        lyrics = smart_truncate(lyrics, LYRICS_MAX)

        # Titolo: primo se merge, con indicatore
        title = item["title"]
        if len(merged_titles) > 1:
            title = title + " [+{}]".format(len(merged_titles) - 1)

        result.append({
            "title":    title,
            "lyrics":   lyrics,
            "style":    style,
            "lang":     final_lang,
            "rhymed":   want_rhyme,
            "source":   item["url"],
            "blog":     blog_meta["id"],
            "date":     item["date"],
            "done":     False,
        })

    return result


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print(f"  SUNO BLOG PIPELINE — {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 60)

    # Carica queue esistente per deduplicare
    existing_urls = set()
    existing_items = []

    if QUEUE_MASTER.exists():
        existing_items = json.loads(QUEUE_MASTER.read_text("utf-8"))
        existing_urls = {it.get("source","") for it in existing_items}
        print(f"  Queue master esistente: {len(existing_items)} voci")
    elif QUEUE_LEGACY.exists():
        # Prima run: migra la queue legacy aggiornando gli stili
        legacy = json.loads(QUEUE_LEGACY.read_text("utf-8"))
        print(f"  Migrazione queue legacy: {len(legacy)} voci")
        en_counter = [0]
        total_counter = [0]
        for it in legacy:
            total_counter[0] += 1
            lang = detect_lang(it.get("lyrics",""))
            want_en = lang == "en" or total_counter[0] % round(1/EN_RATIO) == 0
            final_lang = "en" if want_en else "it"
            style = infer_style(it["title"], it.get("lyrics",""), "diary", final_lang)
            lyrics = it.get("lyrics","")
            if total_counter[0] % round(1/RHYME_RATE) != 0 and not has_rhyme(lyrics):
                lyrics = enforce_rhyme(lyrics)
            it["style"] = style
            it["lang"] = final_lang
            it["lyrics"] = lyrics[:3000]
            it.setdefault("blog", "sabbonzo")
            it.setdefault("rhymed", False)
            existing_items.append(it)
            existing_urls.add(it.get("source",""))
        print(f"  Stili aggiornati in tutti i {len(existing_items)} post legacy")

    # Scrapa ogni blog
    en_counter  = [0]
    total_counter = [len(existing_items)]
    new_total = 0

    for blog in BLOGS:
        if blog["id"] == "sabbonzo" and existing_urls:
            print(f"\n  [{blog['id']}] già in queue — skip scraping (stili già aggiornati)")
            continue
        if blog["id"] == "blackratas":
            print(f"\n  [{blog['id']}] nessun post — skip")
            continue

        print(f"\n  Scraping [{blog['id']}] {blog['url']} ...")
        raw_posts = fetch_atom(blog["url"])
        print(f"  → {len(raw_posts)} post trovati")

        # Filtra già presenti
        new_posts = [p for p in raw_posts if p["url"] not in existing_urls]
        print(f"  → {len(new_posts)} nuovi (deduplicati)")

        if not new_posts:
            continue

        processed = process_posts(new_posts, blog, en_counter, total_counter)
        for it in processed:
            existing_urls.add(it["source"])
        existing_items.extend(processed)
        new_total += len(processed)
        print(f"  → {len(processed)} voci aggiunte alla queue")

    # Scrivi queue master
    QUEUE_MASTER.write_text(json.dumps(existing_items, indent=2, ensure_ascii=False), "utf-8")

    pending = sum(1 for it in existing_items if not it.get("done"))
    print(f"\n  ✅ Queue master salvata: {len(existing_items)} totali | {pending} pending")
    print(f"  📁 {QUEUE_MASTER}")

    # Statistiche
    by_blog = {}
    by_lang = {}
    by_style_prefix = {}
    for it in existing_items:
        if not it.get("done"):
            b = it.get("blog","?")
            l = it.get("lang","?")
            s = it.get("style","")[:30]
            by_blog[b] = by_blog.get(b,0) + 1
            by_lang[l] = by_lang.get(l,0) + 1
            by_style_prefix[s] = by_style_prefix.get(s,0) + 1

    print("\n  PENDING per blog:")
    for b,n in sorted(by_blog.items(), key=lambda x:-x[1]):
        print(f"    {b}: {n}")
    print("\n  PENDING per lingua:")
    for l,n in sorted(by_lang.items(), key=lambda x:-x[1]):
        print(f"    {l}: {n}")
    print("\n  Top 5 stili:")
    for s,n in sorted(by_style_prefix.items(), key=lambda x:-x[1])[:5]:
        print(f"    {s}: {n}")


if __name__ == "__main__":
    main()
