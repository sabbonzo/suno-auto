# © Sabino Gervasio
"""
scrape_blog_full.py — Scarica TUTTI i post di sabbonzo.blogspot.com
con testo completo (non troncato), uno file .txt per post.

Output: blog_posts/sabbonzo/{data}_{titolo}.txt
        blog_posts/sabbonzo/_INDEX.json
"""
import os
import json, re, html, time, urllib.request, sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8")

BLOG_URL  = "https://sabbonzo.blogspot.com"
OUT_DIR   = Path("os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness"))/blog_posts/sabbonzo")
INDEX_FILE = OUT_DIR / "_INDEX.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)


def clean_html(raw: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\xa0', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def safe_filename(title: str, date: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    safe = safe.replace(' ', '_').strip('._')[:50]
    return f"{date}_{safe}"


def fetch_all_posts() -> list:
    posts = []
    base = BLOG_URL + "/feeds/posts/default"
    start = 1
    page_num = 0

    while True:
        params = {"alt": "json", "max-results": "50", "start-index": str(start)}
        url = base + "?" + urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  Errore feed pagina {page_num+1}: {e}")
            break

        feed = data.get("feed", {})
        entries = feed.get("entry", [])
        total = int(feed.get("openSearch$totalResults", {}).get("$t", 0))

        if not entries:
            break

        page_num += 1
        print(f"  Pagina {page_num}: post {start}–{start+len(entries)-1} / {total}")

        for e in entries:
            title = e.get("title", {}).get("$t", "Senza titolo").strip()
            raw   = (e.get("content", {}).get("$t", "") or
                     e.get("summary", {}).get("$t", ""))
            pub   = e.get("published", {}).get("$t", "")[:10]
            link  = next((l["href"] for l in e.get("link", [])
                          if l.get("rel") == "alternate"), "")
            posts.append({
                "title": title,
                "raw":   raw,
                "date":  pub,
                "url":   link,
            })

        start += len(entries)
        if start > total:
            break
        time.sleep(0.4)

    return posts


def main():
    print("=" * 60)
    print(f"  SABBONZO BLOG SCRAPER — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Target: {BLOG_URL}")
    print("=" * 60)

    # Carica indice esistente (resume se interrotto)
    index = {}
    if INDEX_FILE.exists():
        index = {it["url"]: it for it in json.loads(INDEX_FILE.read_text("utf-8"))}
        print(f"  Indice esistente: {len(index)} post già scaricati")

    posts = fetch_all_posts()
    print(f"\n  Totale post trovati: {len(posts)}")

    new_count = 0
    for i, post in enumerate(posts):
        url = post["url"]
        if url in index:
            continue  # già salvato

        text = clean_html(post["raw"])
        fname = safe_filename(post["title"], post["date"])
        out_path = OUT_DIR / f"{fname}.txt"

        # Contenuto del file
        content = (
            f"TITOLO: {post['title']}\n"
            f"DATA:   {post['date']}\n"
            f"URL:    {url}\n"
            f"CHARS:  {len(text)}\n"
            f"{'─'*50}\n\n"
            f"{text}\n"
        )
        out_path.write_text(content, encoding="utf-8")

        index[url] = {
            "title":    post["title"],
            "date":     post["date"],
            "url":      url,
            "file":     out_path.name,
            "chars":    len(text),
        }
        new_count += 1

        if (i + 1) % 50 == 0 or i == len(posts) - 1:
            # Salva indice intermedio (crash-safe)
            INDEX_FILE.write_text(
                json.dumps(list(index.values()), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"  [{i+1}/{len(posts)}] indice salvato ({new_count} nuovi)")

    # Salva indice finale
    INDEX_FILE.write_text(
        json.dumps(list(index.values()), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Statistiche
    all_chars = sum(it["chars"] for it in index.values())
    short = sum(1 for it in index.values() if it["chars"] < 200)
    medium = sum(1 for it in index.values() if 200 <= it["chars"] < 600)
    long_  = sum(1 for it in index.values() if it["chars"] >= 600)

    print(f"\n{'='*60}")
    print(f"  COMPLETATO")
    print(f"  Post totali salvati: {len(index)}")
    print(f"  Nuovi questa run:    {new_count}")
    print(f"  Caratteri totali:    {all_chars:,}")
    print(f"  Corti (<200c):       {short}")
    print(f"  Medi (200-600c):     {medium}")
    print(f"  Lunghi (>600c):      {long_}")
    print(f"  Cartella: {OUT_DIR}")
    print(f"  Indice:   {INDEX_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
