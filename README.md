# 🎵 suno-auto

> Bulk-generate MP3s on [Suno AI](https://suno.com) using Playwright browser automation.

## Features
- Queue hundreds of songs from a JSON list (title + lyrics + style)
- Handles Suno's CDN encoding delay (waits 35s, retries 3× with backoff)
- Persistent Chrome profile — login once, run forever
- Downloads MP3s at full quality (skips stub files < 100KB)
- Daily credit limiter (configurable, default 6 songs/day)
- Analyzes style from lyrics and clusters songs for bundling

## Setup

```bash
pip install playwright python-dotenv
playwright install chromium
cp .env.example .env  # fill in your values
python suno_queue_runner.py
```

## .env
```
SUNO_PROFILE_DIR=./suno_profile
OUTPUT_DIR=./output
DAILY_LIMIT=6
```

## Queue format (`queue.json`)
```json
[
  {"title": "My Song", "lyrics": "verse one\nverse two", "style": "Italian pop, acoustic guitar, 90bpm"}
]
```

## How it works
1. Opens Chrome with persistent profile (you log into Suno once manually)
2. For each pending item: fills title + style → clicks Create → waits for CDN
3. Downloads both generated variants as MP3
4. Saves progress to queue JSON (done=true when downloaded)

## License
MIT © Sabino Gervasio
