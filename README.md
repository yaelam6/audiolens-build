# ⊙ AudioLens

**A desktop application for BPM and musical key analysis, built for DJs and music producers.**

🌐 **Live website:** [audiolens.netlify.app](https://audiolens.netlify.app)

---

## What It Does

AudioLens analyzes audio files and song metadata to detect **BPM (tempo)** and **musical key**, then displays the result on a **Camelot Wheel** — the standard system DJs use for harmonic mixing.

You can search for any song by name or artist, upload a local audio file, and find similar songs that are harmonically compatible and tempo-matched for seamless mixing.

---

## Key Features

- 🎵 **BPM Detection** — Multi-method analysis (autocorrelation, FFT, band-filtered onset envelopes) with half/double-tempo correction
- 🎹 **Key Detection** — Chromagram-based analysis using Krumhansl–Schmuckler, Temperley, and Shaath profiles; accelerated by `librosa` when available
- 🎡 **Camelot Wheel** — Key displayed as Camelot notation (e.g. `8A`, `10B`) for harmonic mixing compatibility
- 🔍 **Song Search** — iTunes Search API with dual parallel queries (general + artist-term) for accurate results
- 📁 **File Upload** — Analyze any local WAV, MP3, FLAC, or OGG file directly
- 🎛️ **Mix Matches** — Finds similar songs from a curated pool filtered by BPM tolerance and Camelot compatibility
- 🎧 **Preview Playback** — Play 30-second iTunes previews directly inside the app
- 🌗 **Dark UI** — Custom dark-mode interface with animated loading states and a live Circle of Fifths canvas

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Language | Python 3.11 |
| GUI | CustomTkinter, Tkinter Canvas |
| Audio DSP | NumPy, SciPy, SoundFile, librosa |
| Networking | requests, ThreadPoolExecutor |
| Build | PyInstaller (Mac + Windows), GitHub Actions |
| Website | HTML, CSS, JavaScript — deployed on Netlify |

---

## APIs Used

| API | Purpose |
|---|---|
| [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html) | Song search, metadata, 30-second previews |
| [Spotify Web API](https://developer.spotify.com/documentation/web-api) | Optional: audio features (BPM, key) for Mix Matches |

The iTunes Search API is free and requires no authentication. The Spotify integration uses the Client Credentials flow (no user login required) and is optional — the app falls back to iTunes if Spotify credentials are not configured.

> **Note:** Spotify restricted several endpoints (`/audio-features`, `/top-tracks`, `/related-artists`) for new developer apps in late 2024. The Spotify integration path is implemented and ready, but requires an approved app with Extended Quota Mode.

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

`librosa` has an optional dependency on `llvmlite`. If the standard install fails, use:
```bash
pip install requests numpy soundfile customtkinter scipy
pip install librosa --no-deps
```

---

## Running the App

```bash
python audioLens_02.py
```

---

## Spotify Integration (Optional)

To enable the Spotify-powered Mix Matches pool, create a free app at [developer.spotify.com](https://developer.spotify.com) and save your credentials to `~/.audiolens_spotify.json`:

```json
{
  "client_id": "your_spotify_client_id",
  "client_secret": "your_spotify_client_secret"
}
```

Alternatively, set environment variables:

```bash
export SPOTIFY_CLIENT_ID=your_client_id
export SPOTIFY_CLIENT_SECRET=your_client_secret
```

The app will pick up either automatically on startup. **Never commit credentials to version control.**

---

## Project Structure

```
audioLens_02.py        # Main application (v2.0) — all logic and UI
audioLens.py           # Original v1.0 (reference)
requirements.txt       # Python dependencies
index.html             # Project landing page (deployed to Netlify)
AudioLens.spec         # PyInstaller build spec for macOS
AudioLens-Windows.spec # PyInstaller build spec for Windows
create_icon_win.py     # Icon generation utility for Windows build
AudioLens.icns         # macOS app icon
.github/workflows/     # GitHub Actions CI workflow (Windows build)
```

---

## Known Limitations

- **BPM accuracy on short previews** — iTunes previews are 30 seconds. BPM detection on short clips can return half or double the true tempo. The app applies a ×2 / ×0.5 correction heuristic, but edge cases remain.
- **Key detection accuracy** — Chromagram-based key detection is a well-known hard problem. Results are reliable for most pop and electronic music but may be off for complex harmonic content.
- **Mix Matches pool size** — Without Spotify Extended Quota access, the candidate pool is built from iTunes artist searches, which limits variety compared to a full streaming catalogue.
- **No internet, no search** — Song search and Mix Matches both require a network connection (iTunes API).
- **macOS SSL warnings** — The app suppresses `InsecureRequestWarning` from `urllib3`; this is a known issue with the system Python SSL bundle on some macOS versions.

---

## Future Improvements

- [ ] Re-enable Spotify endpoint integration when Extended Quota Mode is approved
- [ ] Waveform visualizer in the analysis panel
- [ ] Export Mix Matches as a playlist (M3U / CSV)
- [ ] BPM tap-tempo override
- [ ] More granular genre/sub-genre detection (Dark Psy, Hi-Tech, etc.)
- [ ] Windows code signing for a cleaner download experience

---

## Skills Demonstrated

This project covers a wide range of software engineering disciplines:

- **Product thinking** — Defined the problem (DJs needing quick BPM/key data) and designed features around a real workflow
- **Audio DSP** — Implemented BPM detection from scratch using autocorrelation and FFT on filtered onset envelopes; key detection using chromagram correlation against music-theory profiles
- **Desktop GUI development** — Built a complete dark-mode UI with CustomTkinter including animated loading states, a Canvas-drawn Circle of Fifths, and responsive layout
- **API integration** — iTunes Search API (parallel dual queries, deduplication, relevance scoring) and Spotify Web API (OAuth Client Credentials, batch audio features)
- **Multithreading** — Background analysis with `ThreadPoolExecutor`, staggered UI updates, per-request cancellation tokens to prevent stale callbacks
- **Error handling & fallbacks** — Graceful degradation from Spotify → iTunes, half/double-tempo BPM correction, preview download failures
- **Build & deployment** — PyInstaller cross-platform packaging, GitHub Actions CI for Windows builds, Netlify static site deployment
- **Iterative development** — Evolved from a simple API wrapper to a full local DSP pipeline across multiple development sessions

---

## Development Approach

This project was developed using a **vibe coding** workflow with [Claude Code](https://claude.ai/code), combining AI-assisted development with human product thinking, feature planning, testing, and iteration. All product decisions, UX choices, testing, and debugging direction were driven by the developer; Claude Code was used as a pair-programming assistant for implementation, refactoring, and technical problem-solving.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Made with ♥ by [Yael Amitay](mailto:yaelam6@gmail.com)*
