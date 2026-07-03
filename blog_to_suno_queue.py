# © Sabino Gervasio
"""
Converte i post di sabbonzo.blogspot.com in una coda canzoni per suno_daily_wizard.
Ogni post diventa: titolo canzone + testo (excerpt come lirics) + stile contestuale.
427 post = 427 potenziali canzoni.
"""
import os
import json, sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness")))

BLOG_FILE  = MUSIC_DIR / "blog_posts_sabbonzo.json"
QUEUE_FILE = MUSIC_DIR / "suno_queue_from_blog.json"

# Mappa parole chiave nel titolo → stile Suno
STYLE_MAP = [
    (["amore", "cuore", "ti amo", "innamorat"], "Italian romantic ballad, piano, violino, voce maschile intensa"),
    (["notte", "notturna", "buonanotte", "interferenze"],  "Italian nocturne, ambient, synth pad, voce femminile sussurrata"),
    (["follia", "male", "dolore", "tradimento"],  "Italian dark pop, chitarra elettrica, drama, tensione"),
    (["primavera", "estate", "sole", "margherita"], "Italian summer pop, melodico, voce gioiosa, chitarra acustica"),
    (["alexandra", "luisa", "annarita", "marianna"], "Italian canzone dedicata, personalizzata, arrangiamento intimo"),
    (["poesia", "canto", "melodia", "note"],   "Italian cantautore style, acoustic, poetico"),
    (["sport", "guerra", "battaglia", "sfida"],  "Italian epic, drums, orchestra, motivazionale"),
    (["sogno", "fantasia", "invisibil"],  "Italian dream pop, etereo, synth, voce sognante"),
    (["morte", "finire", "addio", "ultimo"], "Italian malinconia, minor key, pianoforte solo"),
]
DEFAULT_STYLE = "Italian Pop, melodico, arrangiamento moderno, voce espressiva"


def pick_style(title: str, excerpt: str) -> str:
    text = (title + " " + excerpt).lower()
    for keywords, style in STYLE_MAP:
        if any(k in text for k in keywords):
            return style
    return DEFAULT_STYLE


def clean_title(t: str) -> str:
    t = re.sub(r'[^\w\s\'\-\.\!\?àèéìòùÀÈÉÌÒÙ]', ' ', t)
    return t.strip()[:60] or "Canzone senza titolo"


def excerpt_to_lyrics(excerpt: str, title: str) -> str:
    """Crea testo base da usare come prompt lirics per Suno."""
    if len(excerpt) > 50:
        return excerpt[:400]
    # Se excerpt troppo corto, usa il titolo come ispirazione
    return f"[Ispirazione dal titolo: {title}]\n\nUna canzone che parla di {title.lower()}."


def main():
    posts = json.loads(BLOG_FILE.read_text("utf-8"))
    print(f"[BLOG] Post caricati: {len(posts)}")

    queue = []
    for p in posts:
        title   = clean_title(p.get("title", ""))
        excerpt = p.get("excerpt", "")
        style   = pick_style(title, excerpt)
        lyrics  = excerpt_to_lyrics(excerpt, title)

        queue.append({
            "title":   title,
            "lyrics":  lyrics,
            "style":   style,
            "source":  p.get("url", ""),
            "done":    False,
        })

    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), "utf-8")
    print(f"[QUEUE] Salvata: {QUEUE_FILE.name} ({len(queue)} canzoni)")

    # Statistiche stili
    from collections import Counter
    styles = Counter(q["style"] for q in queue)
    print("\n[STILI]")
    for s, n in styles.most_common():
        print(f"  {n:3d}x  {s[:60]}")

    # Mostra prime 10
    print("\n[PRIME 10 CANZONI]")
    for q in queue[:10]:
        print(f"  [{q['style'][:30]}...] {q['title']}")


if __name__ == "__main__":
    main()
