# © Sabino Gervasio
"""
suno_style_analyzer.py — Assegna stili musicali precisi a ogni canzone via Ollama.

Legge suno_queue_master.json → per ogni item analizza titolo+lyrics con Ollama
→ assegna genere corretto, strumenti culturalmente accurati, BPM, mood
→ salva: style (aggiornato), style_by (modello), style_version

Poi costruisce RELEASES/ con cartella per ogni canzone che ha già MP3+cover.
"""
import os
import sys, json, re, time, urllib.request, urllib.error, shutil, hashlib, subprocess
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

BASE          = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))")
QUEUE_F       = BASE / "suno_queue_master.json"
LOCAL_F       = BASE / "suno_local_queue.json"
DISTRO        = BASE / "DISTRO_READY"
COVERS        = BASE / "covers"
RELEASES      = BASE / "RELEASES"
DA_UPLOADARE  = BASE / "DA_UPLOADARE"
RELEASES.mkdir(exist_ok=True)
DA_UPLOADARE.mkdir(exist_ok=True)

OLLAMA_URL  = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi4-mini:latest"  # più veloce di phi4:latest per batch
BATCH_SAVE  = 20                    # salva ogni N items

# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT SYSTEM — regole musicali per Suno
# ═══════════════════════════════════════════════════════════════════════════════
STYLE_RULES = """
REGOLE STILE SUNO:
- Formato output: "genre, instruments (max 3), BPM: N, mood adjectives, vocal style"
- Massimo 100 caratteri totali
- Sempre includere BPM numerico
- Strumenti devono essere CULTURALMENTE accurati al testo

MAPPATURA CULTURAL→STRUMENTI:
- Arabo/Orientale/Deserto/Notte araba: Arabic maqam, oud, darbuka, 80-95 BPM
- Viking/Nordico/Ragnarok/Norse: Viking folk metal, nyckelharpa, war drums, 130-160 BPM
- Fantasy RPG/Elfico/Magia: epic orchestral, harp, choir, 100-130 BPM
- Dark Fantasy/Oscuro/Gotico: dark orchestral, cello, eerie bells, 70-90 BPM
- D&D/Dark Sun/Dungeon: dungeon synth, lute, ominous brass, 85-110 BPM
- Amore/Romance/Dolce: Italian cantautore, nylon guitar, violin, 72-88 BPM
- Estate/Mare/Sole/Mediterraneo: Mediterranean pop, bouzouki, percussion, 100-115 BPM
- Triste/Malinconia/Sola: melancholic folk, piano, strings, 60-75 BPM
- Spirituale/Preghiera/Sacro: gospel, organ, choir, 75-90 BPM
- Rabbia/Ribellione/Oscuro: dark rock, distorted guitar, drums, 120-145 BPM
- Natura/Bosco/Vento: acoustic folk, flute, acoustic guitar, 80-100 BPM
- Techno/Digitale/AI/Codice: synthwave, electronic beats, 110-130 BPM
- Nostalgia/Passato/Vecchio: vintage pop, piano, accordion, 80-95 BPM
- Epico/Guerra/Battaglia: epic cinematic, brass, choir, 120-150 BPM
"""

PROMPT_TEMPLATE = """Sei un music producer professionista. Analizza questo post di blog italiano e assegna lo stile musicale PRECISO per Suno AI.

{rules}

Titolo: {title}
Blog: {blog}
Testo (prime 200 chars): {excerpt}

Rispondi SOLO con questo JSON (nient'altro, nessun testo prima o dopo):
{{"genre":"...","subgenre":"...","instruments":"strumento1, strumento2, strumento3","bpm":90,"mood":"aggettivo1, aggettivo2","energy":"low|medium|high","vocals":"tipo voce","suno_style":"stringa completa max 100 chars compatibile Suno"}}"""


