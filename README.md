# ⊙ AudioLens

**A desktop application for BPM and musical key analysis, built for DJs and music producers.**

🌐 **Live website:** [audiolens.netlify.app](https://audiolens.netlify.app)

---

## What It Does

AudioLens analyzes songs and audio files to detect **BPM (tempo)** and **musical key**, then displays the result on a **Circle of Fifths** — the standard reference DJs and musicians use for harmonic relationships.

Search for any song by name or artist, or upload a local audio file, and get instant BPM and key data displayed on a live interactive canvas.

---

## Key Features

- 🔍 **Song Search** — Spotify-powered search with relevance scoring; returns name, artist, and album
- 🎵 **BPM Detection** — Cascade lookup: Spotify audio-features → GetSongBPM API → Beatport API → local DSP analysis on 30-second preview
- 🎹 **Key Detection** — Chromagram-based analysis using Krumhansl–Schmuckler and Temperley profiles
- 🎡 **Circle of Fifths** — Live interactive canvas highlighting the detected key and mode (Major/Minor)
- 📁 **File Upload** — Analyze any local WAV, MP3, FLAC, OGG, or AIF file directly with the same DSP pipeline
- 🎧 **Preview Playback** — Play 30-second iTunes previews directly inside the app (▶ button on each result)
- 🌗 **Dark UI** — Custom dark-mode interface with animated loading states

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Language | Python 3.11 |
| GUI | CustomTkinter, Tkinter Canvas |
| Audio DSP | NumPy, SciPy, SoundFile |
| Networking | requests, threading |
| Build | PyInstaller (Mac + Windows), GitHub Actions |
| Website | HTML, CSS, JavaScript — deployed on Netlify |

---

## APIs Used

| API | Purpose |
|---|---|
| [Spotify Web API](https://developer.spotify.com/documentation/web-api) | Song search and audio features (BPM, key) |
| [GetSongBPM API](https://getsongbpm.com/api) | BPM and key fallback lookup |
| [Beatport API](https://api.beatport.com) | BPM and key fallback lookup |
| [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html) | 30-second song previews |

The Spotify integration uses the Client Credentials flow (no user login required). iTunes previews are used for playback and DSP fallback — no authentication required.

> **Note:** Spotify restricted several endpoints (`/audio-features`) for new developer apps in late 2024. When Spotify returns no data, the app automatically falls back to GetSongBPM → Beatport → local DSP preview analysis.

---

## Installation

**Requirements:** Python 3.9+

```bash
git clone https://github.com/yaelam6/bpm-key-finder.git
cd bpm-key-finder
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running the App

```bash
python audioLens.py
```

---

## Project Structure

```
audioLens.py           # Main application — all logic and UI
AudioLens.spec         # PyInstaller build spec for macOS
AudioLens-Windows.spec # PyInstaller build spec for Windows
AudioLens.icns         # macOS app icon
create_icon_win.py     # Icon generation utility for Windows build
requirements.txt       # Python dependencies
index.html             # Project landing page (deployed to Netlify)
.github/workflows/     # GitHub Actions CI workflow (Windows build)
```

---

## Known Limitations

- **Spotify audio-features restriction** — Spotify restricted the `/audio-features` endpoint for new apps in late 2024. The app falls back through GetSongBPM → Beatport → local DSP automatically, but results may vary.
- **BPM accuracy on short previews** — Local DSP runs on 30-second previews. BPM detection on short clips can return half or double the true tempo.
- **Key detection accuracy** — Chromagram-based key detection is a well-known hard problem. Results are reliable for most pop and electronic music but may be off for complex harmonic content.
- **No internet, no search** — Song search and preview playback both require a network connection.
- **macOS SSL warnings** — The app suppresses `InsecureRequestWarning` from `urllib3`; this is a known issue with the system Python SSL bundle on some macOS versions.

---

## Skills Demonstrated

- **Audio DSP** — BPM detection from scratch using autocorrelation and FFT on filtered onset envelopes; key detection using chromagram correlation against music-theory profiles
- **Desktop GUI development** — Complete dark-mode UI with CustomTkinter including animated loading states and a Canvas-drawn Circle of Fifths
- **API integration** — Spotify Web API (OAuth Client Credentials), GetSongBPM, Beatport, iTunes Search API
- **Multithreading** — Background analysis with `threading.Thread`, staggered UI updates, per-request cancellation tokens to prevent stale callbacks
- **Error handling & fallbacks** — Graceful degradation across four data sources (Spotify → GetSongBPM → Beatport → preview DSP)
- **Build & deployment** — PyInstaller cross-platform packaging, GitHub Actions CI for Windows builds, Netlify static site deployment

---

## Development Approach

This project was developed using a **vibe coding** workflow with [Claude Code](https://claude.ai/code), combining AI-assisted development with human product thinking, feature planning, testing, and iteration. All product decisions, UX choices, testing, and debugging direction were driven by the developer; Claude Code was used as a pair-programming assistant for implementation, refactoring, and technical problem-solving.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Made with ♥ by [Yael Amitay](mailto:yaelam6@gmail.com)*
