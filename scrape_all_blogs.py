# © Sabino Gervasio
"""
scrape_all_blogs.py — Scarica tutti i blog di Sabino in blog_posts/{blog_id}/
Poi rigenera suno_queue_master.json con testi completi + struttura canzone.
"""
import os
import json, re, html, time, urllib.request, sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8")

MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness")))
sys.path.insert(0, str(MUSIC_DIR))

BLOGS = [
    {"id": "sabbonzo",      "url": "https://sabbonzo.blogspot.com",     "theme": "diary"},
    {"id": "rainboworlds",  "url": "https://rainboworlds.blogspot.com",  "theme": "fantasy"},
    {"id": "lisiaskycloud", "url": "https://lisiaskycloud.blogspot.com", "theme": "fantasy"},
    {"id": "darksun2009",   "url": "https://darksun2009.blogspot.com",   "theme": "dark_fantasy"},
]

BLOG_POSTS_DIR = MUSIC_DIR / "blog_posts"
QUEUE_MASTER   = MUSIC_DIR / "suno_queue_master.json"


def clean_html(raw):
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\xa0', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def safe_filename(title, date):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    safe = safe.replace(' ', '_').strip('._')[:50]
    return f"{date}_{safe}"


def fetch_all_posts(blog_url):
    posts = []
    base = blog_url.rstrip('/') + "/feeds/posts/default"
    start = 1
    while True:
        params = {"alt": "json", "max-results": "50", "start-index": str(start)}
        url = base + "?" + urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  Errore: {e}")
            break
        feed = data.get("feed", {})
        entries = feed.get("entry", [])
        total = int(feed.get("openSearch$totalResults", {}).get("$t", 0))
        if not entries:
            break
        for e in entries:
            title = e.get("title", {}).get("$t", "Senza titolo").strip()
            raw   = e.get("content", {}).get("$t", "") or e.get("summary", {}).get("$t", "")
            pub   = e.get("published", {}).get("$t", "")[:10]
            link  = next((l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"), "")
            posts.append({"title": title, "raw": raw, "date": pub, "url": link})
        start += len(entries)
        if start > total:
            break
        time.sleep(0.3)
    return posts


def scrape_blog(blog_meta):
    """Scarica tutti i post di un blog in blog_posts/{id}/"""
    out_dir = BLOG_POSTS_DIR / blog_meta["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    index_file = out_dir / "_INDEX.json"

    existing = {}
    if index_file.exists():
        existing = {it["url"]: it for it in json.loads(index_file.read_text("utf-8"))}

    # sabbonzo già scaricato — skip scraping ma rileggi indice
    if blog_meta["id"] == "sabbonzo" and len(existing) >= 400:
        print(f"  [{blog_meta['id']}] {len(existing)} post già in locale — skip fetch")
        return list(existing.values()), out_dir

    print(f"  Fetching [{blog_meta['id']}] {blog_meta['url']} ...")
    posts = fetch_all_posts(blog_meta["url"])
    print(f"  {len(posts)} post trovati")

    new_count = 0
    for post in posts:
        if post["url"] in existing:
            continue
        text = clean_html(post["raw"])
        fname = safe_filename(post["title"], post["date"])
        path = out_dir / f"{fname}.txt"
        content = (f"TITOLO: {post['title']}\nDATA:   {post['date']}\n"
                   f"URL:    {post['url']}\nCHARS:  {len(text)}\n"
                   f"{'─'*50}\n\n{text}\n")
        path.write_text(content, encoding="utf-8")
        existing[post["url"]] = {
            "title": post["title"], "date": post["date"],
            "url": post["url"], "file": path.name, "chars": len(text),
        }
        new_count += 1

    index_file.write_text(
        json.dumps(list(existing.values()), indent=2, ensure_ascii=False), "utf-8")
    print(f"  Salvati {new_count} nuovi, totale {len(existing)}")
    return list(existing.values()), out_dir


def rebuild_queue(all_blogs_data):
    """Ricostruisce suno_queue_master.json dai file completi usando il pipeline."""
    from suno_blog_pipeline import (
        clean_html, infer_style, lyrify, smart_truncate, detect_lang,
        FANTASY_RATIO, FANTASY_STYLE_MAP, LYRICS_MAX, EN_RATIO, RHYME_RATE
    )
    import random

    queue = []
    total_counter = [0]
    existing_done = {}

    # Preserva lo stato "done" dalla queue precedente
    if QUEUE_MASTER.exists():
        old = json.loads(QUEUE_MASTER.read_text("utf-8"))
        existing_done = {it.get("source", ""): it.get("done", False) for it in old}

    for blog_meta, index_items, out_dir in all_blogs_data:
        print(f"\n  Elaborazione [{blog_meta['id']}]: {len(index_items)} post")
        for item in sorted(index_items, key=lambda x: x.get("date", "")):
            txt_path = out_dir / item["file"]
            if not txt_path.exists():
                continue
            # Leggi testo completo dal file (salta header metadati)
            raw = txt_path.read_text("utf-8")
            sep = raw.find('─' * 10)
            if sep >= 0:
                end = raw.find('\n\n', sep)
                text = clean_html(raw[end:].strip()) if end >= 0 else clean_html(raw[sep + 52:].strip())
            else:
                text = clean_html(raw)

            if len(text) < 10:
                continue

            total_counter[0] += 1
            lang = detect_lang(text)
            want_en = (lang == "en") or (total_counter[0] % round(1/EN_RATIO) == 0)
            final_lang = "en" if want_en else "it"

            is_fantasy = (blog_meta["theme"] in ("fantasy", "dark_fantasy") or
                          abs(hash(item["title"])) % 100 < int(FANTASY_RATIO * 100))

            if is_fantasy and blog_meta["theme"] in FANTASY_STYLE_MAP:
                style = FANTASY_STYLE_MAP[blog_meta["theme"]]
            else:
                style = infer_style(item["title"], text, blog_meta["theme"], final_lang)
                if is_fantasy:
                    style = (style
                        .replace("pop cantautorale", "epic cantautorale, archi cinematici")
                        .replace("melodico", "epico e drammatico")
                        .replace("arrangiamento moderno", "orchestrazione epica"))

            want_rhyme = (total_counter[0] % round(1 / (1 - RHYME_RATE)) != 0)
            lyrics = lyrify(text, item["title"], final_lang, want_rhyme, is_fantasy)
            lyrics = smart_truncate(lyrics, LYRICS_MAX)

            queue.append({
                "title":     item["title"],
                "lyrics":    lyrics,
                "style":     style,
                "lang":      final_lang,
                "fantasy":   is_fantasy,
                "rhymed":    want_rhyme,
                "source":    item["url"],
                "blog":      blog_meta["id"],
                "date":      item["date"],
                "done":      existing_done.get(item["url"], False),
            })

    QUEUE_MASTER.write_text(json.dumps(queue, indent=2, ensure_ascii=False), "utf-8")
    return queue


def main():
    print("=" * 60)
    print(f"  SCRAPE ALL BLOGS + REBUILD QUEUE — {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 60)

    all_blogs_data = []
    for blog_meta in BLOGS:
        items, out_dir = scrape_blog(blog_meta)
        all_blogs_data.append((blog_meta, items, out_dir))

    print("\n  Ricostruzione suno_queue_master.json ...")
    queue = rebuild_queue(all_blogs_data)

    pending  = sum(1 for it in queue if not it.get("done"))
    fantasy  = sum(1 for it in queue if it.get("fantasy"))
    en_count = sum(1 for it in queue if it.get("lang") == "en")
    rhymed   = sum(1 for it in queue if it.get("rhymed"))

    print(f"\n{'='*60}")
    print(f"  COMPLETATO")
    print(f"  Totale canzoni in queue:  {len(queue)}")
    print(f"  Pending (da generare):    {pending}")
    print(f"  Modalita' fantasy:        {fantasy} ({fantasy*100//max(len(queue),1)}%)")
    print(f"  In inglese:               {en_count} ({en_count*100//max(len(queue),1)}%)")
    print(f"  Con rima:                 {rhymed} ({rhymed*100//max(len(queue),1)}%)")
    print(f"  File: {QUEUE_MASTER}")
    print(f"{'='*60}")

    # Mostra 3 esempi
    import random as rnd
    rnd.seed(42)
    samples = rnd.sample(queue, min(3, len(queue)))
    for s in samples:
        print(f"\n  --- ESEMPIO: {s['title'][:50]} ---")
        print(f"  Blog: {s['blog']} | Style: {s['style'][:60]}")
        print(f"  Fantasy: {s['fantasy']} | Lang: {s['lang']} | Rhyme: {s['rhymed']}")
        print(f"  Lyrics preview:\n{s['lyrics'][:300]}")


if __name__ == "__main__":
    main()