def ollama_call(prompt: str, timeout=120) -> str:
    data = json.dumps({
        "model":       OLLAMA_MODEL,
        "prompt":      prompt,
        "stream":      False,
        "keep_alive":  "60m",
        "options":     {"temperature": 0.2, "num_predict": 400}
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())["response"].strip()
    except Exception as e:
        return f"ERROR:{e}"


def parse_style_response(raw: str) -> dict | None:
    """Estrae JSON dalla risposta Ollama — gestisce plain JSON e ```json fences."""
    # Strip markdown code fence if present
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.IGNORECASE)
    clean = re.sub(r'\s*```$', '', clean.strip())

    # Try parsing the whole cleaned string first
    try:
        obj = json.loads(clean)
        if "suno_style" in obj:
            return obj
    except Exception:
        pass

    # Fallback: find first {...} block (handles trailing text)
    m = re.search(r'\{[^{}]{10,}\}', clean, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if "suno_style" in obj:
                return obj
        except Exception:
            pass
    return None


def normalize_suno_style(obj: dict) -> str:
    """Costruisce stringa stile Suno dal JSON, max 100 chars."""
    parts = []
    if obj.get("genre"):        parts.append(obj["genre"])
    if obj.get("instruments"):  parts.append(obj["instruments"])
    bpm = obj.get("bpm")
    if bpm:                     parts.append(f"{bpm} BPM")
    if obj.get("mood"):         parts.append(obj["mood"])
    if obj.get("vocals"):       parts.append(obj["vocals"])
    style = ", ".join(parts)
    # Fallback: usa suno_style se la costruzione supera 100 chars
    if len(style) > 100:
        style = obj.get("suno_style", style)[:100]
    return style


# ═══════════════════════════════════════════════════════════════════════════════
# PARTE 1 — Analisi stile con Ollama
# ═══════════════════════════════════════════════════════════════════════════════
def run_style_analysis(force=False):
    qm = json.loads(QUEUE_F.read_text("utf-8"))

    # Items da analizzare: tutti quelli senza style_by, o se force=True tutti
    todo = [i for i, x in enumerate(qm)
            if force or not x.get("style_by")]
    print(f"Items da analizzare: {len(todo)}/{len(qm)}")
    if not todo:
        print("Tutti gli stili già assegnati. Usa force=True per rianalizzare.")
        return qm

    ok = err = 0
    for count, idx in enumerate(todo, 1):
        item = qm[idx]
        title  = item.get("title", "?")
        blog   = item.get("blog", "sabbonzo")
        lyrics = item.get("lyrics", "")
        excerpt = re.sub(r'\[.*?\]', '', lyrics)[:200].replace("\n", " ").strip()

        prompt = PROMPT_TEMPLATE.format(
            rules=STYLE_RULES, title=title, blog=blog, excerpt=excerpt
        )

        raw = ollama_call(prompt)

        if raw.startswith("ERROR:"):
            print(f"  [{count}/{len(todo)}] ❌ {title[:40]} — {raw}")
            err += 1
            # mantieni stile vecchio, segna come tentato
            qm[idx]["style_by"]      = f"ollama:{OLLAMA_MODEL}:ERROR"
            qm[idx]["style_version"] = "2.0"
        else:
            parsed = parse_style_response(raw)
            if parsed:
                new_style = normalize_suno_style(parsed)
                old_style = item.get("style", "")
                qm[idx]["style"]         = new_style
                qm[idx]["style_raw"]     = parsed        # salva tutto il JSON
                qm[idx]["style_by"]      = f"ollama:{OLLAMA_MODEL}"
                qm[idx]["style_version"] = "2.0"
                qm[idx]["style_date"]    = datetime.now().strftime("%Y-%m-%d %H:%M")
                changed = "✓" if new_style != old_style else "="
                print(f"  [{count}/{len(todo)}] {changed} {title[:38]} → {new_style[:60]}")
                ok += 1
            else:
                print(f"  [{count}/{len(todo)}] ⚠ parse fail: {title[:38]} | raw: {raw[:80]}")
                err += 1

        # Salva ogni BATCH_SAVE items
        if count % BATCH_SAVE == 0:
            QUEUE_F.write_text(json.dumps(qm, ensure_ascii=False, indent=2), "utf-8")
            print(f"  💾 Salvato checkpoint ({count}/{len(todo)})")

    # Salva finale
    QUEUE_F.write_text(json.dumps(qm, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  Stili assegnati: {ok} | Errori: {err}")
    return qm


# ═══════════════════════════════════════════════════════════════════════════════
# PARTE 2 — Costruisce cartelle RELEASES/
# ═══════════════════════════════════════════════════════════════════════════════
def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def _safe_dir_name(title: str) -> str:
    """Nome cartella sicuro per Windows."""
    s = re.sub(r'[<>:"/\\|?*]', "", title)
    s = s.strip(". ")  # Windows vieta nomi che finiscono con punto o spazio
    return s[:60].strip()

def build_releases(qm: list):
    # Mappa MP3 per titolo
    mp3_map: dict[str, list[Path]] = {}
    for f in DISTRO.glob("*.mp3"):
        stem = re.sub(r"\s*\(v\d+\)$", "", f.stem).strip()
        mp3_map.setdefault(_norm(stem), []).append(f)

    # Mappa cover da local_queue
    lq_map: dict[str, str] = {}
    if LOCAL_F.exists():
        for x in json.loads(LOCAL_F.read_text("utf-8")):
            lq_map[x["title"]] = x.get("cover_path", "")

    built = 0
    for item in qm:
        title  = item.get("title", "?")
        lyrics = item.get("lyrics", "")
        style  = item.get("style", "")

        # Cerca MP3
        mp3s = mp3_map.get(_norm(title), [])
        if not mp3s:
            # Cerca per prefisso 15 chars
            pref = _norm(title)[:15]
            hits = [v for k, v in mp3_map.items() if k[:15] == pref]
            mp3s = hits[0] if hits else []

        # Cerca cover
        cover_path = lq_map.get(title, "")
        if not cover_path:
            # Fallback: genera hash cover
            slug = hashlib.md5(title.encode()).hexdigest()[:10]
            candidate = COVERS / f"cover_{slug}.png"
            if candidate.exists():
                cover_path = str(candidate)

        # Crea cartella solo se abbiamo almeno MP3 O cover
        if not mp3s and not cover_path:
            continue

        dir_name = _safe_dir_name(title)
        release_dir = RELEASES / dir_name
        release_dir.mkdir(exist_ok=True)

        # Copia MP3
        for mp3 in mp3s:
            dst = release_dir / mp3.name
            if not dst.exists():
                shutil.copy2(mp3, dst)

        # Copia cover
        if cover_path:
            cp = Path(str(cover_path).strip())
            if cp.exists():
                dst_cover = release_dir / "cover.png"
                if not dst_cover.exists():
                    try:
                        shutil.copy2(str(cp), str(dst_cover))
                    except Exception as e:
                        print(f"  ⚠ cover skip ({cp.name}): {e}")

        # Scrivi lyrics.txt
        lyr_file = release_dir / "lyrics.txt"
        if not lyr_file.exists() and lyrics:
            lyr_file.write_text(
                f"# {title}\n\n{lyrics}", encoding="utf-8"
            )

        # Scrivi style.txt
        sty_file = release_dir / "style.txt"
        if style:
            style_raw = item.get("style_raw", {})
            content = (
                f"TITOLO: {title}\n"
                f"STILE SUNO: {style}\n"
                f"ASSEGNATO DA: {item.get('style_by','manual')}\n"
                f"DATA: {item.get('style_date','')}\n"
            )
            if style_raw:
                content += (
                    f"\nDETTAGLIO:\n"
                    f"  Genere:       {style_raw.get('genre','')}\n"
                    f"  Subgenere:    {style_raw.get('subgenre','')}\n"
                    f"  Strumenti:    {style_raw.get('instruments','')}\n"
                    f"  BPM:          {style_raw.get('bpm','')}\n"
                    f"  Mood:         {style_raw.get('mood','')}\n"
                    f"  Energia:      {style_raw.get('energy','')}\n"
                    f"  Voce:         {style_raw.get('vocals','')}\n"
                )
            sty_file.write_text(content, encoding="utf-8")

        # metadata.json
        meta = {
            "title":      title,
            "blog":       item.get("blog", ""),
            "source_url": item.get("source", ""),
            "style":      style,
            "style_by":   item.get("style_by", ""),
            "bpm":        item.get("style_raw", {}).get("bpm", ""),
            "genre":      item.get("style_raw", {}).get("genre", ""),
            "instruments":item.get("style_raw", {}).get("instruments", ""),
            "mood":       item.get("style_raw", {}).get("mood", ""),
            "vocals":     item.get("style_raw", {}).get("vocals", ""),
            "mp3_files":  [f.name for f in mp3s],
            "has_cover":  bool(cover_path),
            "generated":  bool(mp3s),
            "done":       item.get("done", False),
        }
        (release_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
        )

        built += 1

    print(f"\n  Cartelle RELEASES create/aggiornate: {built}")
    print(f"  Path: {RELEASES}")
    return built


# ═══════════════════════════════════════════════════════════════════════════════
# PARTE 3 — DA_UPLOADARE: cartella con junction alle RELEASES complete
# ═══════════════════════════════════════════════════════════════════════════════
def build_da_uploadare() -> int:
    """Crea junction points in DA_UPLOADARE/ per ogni RELEASES/{song}/ completa.
    Completa = ha almeno 1 MP3 + cover.png + style.txt.
    Usa mklink /J (Windows junction, non richiede admin).
    """
    ready = []
    for release_dir in sorted(RELEASES.iterdir()):
        if not release_dir.is_dir():
            continue
        has_mp3    = any(release_dir.glob("*.mp3"))
        has_cover  = (release_dir / "cover.png").exists()
        has_style  = (release_dir / "style.txt").exists()
        if has_mp3 and has_cover and has_style:
            ready.append(release_dir)

    for release_dir in ready:
        link = DA_UPLOADARE / release_dir.name
        if not link.exists():
            subprocess.run(
                ['cmd', '/c', 'mklink', '/J', str(link), str(release_dir)],
                capture_output=True
            )

    print(f"\n  DA_UPLOADARE: {len(ready)} canzoni pronte al caricamento")
    print(f"  Path: {DA_UPLOADARE}")
    return len(ready)


def print_eta(qm: list, ready_count: int):
    """Stampa stima di completamento prelancio."""
    SONGS_PER_DAY = 6
    TODAY = datetime.now().date()

    total       = len(qm)
    done        = sum(1 for x in qm if x.get("done"))
    generated   = sum(1 for x in qm if x.get("style_by") and not x.get("done"))
    pending     = total - done - generated
    days_needed = -(-pending // SONGS_PER_DAY)   # ceiling division
    eta_date    = TODAY + timedelta(days=days_needed)

    print(f"\n{'═'*55}")
    print(f"  STIMA PRELANCIO")
    print(f"{'═'*55}")
    print(f"  Canzoni totali:          {total}")
    print(f"  Già generate (done):     {done}")
    print(f"  Stile assegnato:         {generated + done}")
    print(f"  In coda (da generare):   {pending}")
    print(f"  Ritmo generazione:       {SONGS_PER_DAY} canzoni/giorno")
    print(f"  Giorni necessari:        {days_needed}")
    print(f"  ETA completamento:       {eta_date.strftime('%Y-%m-%d')} ({'domenica' if eta_date.weekday()==6 else 'sabato' if eta_date.weekday()==5 else ''})")
    print(f"  Pronte DA_UPLOADARE:     {ready_count}")
    print(f"{'═'*55}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 65)
    print("  SUNO STYLE ANALYZER + RELEASE BUILDER")
    print("=" * 65)

    # Step 1: analisi stili con Ollama
    print("\n[STEP 1] Analisi stili con Ollama...\n")
    qm = run_style_analysis(force=False)

    # Step 2: costruisce cartelle RELEASES
    print("\n[STEP 2] Costruisce cartelle RELEASES...\n")
    build_releases(qm)

    # Step 3: popola DA_UPLOADARE con junction alle release complete
    print("\n[STEP 3] Popola DA_UPLOADARE (canzoni pronte)...\n")
    ready_count = build_da_uploadare()

    # Step 4: stima ETA
    print_eta(qm, ready_count)

    # Step 5: rigenera il report canzoni aggiornato
    print("\n[STEP 5] Aggiorna resoconto_canzoni.html...\n")
    PYTHON = r"C:\Users\HP\miniconda3\python.exe"
    result = subprocess.run(
        [PYTHON, str(BASE / "build_report.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        print(f"  OK: {result.stdout.strip()[:120]}")
    else:
        print(f"  ⚠ build_report: {result.stderr[:200]}")

    print("\n" + "=" * 65)
    print("  COMPLETATO")
    print(f"  Queue:        {QUEUE_F}")
    print(f"  Releases:     {RELEASES}")
    print(f"  DA_UPLOADARE: {DA_UPLOADARE}")
    print("=" * 65)
