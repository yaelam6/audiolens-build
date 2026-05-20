import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import requests
import numpy as np
import soundfile as sf
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
from scipy import signal
import warnings

try:
    import librosa as _librosa
    _HAS_LIBROSA = True
except Exception:
    _HAS_LIBROSA = False

warnings.filterwarnings("ignore")

KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAMES = KEY_NAMES[:]

# =========================================================
# COLORS
# =========================================================
BG = "#0f1117"
PANEL = "#181b26"
CARD = "#1e2130"
ACCENT = "#7c5cfc"
ACCENT2 = "#26c6a0"
ACCENT_G = "#1db954"
ERR = "#e05555"
TXT = "#dde1f0"
TXT2 = "#8a91b4"
TXT3 = "#50576e"
BTN_BG = "#252840"

# =========================================================
# HELPERS
# =========================================================
def _sim(a: str, b: str) -> float:
    def clean(t):
        t = t.lower()
        t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
        t = re.sub(r"[^a-z0-9\u05d0-\u05ea\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    a, b = clean(a), clean(b)
    if not a or not b:
        return 0.0

    ratio = SequenceMatcher(None, a, b).ratio()
    a_words, b_words = set(a.split()), set(b.split())
    overlap = len(a_words & b_words) / len(a_words | b_words) if a_words and b_words else 0.0
    contains_bonus = 0.1 if a in b or b in a else 0.0
    return min(ratio * 0.65 + overlap * 0.35 + contains_bonus, 1.0)


def _normalize_key_mode(raw_key: str):
    if not raw_key:
        return None, None

    s = raw_key.strip()
    s = s.replace("♯", "#").replace("♭", "b")
    s = s.replace(" major", " Major").replace(" minor", " Minor")

    m = re.search(r"([A-G][#b]?)[\s\-_\/]*(Major|Minor)", s, re.IGNORECASE)
    if m:
        key = m.group(1).upper()
        mode = "maj" if m.group(2).lower() == "major" else "min"
        repl = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
        key = repl.get(key, key)
        return key, mode

    m2 = re.search(r"^([A-G][#b]?)(m)?$", s, re.IGNORECASE)
    if m2:
        key = m2.group(1).upper()
        mode = "min" if m2.group(2) else "maj"
        repl = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
        key = repl.get(key, key)
        return key, mode

    return None, None


# =========================================================
# STYLE QUERIES — granular sub-genre → representative artist names
# Artist-based iTunes queries give genre-accurate results because
# an artist's catalog stays style-consistent.
# =========================================================
_STYLE_QUERIES = {
    "Goa Trance":            ["Hallucinogen", "Juno Reactor", "Astral Projection",
                              "Man with No Name", "Total Eclipse", "Shpongle",
                              "Eat Static", "Etnica", "Pleiadians", "Cosmosis"],
    "Psytrance":             ["Infected Mushroom", "Astrix", "Vini Vici", "Talamasca",
                              "Bizzare Contact", "Captain Hook", "GMS"],
    "Uplifting Trance":      ["Armin van Buuren", "Above Beyond", "Aly & Fila",
                              "Bryan Kearney", "Ferry Corsten"],
    "Classic Trance":        ["Paul van Dyk", "Robert Miles", "Sasha", "John Digweed",
                              "Chicane", "BT"],
    "Techno":                ["Adam Beyer", "Amelie Lens", "Charlotte de Witte",
                              "Sasha Carassi", "Richie Hawtin"],
    "House / Tech House":    ["FISHER", "Chris Lake", "John Summit", "Hot Since 82",
                              "Green Velvet"],
    "Deep House":            ["Lane 8", "Bonobo", "Bicep", "Nora En Pure",
                              "Kollektiv Turmstrasse"],
    "Drum & Bass":           ["Pendulum", "Chase Status", "Sub Focus", "Netsky",
                              "Camo Krooked"],
    "Progressive / Melodic": ["deadmau5", "Eric Prydz", "Yotto", "Maceo Plex",
                              "Innellea"],
    "Ambient / Chill":       ["Tycho", "Boards of Canada", "Emancipator",
                              "Carbon Based Lifeforms"],
    "Hip-Hop / Trap":        ["Travis Scott", "Future", "21 Savage", "Gunna",
                              "Lil Baby"],
    "Pop / Dance":           ["Calvin Harris", "David Guetta", "Kygo", "Martin Garrix",
                              "Zedd"],
}

# Known Goa Trance artists (90s era) — used for BPM-ambiguous cases
_GOA_ARTISTS = {
    "hallucinogen", "juno reactor", "astral projection", "man with no name",
    "total eclipse", "shpongle", "eat static", "etnica", "pleiadians",
    "cosmosis", "chi a.d.", "ra", "transwave", "xenomorph", "sun project",
}
# Known modern psytrance artists
_PSY_ARTISTS = {
    "infected mushroom", "astrix", "vini vici", "talamasca", "bizzare contact",
    "captain hook", "gms", "solar fields",
}
# Known uplifting/classic trance artists
_UPLIFTING_ARTISTS = {
    "armin van buuren", "above beyond", "aly & fila", "bryan kearney",
    "ferry corsten", "paul van dyk",
}


def _detect_style(genre: str, bpm: float, artist: str) -> str:
    """Return a _STYLE_QUERIES key based on iTunes genre, BPM, and artist name.
    BPM is the key discriminator within the trance family."""
    g = (genre or "").lower()
    a = (artist or "").lower()
    bpm = float(bpm or 120.0)

    is_trance    = "trance" in g
    is_elec      = g in ("electronic", "dance")
    is_no_genre  = g == ""

    # ── Trance family ─────────────────────────────────────────────────────────
    if is_trance or is_elec:
        if 128 <= bpm <= 152:
            if any(k in a for k in _GOA_ARTISTS):
                return "Goa Trance"
            if any(k in a for k in _PSY_ARTISTS) and bpm >= 140:
                return "Psytrance"
            # BPM alone: <140 → Goa-era tempo, ≥140 → modern psytrance tempo
            return "Goa Trance" if bpm < 140 else "Psytrance"
        if 120 <= bpm < 135:
            if any(k in a for k in _UPLIFTING_ARTISTS):
                return "Uplifting Trance"
            return "Classic Trance"
        if bpm >= 135:
            return "Uplifting Trance"

    if is_trance:
        return "Uplifting Trance"   # fallback for any remaining trance

    # ── Other genres ──────────────────────────────────────────────────────────
    if "techno" in g:
        return "Techno"
    if "house" in g:
        return "Deep House" if bpm < 122 else "House / Tech House"
    if "drum" in g or "bass" in g or 155 <= bpm <= 185:
        return "Drum & Bass"
    if "hip" in g or "rap" in g or "trap" in g:
        return "Hip-Hop / Trap"
    if "pop" in g or "alternative" in g:
        return "Pop / Dance"
    if "ambient" in g or bpm < 90:
        return "Ambient / Chill"
    if not is_no_genre and 118 <= bpm <= 132:
        return "Progressive / Melodic"

    # ── No genre metadata (uploaded file) — classify by BPM alone ─────────────
    if is_no_genre:
        if 155 <= bpm <= 185:
            return "Drum & Bass"
        if 140 <= bpm <= 155:
            return "Psytrance"
        if 128 <= bpm < 140:
            return "Goa Trance"
        if 124 <= bpm < 128:
            return "Techno"
        if 118 <= bpm < 124:
            return "House / Tech House"
        if 110 <= bpm < 118:
            return "Deep House"
        if 85 <= bpm < 110:
            return "Hip-Hop / Trap"
        if bpm < 85:
            return "Ambient / Chill"

    return ""   # unknown — caller falls back to artist-name query


# =========================================================
# CAMELOT WHEEL — harmonic mixing compatibility
# =========================================================
_CAMELOT = {
    ('G#', 'min'): (1,  'A'), ('D#', 'min'): (2,  'A'), ('A#', 'min'): (3,  'A'),
    ('F',  'min'): (4,  'A'), ('C',  'min'): (5,  'A'), ('G',  'min'): (6,  'A'),
    ('D',  'min'): (7,  'A'), ('A',  'min'): (8,  'A'), ('E',  'min'): (9,  'A'),
    ('B',  'min'): (10, 'A'), ('F#', 'min'): (11, 'A'), ('C#', 'min'): (12, 'A'),
    ('B',  'maj'): (1,  'B'), ('F#', 'maj'): (2,  'B'), ('C#', 'maj'): (3,  'B'),
    ('G#', 'maj'): (4,  'B'), ('D#', 'maj'): (5,  'B'), ('A#', 'maj'): (6,  'B'),
    ('F',  'maj'): (7,  'B'), ('C',  'maj'): (8,  'B'), ('G',  'maj'): (9,  'B'),
    ('D',  'maj'): (10, 'B'), ('A',  'maj'): (11, 'B'), ('E',  'maj'): (12, 'B'),
}


def camelot_label(key, mode):
    c = _CAMELOT.get((key, mode))
    return f"{c[0]}{c[1]}" if c else "?"


def camelot_compatible(key1, mode1, key2, mode2, max_steps=1):
    """True if two keys are harmonically compatible for DJ mixing (Camelot wheel)."""
    c1 = _CAMELOT.get((key1, mode1))
    c2 = _CAMELOT.get((key2, mode2))
    if not c1 or not c2:
        return False
    n1, l1 = c1
    n2, l2 = c2
    if n1 == n2 and l1 == l2:
        return True   # exact same key
    if n1 == n2:
        return True   # relative major/minor (always harmonically compatible)
    if l1 == l2:
        dist = min(abs(n1 - n2), 12 - abs(n1 - n2))
        return dist <= max_steps
    return False


# =========================================================
# SPOTIFY  (optional — large pre-computed BPM+key pool)
# Credentials stored in ~/.audiolens_spotify.json (never committed)
# =========================================================
# Credentials are never hard-coded here.
# Place them in ~/.audiolens_spotify.json:  {"client_id": "...", "client_secret": "..."}
# Or set environment variables SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.
_SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
_SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
_SPOTIFY_CONF          = os.path.expanduser("~/.audiolens_spotify.json")
_SPOTIFY_KEY_MAP       = {0:'C', 1:'C#', 2:'D', 3:'D#', 4:'E', 5:'F',
                          6:'F#', 7:'G', 8:'G#', 9:'A', 10:'A#', 11:'B'}


class SpotifyClient:
    _BASE = "https://api.spotify.com/v1"
    _AUTH = "https://accounts.spotify.com/api/token"

    def __init__(self, client_id: str, client_secret: str):
        self._id     = client_id.strip()
        self._secret = client_secret.strip()
        self._token  = None
        self._expiry = 0.0

    def _refresh_token(self):
        creds = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
        r = requests.post(
            self._AUTH,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10, verify=False,
        )
        r.raise_for_status()
        d = r.json()
        self._token  = d["access_token"]
        self._expiry = time.time() + d.get("expires_in", 3600) - 60

    def _ensure_token(self):
        if not self._token or time.time() >= self._expiry:
            self._refresh_token()

    def get(self, path: str, params: dict = None):
        self._ensure_token()
        r = requests.get(
            f"{self._BASE}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self._token}"},
            params=params or {},
            timeout=12, verify=False,
        )
        r.raise_for_status()
        return r.json()

    def search_artist_id(self, name: str):
        try:
            d = self.get("search", {"q": name, "type": "artist", "limit": 1})
            items = d.get("artists", {}).get("items", [])
            return items[0]["id"] if items else None
        except Exception:
            return None

    def artist_top_tracks(self, artist_id: str, market: str = "US") -> list:
        try:
            d = self.get(f"artists/{artist_id}/top-tracks", {"market": market})
            return d.get("tracks", [])
        except Exception:
            return []

    def related_artist_ids(self, artist_id: str, limit: int = 3) -> list:
        try:
            d = self.get(f"artists/{artist_id}/related-artists")
            return [a["id"] for a in d.get("artists", [])[:limit]]
        except Exception:
            return []

    def audio_features_batch(self, track_ids: list) -> dict:
        out = {}
        for i in range(0, len(track_ids), 100):
            chunk = track_ids[i:i + 100]
            try:
                d = self.get("audio-features", {"ids": ",".join(chunk)})
                for af in d.get("audio_features") or []:
                    if af and af.get("id"):
                        out[af["id"]] = af
            except Exception:
                pass
        return out


def _load_spotify():
    try:
        with open(_SPOTIFY_CONF) as f:
            d = json.load(f)
        cid = d.get("client_id", "").strip()
        sec = d.get("client_secret", "").strip()
        if cid and sec:
            return SpotifyClient(cid, sec)
    except Exception:
        pass
    # Fall back to built-in credentials
    if _SPOTIFY_CLIENT_ID and _SPOTIFY_CLIENT_SECRET:
        return SpotifyClient(_SPOTIFY_CLIENT_ID, _SPOTIFY_CLIENT_SECRET)
    return None


def _save_spotify(client_id: str, client_secret: str):
    with open(_SPOTIFY_CONF, "w") as f:
        json.dump({"client_id": client_id.strip(),
                   "client_secret": client_secret.strip()}, f)


def spotify_mix_search(sp: SpotifyClient, style: str, ref_artist: str,
                       bpm: float, key: str, mode: str,
                       bpm_tol: int, max_steps: int,
                       ref_track_id: str = "") -> list:
    """Fetch tracks via Spotify API and filter by BPM + Camelot.
    No audio download needed — Spotify audio-features supplies tempo, key, mode.
    Raises on API failure so caller can fall back to iTunes."""
    artists = []
    if style and style in _STYLE_QUERIES:
        artists = list(_STYLE_QUERIES[style])[:5]
    if ref_artist and ref_artist not in artists:
        artists.insert(0, ref_artist)
    if not artists:
        artists = ["deadmau5", "Armin van Buuren", "FISHER", "Adam Beyer"]

    tracks = {}  # track_id → track dict

    def _collect(name):
        aid = sp.search_artist_id(name)
        if not aid:
            return
        for t in sp.artist_top_tracks(aid):
            tid = t.get("id")
            if tid and tid not in tracks:
                tracks[tid] = t
        for rel_id in sp.related_artist_ids(aid, 2):
            for t in sp.artist_top_tracks(rel_id):
                tid = t.get("id")
                if tid and tid not in tracks:
                    tracks[tid] = t

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(_collect, artists[:5]))

    tracks.pop(ref_track_id, None)
    if not tracks:
        return []

    af_map = sp.audio_features_batch(list(tracks.keys()))
    # If audio-features returned nothing at all (endpoint restricted for this app)
    # raise so the caller can fall back to iTunes.
    if not af_map:
        raise RuntimeError("audio-features returned no data (endpoint may be restricted)")

    check_key = bool(key and mode)   # skip Camelot filter when ref key is unknown

    results = []
    for tid, track in tracks.items():
        af = af_map.get(tid)
        if not af:
            continue
        t_bpm  = af.get("tempo", 0)
        t_key  = af.get("key", -1)
        t_mode = af.get("mode", -1)
        if t_key < 0 or t_mode < 0:
            continue
        if abs(t_bpm - bpm) > bpm_tol:
            continue
        k_name = _SPOTIFY_KEY_MAP.get(t_key)
        m_name = "maj" if t_mode == 1 else "min"
        if not k_name:
            continue
        if check_key and not camelot_compatible(key, mode, k_name, m_name, max_steps):
            continue
        artist_name = ", ".join(a["name"] for a in track.get("artists", []))
        results.append({
            "track_id":    tid,
            "name":        track.get("name", ""),
            "artist":      artist_name,
            "album":       track.get("album", {}).get("name", ""),
            "preview_url": track.get("preview_url") or "",
            "genre":       style,
            "match_bpm":   round(t_bpm, 1),
            "match_key":   k_name,
            "match_mode":  m_name,
        })
    return results


# =========================================================
# ITUNES SEARCH
# =========================================================
def itunes_search(query: str):
    """Search iTunes for songs or artists.
    Runs two parallel requests — a general search and an artist-specific search —
    then merges and deduplicates so both song-name and artist-name queries work well."""
    q = query.strip()
    if not q:
        return [], "Please enter a song or artist name."

    def _fetch(params):
        try:
            return requests.get(
                "https://itunes.apple.com/search",
                params={"country": "us", "entity": "song", **params},
                timeout=12, verify=False,
            ).json().get("results", [])
        except Exception:
            return []

    # Run general search and artist-term search in parallel
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_gen    = ex.submit(_fetch, {"term": q, "limit": 50})
        f_artist = ex.submit(_fetch, {"term": q, "limit": 50,
                                      "attribute": "artistTerm"})
        gen_res    = f_gen.result()
        artist_res = f_artist.result()

    seen_ids   = set()
    seen_pairs = set()
    rows = []
    for t in gen_res + artist_res:
        tid = t.get("trackId")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        name   = t.get("trackName", "")
        artist = t.get("artistName", "")
        pair   = (name.lower(), artist.lower())
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        score = max(_sim(q, name), _sim(q, artist) * 0.95)
        rows.append({
            "track_id":    str(tid),
            "name":        name,
            "artist":      artist,
            "album":       t.get("collectionName", ""),
            "preview_url": t.get("previewUrl", ""),
            "genre":       t.get("primaryGenreName", ""),
            "score":       score,
        })

    if not rows:
        return [], f'No results for "{query}".'

    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:8], None


def itunes_mix_search(queries: list, limit_per: int = 20) -> list:
    """Search iTunes for songs by each artist in the query list.
    Post-filters by artist name similarity so we get songs BY the target
    artists, not unrelated songs that happen to share a word with the query."""
    seen, results = set(), []

    def _fetch_one(q):
        try:
            return q, requests.get(
                "https://itunes.apple.com/search",
                params={"term": q, "entity": "song", "limit": limit_per,
                        "country": "us", "attribute": "artistTerm"},
                timeout=12, verify=False,
            ).json().get("results", [])
        except Exception:
            return q, []

    with ThreadPoolExecutor(max_workers=4) as ex:
        all_results = list(ex.map(_fetch_one, queries))

    for q, tracks in all_results:
        for t in tracks:
            tid = t.get("trackId")
            if not tid or tid in seen:
                continue
            preview = t.get("previewUrl", "")
            if not preview:
                continue
            # Only keep songs actually by the target artist (sim > 0.4)
            if _sim(q, t.get("artistName", "")) < 0.4:
                continue
            seen.add(tid)
            results.append({
                "track_id":    str(tid),
                "name":        t.get("trackName", ""),
                "artist":      t.get("artistName", ""),
                "album":       t.get("collectionName", ""),
                "preview_url": preview,
                "genre":       t.get("primaryGenreName", ""),
            })
    return results


def _m4a_to_wav(m4a_path: str):
    """Convert M4A to WAV using afconvert (macOS) or ffmpeg (cross-platform)."""
    wav_path = m4a_path + ".wav"
    # macOS built-in
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@44100", m4a_path, wav_path],
                timeout=20, capture_output=True,
            )
            if r.returncode == 0 and os.path.exists(wav_path):
                return wav_path
        except Exception:
            pass
    # ffmpeg fallback (cross-platform, if installed)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", m4a_path, wav_path],
            timeout=20, capture_output=True,
        )
        if r.returncode == 0 and os.path.exists(wav_path):
            return wav_path
    except Exception:
        pass
    if os.path.exists(wav_path):
        try:
            os.unlink(wav_path)
        except Exception:
            pass
    return None


def analyze_preview_url(preview_url: str):
    """Download a preview URL and run local DSP analysis on it."""
    tmp_path = None
    wav_path = None
    try:
        resp = requests.get(preview_url, timeout=20, verify=False)
        resp.raise_for_status()
        suffix = ".m4a" if ".m4a" in preview_url else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        analyze_path = tmp_path
        if suffix == ".m4a":
            wav_path = _m4a_to_wav(tmp_path)
            if wav_path:
                analyze_path = wav_path
        res = analyze_file(analyze_path)
        if res["bpm"] and res["key"]:
            return res["bpm"], res["key"], res["mode"], None
        return None, None, None, None
    except Exception as e:
        return None, None, None, f"Preview analysis failed: {e}"
    finally:
        for p in (wav_path, tmp_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


# =========================================================
# DSP — BPM
# =========================================================
def _onset_env(data, sr, hop=256, fsize=2048):
    if len(data) < fsize:
        data = np.pad(data, (0, fsize - len(data)))
    nf = max(1, 1 + (len(data) - fsize) // hop)
    env = np.zeros(nf)
    hann = np.hanning(fsize)
    prev = None
    for i in range(nf):
        f = data[i * hop:i * hop + fsize]
        if len(f) < fsize:
            f = np.pad(f, (0, fsize - len(f)))
        mag = np.abs(np.fft.rfft(f * hann))
        if prev is not None:
            env[i] = np.sum(np.maximum(mag - prev, 0))
        prev = mag
    return env


def _band_env(data, sr, lo, hi, hop=256, fsize=1024):
    sos = signal.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
    flt = signal.sosfilt(sos, data)
    if len(flt) < fsize:
        flt = np.pad(flt, (0, fsize - len(flt)))
    nf = max(1, 1 + (len(flt) - fsize) // hop)
    env = np.zeros(nf)
    for i in range(nf):
        f = flt[i * hop:i * hop + fsize]
        if len(f) < fsize:
            f = np.pad(f, (0, fsize - len(f)))
        env[i] = np.sum(f**2)
    env = np.log1p(env)
    diff = np.diff(env, prepend=env[0])
    return np.maximum(diff, 0)


def _ac_bpm(env, env_sr, lo=60, hi=200):
    env = env - env.mean()
    if np.abs(env).max() < 1e-8:
        return {}
    ac = signal.correlate(env, env, mode="full")
    ac = ac[len(ac) // 2:]
    ac /= ac[0] + 1e-8
    lmin = int(env_sr * 60 / hi)
    lmax = min(int(env_sr * 60 / lo), len(ac) - 1)
    if lmin < 1 or lmin >= lmax:
        return {}
    sc = {}
    for lag in range(lmin, lmax + 1):
        bpm = 60 * env_sr / lag
        s = ac[lag]
        for m, w in [(2, 0.5), (3, 0.25), (4, 0.125)]:
            idx = lag * m
            if idx < len(ac):
                s += w * ac[idx]
        sc[round(float(bpm), 2)] = float(s)
    return sc


def _merge(scs, lo=60, hi=200, res=0.5):
    grid = np.arange(lo, hi + res, res)
    total = np.zeros(len(grid))
    for sc, w in scs:
        if not sc:
            continue
        mx = max(sc.values(), default=0)
        if mx <= 0:
            continue
        for bpm, s in sc.items():
            idx = int(round((bpm - lo) / res))
            if 0 <= idx < len(total):
                total[idx] += w * max(s / mx, 0)
    return grid, total


def _fft_bpm(env, env_sr, lo=60, hi=200, res=0.5):
    """BPM scores from FFT of onset envelope — finds the kick frequency even when
    a 2-beat phrase fools the autocorrelation into returning half the true tempo."""
    e = env - env.mean()
    if np.abs(e).max() < 1e-8:
        return {}
    n = max(len(e), 8192)
    n = 2 ** int(np.ceil(np.log2(n)))
    amps = np.abs(np.fft.rfft(e, n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / env_sr)
    lo_hz, hi_hz = lo / 60.0, hi / 60.0
    mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    sc = {}
    for f, a in zip(freqs[mask], amps[mask]):
        bpm = round(f * 60.0 / res) * res
        if lo <= bpm <= hi:
            sc[bpm] = sc.get(bpm, 0) + float(a)
    mx = max(sc.values()) if sc else 1.0
    return {b: v / mx for b, v in sc.items()}


def _resolve(grid, total, lo=60, hi=200):
    best = float(grid[np.argmax(total)])
    cands = {best: total[np.argmax(total)]}
    for f in [0.5, 2.0]:
        alt = best * f
        if lo <= alt <= hi:
            ai = int(round((alt - lo) / 0.5))
            if 0 <= ai < len(total):
                cands[alt] = total[ai]
    return round(float(max(cands, key=lambda b: cands[b] * (1 - 0.1 * abs(b - 120) / 120))), 1)


# =========================================================
# DSP — KEY
# =========================================================
def _norm(a):
    return (a - a.mean()) / (a.std() + 1e-8)


def _build_profiles():
    # Krumhansl-Schmuckler (1990) — from listening-experiment probe-tone ratings
    KM = _norm(np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]))
    Km = _norm(np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]))
    # Temperley (2007) — re-weighted for corpus analysis
    TM = _norm(np.array([5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]))
    Tm = _norm(np.array([5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]))
    # Shaath (2011) — tuned for contemporary pop/electronic music
    SM = _norm(np.array([6.6, 2.0, 3.5, 2.3, 4.6, 3.9, 2.3, 5.4, 2.3, 3.9, 2.3, 3.2]))
    Sm = _norm(np.array([6.5, 2.8, 3.5, 5.4, 2.7, 3.6, 2.6, 4.8, 4.0, 2.8, 3.5, 3.2]))
    # Blend: equal weight across all three — covers classical, corpus, and modern styles
    MAJ = (KM + TM + SM) / 3.0
    MIN = (Km + Tm + Sm) / 3.0
    return np.apply_along_axis(
        _norm,
        1,
        np.vstack([
            np.stack([np.roll(MAJ, r) for r in range(12)]),
            np.stack([np.roll(MIN, r) for r in range(12)]),
        ]),
    )


_PROFILES = _build_profiles()


def _chroma(data, sr, hop=512, nfft=8192):
    """Standard chromagram via octave-reduction of STFT magnitudes.
    Each FFT bin maps directly to its pitch class (0–11) — no harmonic tricks,
    no strict-cent threshold.  Range 100–5000 Hz gives good resolution while
    avoiding sub-bass noise and cymbal clutter."""
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)

    # Build pitch-class assignment matrix (12, nbins)
    pc_map = np.full(len(freqs), -1, dtype=int)
    for i, f in enumerate(freqs):
        if 100.0 <= f <= 5000.0:
            pc_map[i] = int(round(12.0 * np.log2(f / 440.0) + 69.0)) % 12
    P = np.zeros((12, len(freqs)))
    for pc in range(12):
        P[pc, pc_map == pc] = 1.0

    hann = np.hanning(nfft)
    nf = max(1, 1 + max(0, len(data) - nfft) // hop)
    pad = np.zeros(nfft + (nf - 1) * hop)
    pad[:min(len(data), len(pad))] = data[:min(len(data), len(pad))]

    ch = np.zeros((12, nf))
    bsize = 128          # process in batches — limits RAM to ~16 MB per batch
    for b0 in range(0, nf, bsize):
        b1 = min(b0 + bsize, nf)
        idx = (b0 + np.arange(b1 - b0))[:, None] * hop + np.arange(nfft)
        mag = np.abs(np.fft.rfft(pad[idx] * hann, axis=1))  # (batch, nbins)
        ch[:, b0:b1] = P @ mag.T                             # (12, batch)

    ch = np.log1p(ch)

    # L1-normalise each frame so amplitude doesn't skew the mean
    col_sum = ch.sum(0, keepdims=True)
    col_sum[col_sum < 1e-8] = 1.0
    ch /= col_sum

    # Zero out near-silent frames so they don't dilute the temporal average
    en = ch.sum(0)
    thr = np.percentile(en, 20)
    if thr > 0:
        ch[:, en < thr] = 0.0

    return ch


def detect_key(data, sr):
    """Detect musical key and mode.  Uses librosa chroma_cens when available
    (CQT-based, NNLS-separated — the closest open-source approximation to the
    HPCP algorithm used by professional tools like Tunebat / Essentia).
    Falls back to our STFT-based approach if librosa is not installed."""
    if _HAS_LIBROSA:
        return _detect_key_librosa(data, sr)
    return _detect_key_dsp(data, sr)


def _detect_key_librosa(data, sr):
    try:
        y = data.astype(np.float32)
        # Resample to 22050 for consistent analysis
        if sr != 22050:
            y = _librosa.resample(y, orig_sr=sr, target_sr=22050)
            sr = 22050

        # chroma_cens: CQT → NNLS separation → L1 norm → quantisation → smoothing
        # bins_per_octave=36 gives 1/3-semitone resolution — far better than STFT
        chroma = _librosa.feature.chroma_cens(y=y, sr=sr, bins_per_octave=36)  # (12, T)

        # Segment voting: split into 8-second chunks, vote per chunk, then average.
        # Uniform weight — avoids loud drops masking the real key.
        chunk = int(sr * 8 / 512)  # frames per 8-second window (hop_length=512 default)
        if chroma.shape[1] <= chunk:
            votes = _PROFILES @ _norm(chroma.mean(1))
        else:
            votes = np.zeros(24)
            n = 0
            for start in range(0, chroma.shape[1] - chunk + 1, chunk // 2):
                seg = chroma[:, start:start + chunk]
                cf  = seg.mean(1)
                if cf.max() < 1e-8:
                    continue
                votes += _PROFILES @ _norm(cf)
                n += 1
            if n == 0:
                votes = _PROFILES @ _norm(chroma.mean(1))

        bi   = int(np.argmax(votes))
        mode = "maj" if bi < 12 else "min"
        key  = bi % 12

        sc_s = np.sort(votes)[::-1]
        conf = float(np.clip((sc_s[0] - sc_s[1]) / (sc_s[0] - sc_s[-1] + 1e-8), 0, 1))

        disp = chroma.mean(1)
        disp = disp / disp.max() if disp.max() > 0 else disp
        return NOTE_NAMES[key], mode, conf, disp
    except Exception:
        return _detect_key_dsp(data, sr)


def _detect_key_dsp(data, sr):
    """STFT-based fallback key detector (used when librosa is unavailable)."""
    try:
        tgt = 22050
        if sr != tgt:
            g = np.gcd(int(sr), tgt)
            data = signal.resample_poly(data, tgt // g, sr // g)
            sr = tgt

        sos = signal.butter(4, [100.0, 5000.0], btype="bandpass",
                            fs=float(sr), output="sos")
        data_f = signal.sosfilt(sos, data)

        cf = _chroma(data_f, sr).mean(1)
        cf = _norm(cf)
        global_scores = _PROFILES @ cf

        win  = min(int(sr * 8), len(data_f))
        hop_s = int(sr * 4)
        votes = np.zeros(24)
        n_segs = 0
        for start in range(0, max(1, len(data_f) - win + 1), hop_s):
            seg = data_f[start:start + win]
            if len(seg) < sr * 2:
                continue
            if np.sqrt(np.mean(seg ** 2)) < 1e-5:
                continue
            sc = _chroma(seg, sr).mean(1)
            if sc.max() < 1e-8:
                continue
            votes += _PROFILES @ _norm(sc)
            n_segs += 1

        n_segs = max(n_segs, 1)
        combined = global_scores * 2.0 + votes / n_segs * 2.0
        bi   = int(np.argmax(combined))
        mode = "maj" if bi < 12 else "min"
        key  = bi % 12

        sc_s = np.sort(combined)[::-1]
        conf = float(np.clip((sc_s[0] - sc_s[1]) / (sc_s[0] - sc_s[-1] + 1e-8), 0, 1))

        disp = cf / cf.max() if cf.max() > 0 else cf
        return NOTE_NAMES[key], mode, conf, disp
    except Exception:
        return None, None, 0.0, np.zeros(12)


def analyze_file(path, lo=60, hi=200):
    res = {"bpm": None, "key": None, "mode": None, "confidence": 0.0, "chroma": np.zeros(12)}
    try:
        data, sr = sf.read(path)
        if data.ndim > 1:
            data = data.mean(1)
        data = data.astype(np.float64)
        mx = np.abs(data).max()
        if mx > 0:
            data /= mx
        k, m, c, ch = detect_key(data, sr)
        res.update(key=k, mode=m, confidence=c, chroma=ch)
        tgt = 22050
        if sr != tgt:
            g = np.gcd(int(sr), tgt)
            data = signal.resample_poly(data, tgt // g, sr // g)
            sr = tgt
        hop = 256
        env_sr = sr / hop
        b_sc = _ac_bpm(_band_env(data, sr, 30, 200, hop), env_sr, lo, hi)
        m_sc = _ac_bpm(_band_env(data, sr, 200, 2000, hop), env_sr, lo, hi)
        f_env = _onset_env(data, sr, hop)
        if f_env.max() > 0:
            f_env /= f_env.max()
        f_sc = _ac_bpm(f_env, env_sr, lo, hi)
        fft_sc = _fft_bpm(f_env, env_sr, lo, hi)
        grid, tot = _merge([(b_sc, 1.5), (m_sc, 1.0), (f_sc, 1.2), (fft_sc, 5.0)], lo, hi)
        if tot.max() >= 1e-8:
            res["bpm"] = _resolve(grid, tot, lo, hi)
    except Exception:
        pass
    return res


# =========================================================
# CIRCLE OF FIFTHS CANVAS
# =========================================================
class CircleOfFifthsCanvas(tk.Canvas):
    # Clockwise from top (C = 12 o'clock). Traditional circle of fifths notation.
    _MAJOR_LABELS = ["C", "G", "D", "A", "E", "B", "Gb", "Db", "Ab", "Eb", "Bb", "F"]
    _MINOR_LABELS = ["Am", "Em", "Bm", "F#m", "C#m", "G#m", "Ebm", "Bbm", "Fm", "Cm", "Gm", "Dm"]
    _MAJ_POS = {"C":0,"G":1,"D":2,"A":3,"E":4,"B":5,"F#":6,"C#":7,"G#":8,"D#":9,"A#":10,"F":11}
    _MIN_POS = {"A":0,"E":1,"B":2,"F#":3,"C#":4,"G#":5,"D#":6,"A#":7,"F":8,"C":9,"G":10,"D":11}

    _GLOW   = "#3b2899"
    _BORDER = "#b09eff"

    def __init__(self, master, **kw):
        super().__init__(master, bg=PANEL, highlightthickness=0, **kw)
        self._key = None
        self._mode = None
        self.bind("<Configure>", lambda _: self._draw())

    def set(self, key, mode):
        self._key = key
        self._mode = mode
        self._draw()

    def clear(self):
        self._key = None
        self._mode = None
        self._draw()

    def _arc_pts(self, cx, cy, r, a1, a2, steps=36):
        pts = []
        for i in range(steps + 1):
            a = math.radians(a1 + (a2 - a1) * i / steps)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        return pts

    def _ring_seg(self, cx, cy, r_in, r_out, a1, a2, fill, outline=None, width=2):
        pts = self._arc_pts(cx, cy, r_out, a1, a2) + self._arc_pts(cx, cy, r_in, a2, a1)
        self.create_polygon(pts, fill=fill, outline=outline if outline is not None else PANEL, width=width)

    def _draw(self):
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 60 or H < 60:
            return

        cx, cy = W / 2, H / 2
        R = min(W, H) / 2 - 10

        r_out  = R
        r_mid  = R * 0.635
        r_in   = R * 0.375
        r_core = R * 0.225

        fmaj      = max(8,  min(15, int(R * 0.140)))
        fmin      = max(7,  min(12, int(R * 0.103)))
        fcore     = max(12, min(24, int(R * 0.200)))
        fcore_sub = max(7,  min(14, int(R * 0.112)))

        maj_hi = self._MAJ_POS.get(self._key) if self._mode == "maj" and self._key else None
        min_hi = self._MIN_POS.get(self._key) if self._mode == "min" and self._key else None

        for i in range(12):
            a_mid = -90 + i * 30
            a1, a2 = a_mid - 15, a_mid + 15
            is_maj = (i == maj_hi)
            is_min = (i == min_hi)

            # Glow behind highlighted segment (drawn first, larger)
            if is_maj:
                self._ring_seg(cx, cy, r_mid - 4, r_out + 4, a1 - 2, a2 + 2,
                               self._GLOW, outline=PANEL, width=1)
            if is_min:
                self._ring_seg(cx, cy, r_in - 4, r_mid + 4, a1 - 2, a2 + 2,
                               self._GLOW, outline=PANEL, width=1)

            # Outer (major) ring
            self._ring_seg(cx, cy, r_mid, r_out, a1, a2,
                           ACCENT if is_maj else BTN_BG,
                           outline=self._BORDER if is_maj else PANEL,
                           width=3 if is_maj else 2)
            # Inner (minor) ring
            self._ring_seg(cx, cy, r_in, r_mid, a1, a2,
                           ACCENT if is_min else CARD,
                           outline=self._BORDER if is_min else PANEL,
                           width=3 if is_min else 2)

            rad  = math.radians(a_mid)
            rmaj = (r_mid + r_out) / 2
            rmin = (r_in  + r_mid) / 2

            self.create_text(
                cx + rmaj * math.cos(rad), cy + rmaj * math.sin(rad),
                text=self._MAJOR_LABELS[i],
                fill="white" if is_maj else TXT,
                font=("Arial", fmaj + (2 if is_maj else 0), "bold" if is_maj else "normal"),
            )
            self.create_text(
                cx + rmin * math.cos(rad), cy + rmin * math.sin(rad),
                text=self._MINOR_LABELS[i],
                fill="white" if is_min else TXT2,
                font=("Arial", fmin + (1 if is_min else 0), "bold" if is_min else "normal"),
            )

        # Center circle
        has_key = bool(self._key and self._mode)
        self.create_oval(
            cx - r_core, cy - r_core, cx + r_core, cy + r_core,
            fill=ACCENT if has_key else CARD,
            outline=self._BORDER if has_key else TXT3,
            width=2,
        )
        if has_key:
            if self._mode == "maj" and maj_hi is not None:
                display = self._MAJOR_LABELS[maj_hi]
                mode_str = "Major"
            elif self._mode == "min" and min_hi is not None:
                display = self._MINOR_LABELS[min_hi].rstrip("m") or self._MINOR_LABELS[min_hi]
                mode_str = "Minor"
            else:
                display, mode_str = self._key, ""
            self.create_text(
                cx, cy - r_core * 0.18,
                text=display,
                fill="white",
                font=("Arial", fcore, "bold"),
            )
            self.create_text(
                cx, cy + r_core * 0.52,
                text=mode_str,
                fill="#ccbbff",
                font=("Arial", fcore_sub, "normal"),
            )


# =========================================================
# SPLASH SCREEN
# =========================================================
class SplashScreen(tk.Toplevel):
    _W, _H = 420, 300

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        W, H = self._W, self._H
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        self.configure(bg=BG)

        cv = tk.Canvas(self, width=W, height=H, bg=BG, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self._cv = cv

        self._draw_card(cv, 14, 14, W - 14, H - 14, r=20)

        self._icon = cv.create_text(
            W // 2, 88, text="⊙",
            font=("Helvetica Neue", 58, "bold"), fill=ACCENT,
        )

        cx = W // 2
        cv.create_text(cx - 3, 152, text="Audio",
                       font=("Helvetica Neue", 30, "bold"), fill=TXT, anchor="e")
        cv.create_text(cx + 3, 152, text="Lens",
                       font=("Helvetica Neue", 30, "bold"), fill=ACCENT, anchor="w")
        cv.create_text(cx, 178, text="v 2.0",
                       font=("Helvetica Neue", 10), fill=TXT3)

        cv.create_line(cx - 72, 200, cx + 72, 200, fill=TXT3, width=1)

        cv.create_text(cx, 218, text="by Yael Amitay",
                       font=("Helvetica Neue", 11), fill=TXT2)

        self._dots_item = cv.create_text(
            cx, 260, text="Loading   ",
            font=("Helvetica Neue", 13, "bold"), fill=TXT2,
        )

        self._pulse_n = 0
        self._dot_n = 0
        self._anim_id = None
        self._animate()
        self.update()

    def _draw_card(self, cv, x1, y1, x2, y2, r):
        kw_fill = dict(fill=PANEL, outline=PANEL)
        cv.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90, style="pieslice", **kw_fill)
        cv.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90, style="pieslice", **kw_fill)
        cv.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90, style="pieslice", **kw_fill)
        cv.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90, style="pieslice", **kw_fill)
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, **kw_fill)
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, **kw_fill)

        kw_ol = dict(outline=ACCENT, width=1)
        cv.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90, style="arc", **kw_ol)
        cv.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90, style="arc", **kw_ol)
        cv.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90, style="arc", **kw_ol)
        cv.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90, style="arc", **kw_ol)
        cv.create_line(x1 + r, y1, x2 - r, y1, fill=ACCENT, width=1)
        cv.create_line(x2, y1 + r, x2, y2 - r, fill=ACCENT, width=1)
        cv.create_line(x2 - r, y2, x1 + r, y2, fill=ACCENT, width=1)
        cv.create_line(x1, y2 - r, x1, y1 + r, fill=ACCENT, width=1)

    _PULSE = [ACCENT, "#9a7dfd", "#b9a8fe", "#c8bcfe", "#b9a8fe", "#9a7dfd"]

    def _animate(self):
        self._cv.itemconfigure(self._icon, fill=self._PULSE[self._pulse_n % len(self._PULSE)])
        self._pulse_n += 1
        dots = ["   ", ".  ", ".. ", "..."]
        self._cv.itemconfigure(self._dots_item, text="Loading" + dots[self._dot_n % 4])
        self._dot_n += 1
        self._anim_id = self.after(370, self._animate)

    def close(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self.destroy()


# =========================================================
# MAIN APP
# =========================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("AudioLens")
        self.configure(fg_color=BG)
        w, h = 960, 860
        x = (self.winfo_screenwidth() - w) // 2
        y = max(30, (self.winfo_screenheight() - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(True, True)
        self.minsize(820, 640)
        self._splash = SplashScreen(self)
        self._build()
        self.after(1500, self._launch)

    def _launch(self):
        self._splash.close()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _build(self):
        top = ctk.CTkFrame(self, fg_color=PANEL, height=46, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)
        logo = ctk.CTkFrame(top, fg_color="transparent")
        logo.pack(side="left", padx=14)
        ctk.CTkLabel(logo, text="⊙", text_color=ACCENT,
                     font=("Helvetica Neue", 27, "bold")).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(logo, text="Audio", text_color=TXT,
                     font=("Helvetica Neue", 22, "bold")).pack(side="left")
        ctk.CTkLabel(logo, text="Lens", text_color=ACCENT,
                     font=("Helvetica Neue", 22, "bold")).pack(side="left")
        ctk.CTkLabel(logo, text="v2.0", text_color=TXT3,
                     font=("Helvetica Neue", 10)).pack(side="left", padx=(6, 0), anchor="s", pady=(0, 4))
        ctk.CTkLabel(top, text="© Yael Amitay", text_color=TXT3, font=("Arial", 11)).pack(side="right", padx=18)

        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=14, pady=(12, 16))

        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)

        # ── LEFT PANEL  (search + upload inputs) ──────────────────────────────
        self._left_panel = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        self._left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        left = self._left_panel

        ctk.CTkLabel(left, text="Search by Song / Artist", text_color=TXT,
                     font=("Arial", 13, "bold")).pack(pady=(14, 2), padx=14, anchor="w")
        ctk.CTkLabel(left, text="iTunes Search  ·  top 8 matches", text_color=TXT3,
                     font=("Arial", 10)).pack(padx=14, anchor="w")

        self.q_entry = ctk.CTkEntry(
            left,
            placeholder_text="e.g.  Blinding Lights  or  The Weeknd",
            height=36, corner_radius=18,
            fg_color=BTN_BG, border_color="#2e3250",
            text_color=TXT, font=("Arial", 12),
        )
        self.q_entry.pack(fill="x", padx=14, pady=(8, 6))
        self.q_entry.bind("<Return>", lambda _: self._search())

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=14)
        self.search_btn = ctk.CTkButton(
            btn_row, text="Search", command=self._search,
            height=34, corner_radius=17,
            fg_color=ACCENT, hover_color="#6347e0",
            text_color="white", font=("Arial", 12, "bold"),
        )
        self.search_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="↺", command=self._reset,
            width=42, height=34, corner_radius=17,
            fg_color="#3d4273", hover_color="#4e5490",
            text_color="white", font=("Arial", 16, "bold"),
        ).pack(side="left")

        self.status_lbl = ctk.CTkLabel(left, text="", text_color=TXT3,
                                        font=("Arial", 13), wraplength=340)
        self.status_lbl.pack(pady=(5, 2), padx=14)

        # ── Upload section — packed at bottom BEFORE results_scroll so it's
        #    always visible regardless of how tall the scroll area grows.
        #    (With side="bottom" each item anchors to the bottom in reverse order)
        self.file_lbl = ctk.CTkLabel(left, text="No file selected",
                                      text_color=TXT3, font=("Arial", 10))
        self.file_lbl.pack(side="bottom", anchor="w", padx=14, pady=(0, 12))

        self.upload_btn = ctk.CTkButton(
            left, text="Choose File…", command=self._pick_file,
            height=34, corner_radius=17,
            fg_color=ACCENT2, hover_color="#1fa882",
            text_color="#04120e", font=("Arial", 12, "bold"),
        )
        self.upload_btn.pack(side="bottom", fill="x", padx=14, pady=(4, 4))

        ctk.CTkLabel(left, text="WAV  ·  MP3  ·  FLAC  ·  OGG",
                     text_color=TXT3, font=("Arial", 10)).pack(side="bottom", anchor="w", padx=14)
        ctk.CTkLabel(left, text="Analyze Audio File", text_color=TXT,
                     font=("Arial", 13, "bold")).pack(side="bottom", anchor="w", padx=14)
        ctk.CTkFrame(left, fg_color="#2a2d3e", height=1).pack(side="bottom", fill="x", padx=14, pady=(4, 4))

        # ── Search results — fills remaining space between controls and upload ──
        self.results_scroll = ctk.CTkScrollableFrame(left, fg_color=BG, corner_radius=10)
        self.results_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # ── RIGHT PANEL  (analysis results) ────────────────────────────────
        right = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        ctk.CTkLabel(right, text="Analysis", text_color=TXT,
                     font=("Arial", 13, "bold")).pack(pady=(14, 2), padx=14, anchor="w")
        ctk.CTkLabel(right, text="BPM  ·  Key  ·  Camelot", text_color=TXT3,
                     font=("Arial", 10)).pack(padx=14, anchor="w")

        self.scan_status = ctk.CTkLabel(right, text="", text_color=TXT3,
                                         font=("Arial", 13), wraplength=320, justify="left")
        self.scan_status.pack(pady=(10, 0), padx=14, anchor="w")

        self.song_lbl = ctk.CTkLabel(right, text="", text_color=TXT2,
                                      font=("Arial", 11), wraplength=320)
        self.song_lbl.pack(pady=(4, 0), padx=14)

        bpm_row = ctk.CTkFrame(right, fg_color="transparent")
        bpm_row.pack(pady=(8, 2))
        self.bpm_lbl = ctk.CTkLabel(bpm_row, text="--.-", text_color=ACCENT,
                                     font=("Arial", 52, "bold"))
        self.bpm_lbl.pack(side="left")
        ctk.CTkLabel(bpm_row, text="BPM", text_color=TXT3,
                     font=("Arial", 15)).pack(side="left", padx=(6, 0), anchor="s", pady=(0, 11))
        self.camelot_lbl = ctk.CTkLabel(bpm_row, text="—", text_color=TXT3,
                                         font=("Arial", 26, "bold"))
        self.camelot_lbl.pack(side="left", padx=(18, 0), anchor="s", pady=(0, 9))

        self.chroma = CircleOfFifthsCanvas(right)
        self.chroma.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        # ── MIX MATCHES PANEL (row 1, spans both columns) ──
        mix = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        mix.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(7, 0))

        # Controls row
        ctrl = ctk.CTkFrame(mix, fg_color="transparent")
        ctrl.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(ctrl, text="Mix Matches", text_color=TXT,
                     font=("Arial", 13, "bold")).pack(side="left")

        # BPM tolerance slider with − / + step buttons
        ctk.CTkLabel(ctrl, text="BPM ±", text_color=TXT2,
                     font=("Arial", 11)).pack(side="left", padx=(14, 4))
        self._bpm_tol_lbl = ctk.CTkLabel(ctrl, text="8", text_color=ACCENT,
                                          font=("Arial", 11, "bold"), width=24)
        self._bpm_tol_lbl.pack(side="left")

        def _bpm_step(delta):
            v = max(0, min(30, int(self._bpm_tol_slider.get()) + delta))
            self._bpm_tol_slider.set(v)
            self._bpm_tol_lbl.configure(text=str(v))

        _btn_kw = dict(width=24, height=24, corner_radius=12,
                       fg_color=BTN_BG, hover_color="#4e5490",
                       text_color=TXT, font=("Arial", 13, "bold"))
        ctk.CTkButton(ctrl, text="−", command=lambda: _bpm_step(-1),
                      **_btn_kw).pack(side="left", padx=(6, 2))
        self._bpm_tol_slider = ctk.CTkSlider(
            ctrl, from_=0, to=30, number_of_steps=30, width=110,
            button_color=ACCENT, button_hover_color="#6347e0",
            progress_color=ACCENT, fg_color=BTN_BG,
            command=lambda v: self._bpm_tol_lbl.configure(text=str(int(v))),
        )
        self._bpm_tol_slider.set(8)
        self._bpm_tol_slider.pack(side="left")
        ctk.CTkButton(ctrl, text="+", command=lambda: _bpm_step(1),
                      **_btn_kw).pack(side="left", padx=(2, 0))

        # Key compatibility dropdown
        ctk.CTkLabel(ctrl, text="Key:", text_color=TXT2,
                     font=("Arial", 11)).pack(side="left", padx=(18, 4))
        self._key_compat_var = ctk.StringVar(value="±1 step")
        ctk.CTkOptionMenu(
            ctrl, variable=self._key_compat_var,
            values=["Same key", "±1 step", "±2 steps"],
            width=100, height=28, corner_radius=14,
            fg_color=BTN_BG, button_color="#3d4273",
            button_hover_color="#4e5490",
            text_color=TXT, font=("Arial", 11),
        ).pack(side="left")

        # Find button (rightmost)
        self._mix_find_btn = ctk.CTkButton(
            ctrl, text="Find Matches",
            command=self._find_matches,
            width=110, height=28, corner_radius=14,
            fg_color=ACCENT2, hover_color="#1fa882",
            text_color="#04120e", font=("Arial", 11, "bold"),
        )
        self._mix_find_btn.pack(side="right")


        self._mix_status = ctk.CTkLabel(
            mix, text="Select or analyze a song to find mix matches.",
            text_color=TXT3, font=("Arial", 11), wraplength=900,
        )
        self._mix_status.pack(anchor="w", padx=14, pady=(0, 0))

        self._mix_note = ctk.CTkLabel(
            mix, text="",
            text_color=TXT3, font=("Arial", 10), wraplength=900,
        )
        self._mix_note.pack(anchor="w", padx=14, pady=(0, 4))

        self._mix_scroll = ctk.CTkScrollableFrame(
            mix, fg_color=BG, corner_radius=10,
        )
        self._mix_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # Reference song data (set after analysis)
        self._ref_bpm        = None
        self._ref_key        = None
        self._ref_mode       = None
        self._detected_genre = ""
        self._match_gen      = 0
        self._spotify_client = _load_spotify()

    def _clear_results(self):
        self._stop_preview()
        for w in list(self.results_scroll.winfo_children()):
            w.destroy()

    def _set_busy(self, busy, scope="all"):
        s = "disabled" if busy else "normal"
        if scope in ("all", "search"):
            self.search_btn.configure(state=s)
        if scope in ("all", "upload"):
            self.upload_btn.configure(state=s)

    # ------ animated loading dots ------
    def _anim_start(self, key, label, base, color):
        self._anim_cancel(key)
        if not hasattr(self, "_anim"):
            self._anim = {}
        self._anim[key] = {"lbl": label, "base": base, "color": color, "n": 0, "id": None}
        self._anim_tick(key)

    def _anim_cancel(self, key=None):
        if not hasattr(self, "_anim"):
            return
        keys = list(self._anim.keys()) if key is None else [key]
        for k in keys:
            slot = self._anim.get(k)
            if slot and slot.get("id"):
                self.after_cancel(slot["id"])
            self._anim.pop(k, None)

    def _anim_tick(self, key):
        if not hasattr(self, "_anim") or key not in self._anim:
            return
        slot = self._anim[key]
        frames = [".  ", ".. ", "..."]
        try:
            slot["lbl"].configure(
                text=slot["base"] + frames[slot["n"] % 3],
                text_color=slot["color"],
            )
        except Exception:
            self._anim.pop(key, None)
            return
        slot["n"] += 1
        slot["id"] = self.after(450, lambda k=key: self._anim_tick(k))

    def _reset(self):
        self._reset_gen = getattr(self, "_reset_gen", 0) + 1
        self._sel_id    = getattr(self, "_sel_id",    0) + 1
        self._match_gen = getattr(self, "_match_gen", 0) + 1
        self._anim_cancel()
        self._set_busy(False, "all")
        self.q_entry.delete(0, "end")
        self.status_lbl.configure(text="",  text_color=TXT3)
        self.scan_status.configure(text="", text_color=TXT3)
        self.bpm_lbl.configure(text="--.-", text_color=ACCENT)
        self.camelot_lbl.configure(text="—", text_color=TXT3)
        self.song_lbl.configure(text="")
        self.file_lbl.configure(text="No file selected")
        self._clear_results()
        self.chroma.clear()
        # Reset mix panel
        self._ref_bpm = self._ref_key = self._ref_mode = None
        self._detected_genre = ""
        for w in list(self._mix_scroll.winfo_children()):
            w.destroy()
        self._mix_status.configure(
            text="Select or analyze a song to find mix matches.", text_color=TXT3)

    def _search(self):
        q = self.q_entry.get().strip()
        if not q:
            self.status_lbl.configure(text="Please enter a song or artist name.", text_color=ERR)
            return
        self._clear_results()
        self._set_busy(True, "search")
        self._set_busy(False, "upload")  # safety reset in case upload button got stuck
        self._anim_start("search", self.status_lbl, "Searching", TXT3)
        rg = getattr(self, "_reset_gen", 0)
        threading.Thread(target=self._do_search, args=(q, rg), daemon=True).start()

    def _do_search(self, q, reset_gen):
        try:
            results, err = itunes_search(q)
        except Exception as e:
            results, err = [], f"Search error: {e}"
        self.after(0, lambda: self._show_results(q, results, err, reset_gen))

    def _show_results(self, q, results, err, reset_gen=None):
        self._anim_cancel("search")  # always cancel — even on stale results
        if reset_gen is not None and reset_gen != getattr(self, "_reset_gen", 0):
            return
        self._set_busy(False, "search")
        self._clear_results()
        if err:
            self.status_lbl.configure(text=err, text_color=ERR)
            return
        self.status_lbl.configure(text=f'{len(results)} result(s) for "{q}"', text_color=TXT3)
        # Stagger card creation so the event loop stays responsive between widgets.
        for i, rec in enumerate(results):
            self.after(i * 60, lambda r=rec: self._result_card(r))

    def _result_card(self, rec):
        card = ctk.CTkFrame(self.results_scroll, fg_color=CARD, corner_radius=10)
        card.pack(fill="x", pady=3, padx=2)

        # Subtle play button on the far left of the card
        play_btn = ctk.CTkButton(
            card,
            text="▶",
            width=34,
            height=34,
            corner_radius=17,
            fg_color="transparent",
            hover_color=BTN_BG,
            text_color=TXT3,
            font=("Arial", 13),
        )
        play_btn.configure(command=lambda rx=rec, b=play_btn: self._play_preview(rx, b))
        play_btn.pack(side="left", padx=(8, 2), pady=10)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=8)
        ctk.CTkLabel(info, text=rec["name"], text_color=TXT, font=("Arial", 12, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=rec["artist"], text_color=ACCENT2, font=("Arial", 10), anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=rec["album"], text_color=TXT3, font=("Arial", 9), anchor="w").pack(fill="x")

        r = ctk.CTkFrame(card, fg_color="transparent")
        r.pack(side="right", padx=10, pady=8)
        ctk.CTkButton(
            r,
            text="Select",
            width=68,
            height=28,
            corner_radius=14,
            fg_color=ACCENT_G,
            hover_color="#179140",
            text_color="#04120a",
            font=("Arial", 10, "bold"),
            command=lambda rx=rec: self._select(rx),
        ).pack(anchor="e")

    # ------ preview playback ------
    def _play_preview(self, rec, btn):
        cur_id = getattr(self, "_preview_playing_id", None)
        if cur_id is not None and cur_id == rec.get("track_id"):
            self._stop_preview()
            return
        self._stop_preview()
        self._preview_playing_id = rec["track_id"]
        self._preview_playing_btn = btn
        self._preview_session = getattr(self, "_preview_session", 0) + 1
        session = self._preview_session
        self._anim_start("preview", btn, "", TXT3)  # animated dots while loading
        threading.Thread(
            target=self._do_play_preview, args=(rec, session), daemon=True
        ).start()

    def _stop_preview(self):
        self._anim_cancel("preview")
        self._preview_session = getattr(self, "_preview_session", 0) + 1
        proc = getattr(self, "_preview_proc", None)
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            self._preview_proc = None
        btn = getattr(self, "_preview_playing_btn", None)
        if btn is not None:
            try:
                btn.configure(text="▶", text_color=TXT3, fg_color="transparent",
                               hover_color=BTN_BG)
            except Exception:
                pass
            self._preview_playing_btn = None
        self._preview_playing_id = None

    def _do_play_preview(self, rec, session):
        tmp_path = None
        try:
            url = rec.get("preview_url")
            if not url or session != getattr(self, "_preview_session", -1):
                self.after(0, lambda: self._on_preview_not_found(session))
                return
            resp = requests.get(url, timeout=20, verify=False)
            resp.raise_for_status()
            if session != getattr(self, "_preview_session", -1):
                return
            suffix = ".m4a" if ".m4a" in url else ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(resp.content)
                tmp_path = f.name

            if sys.platform == "win32":
                uri = tmp_path.replace("\\", "/")
                ps = (
                    "Add-Type -AssemblyName PresentationCore;"
                    "$mp=[System.Windows.Media.MediaPlayer]::new();"
                    f"$mp.Open([uri]'file:///{uri}');"
                    "$mp.Play();"
                    "Start-Sleep -m 800;"
                    "while(-not $mp.NaturalDuration.HasTimeSpan){Start-Sleep -m 100};"
                    "$s=[int]$mp.NaturalDuration.TimeSpan.TotalSeconds+1;"
                    "Start-Sleep -s $s;"
                    "$mp.Stop();$mp.Close()"
                )
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                proc = subprocess.Popen(
                    ["afplay", tmp_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

            if session != getattr(self, "_preview_session", -1):
                proc.terminate()
            else:
                self._preview_proc = proc
                self.after(0, lambda s=session: self._on_preview_started(s))
                proc.wait()
        except Exception:
            pass
        finally:
            if tmp_path:
                try:
                    import time; time.sleep(0.3)  # Windows needs a moment to release the file
                    os.unlink(tmp_path)
                except Exception:
                    pass
        if session == getattr(self, "_preview_session", -1):
            self.after(0, self._on_preview_done)

    def _on_preview_started(self, session):
        if session != getattr(self, "_preview_session", -1):
            return
        self._anim_cancel("preview")
        btn = getattr(self, "_preview_playing_btn", None)
        if btn:
            try:
                btn.configure(text="■", text_color=ERR, fg_color="transparent",
                               hover_color=BTN_BG)
            except Exception:
                pass

    def _on_preview_not_found(self, session):
        if session != getattr(self, "_preview_session", -1):
            return
        self._anim_cancel("preview")
        self._preview_proc = None
        btn = getattr(self, "_preview_playing_btn", None)
        if btn:
            try:
                btn.configure(text="▶", text_color=TXT3, fg_color="transparent",
                               hover_color=BTN_BG)
            except Exception:
                pass
            self._preview_playing_btn = None
        self._preview_playing_id = None

    def _on_preview_done(self):
        self._anim_cancel("preview")
        self._preview_proc = None
        btn = getattr(self, "_preview_playing_btn", None)
        if btn:
            try:
                btn.configure(text="▶", text_color=TXT3, fg_color="transparent",
                               hover_color=BTN_BG)
            except Exception:
                pass
            self._preview_playing_btn = None
        self._preview_playing_id = None

    def _select(self, rec):
        self._sel_id = getattr(self, "_sel_id", 0) + 1
        sel_id = self._sel_id
        self.song_lbl.configure(text=f"{rec['name']} — {rec['artist']}")
        self.bpm_lbl.configure(text="--.-", text_color=TXT3)
        self._anim_start("scan", self.scan_status, "Looking for BPM & key", TXT3)
        self.chroma.clear()
        rg = getattr(self, "_reset_gen", 0)
        threading.Thread(target=self._fetch_song_data, args=(rec, sel_id, rg), daemon=True).start()

    def _fetch_song_data(self, rec, sel_id, reset_gen):
        def safe_anim(base, color):
            if getattr(self, "_reset_gen", -1) == reset_gen:
                self._anim_start("scan", self.scan_status, base, color)
        try:
            self.after(0, lambda: safe_anim("Analyzing preview", ACCENT2))
            preview_url = rec.get("preview_url")
            bpm, key, mode, err = (None, None, None, None)
            if preview_url:
                bpm, key, mode, err = analyze_preview_url(preview_url)
            self.after(0, lambda: self._handle_song_data(rec, bpm, key, mode, err, sel_id))
        except Exception as e:
            self.after(0, lambda: self._handle_song_data(rec, None, None, None, f"Background error: {e}", sel_id))

    def _handle_song_data(self, rec, bpm, key, mode, err, sel_id=None):
        if sel_id is not None and sel_id != getattr(self, "_sel_id", None):
            return
        self._anim_cancel("scan")
        self.song_lbl.configure(text=f"{rec['name']} — {rec['artist']}")

        if err:
            self.bpm_lbl.configure(text="--.-", text_color=ACCENT)
            self.camelot_lbl.configure(text="—", text_color=TXT3)
            self.scan_status.configure(text="No data found. Try uploading an audio file.", text_color=ERR)
            return

        if bpm is None or key is None:
            self.bpm_lbl.configure(text="--.-", text_color=ACCENT)
            self.camelot_lbl.configure(text="—", text_color=TXT3)
            self.scan_status.configure(text="No data found. Try uploading an audio file.", text_color=ERR)
            return

        self.bpm_lbl.configure(text=f"{bpm:.1f}", text_color=ACCENT)
        self.camelot_lbl.configure(text=camelot_label(key, mode), text_color=ACCENT2)
        self.scan_status.configure(text="")
        self.chroma.set(key, mode)
        self._set_ref(bpm, key, mode,
                      rec.get("genre", ""), rec.get("artist", ""),
                      rec.get("track_id", ""))

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Choose audio file",
            filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg *.aif *.aiff"), ("All", "*.*")],
        )
        self.focus_force()
        if not path:
            return

        self.file_lbl.configure(text=os.path.basename(path))
        self.bpm_lbl.configure(text="--.-", text_color=TXT3)
        self.camelot_lbl.configure(text="—", text_color=TXT3)
        self._anim_start("scan", self.scan_status, "Analyzing", ACCENT2)
        self.song_lbl.configure(text=os.path.basename(path))
        self.chroma.clear()
        self._set_busy(True, "upload")
        rg = getattr(self, "_reset_gen", 0)
        threading.Thread(target=self._do_analyze, args=(path, rg), daemon=True).start()

    def _do_analyze(self, path, reset_gen):
        try:
            res = analyze_file(path)
        except Exception:
            res = {"bpm": None, "key": None, "mode": None, "confidence": 0.0, "chroma": np.zeros(12)}
        self.after(0, lambda: self._show_analysis(path, res, reset_gen))

    def _show_analysis(self, path, res, reset_gen=None):
        if reset_gen is not None and reset_gen != getattr(self, "_reset_gen", 0):
            return
        self._anim_cancel("scan")
        self._set_busy(False, "upload")
        if res["bpm"] is None:
            self.bpm_lbl.configure(text="ERR", text_color=ERR)
        else:
            self.bpm_lbl.configure(text=f"{res['bpm']:.1f}", text_color=ACCENT)

        if res["key"] is None:
            self.camelot_lbl.configure(text="—", text_color=TXT3)
            self.scan_status.configure(text="Could not detect key.", text_color=ERR)
            self.chroma.clear()
        else:
            self.camelot_lbl.configure(text=camelot_label(res["key"], res["mode"]),
                                        text_color=ACCENT2)
            conf = int(res["confidence"] * 100)
            self.scan_status.configure(text=f"Key confidence: {conf}%", text_color=ACCENT2)
            self.chroma.set(res["key"], res["mode"])
            self._set_ref(res["bpm"], res["key"], res["mode"], "", "", "")

        self.song_lbl.configure(text=os.path.basename(path))

    # ── MIX MATCHES ─────────────────────────────────────────

    def _set_ref(self, bpm, key, mode, genre, artist, track_id):
        self._ref_bpm      = bpm
        self._ref_key      = key
        self._ref_mode     = mode
        self._ref_artist   = artist
        self._ref_track_id = track_id
        # Auto-detect style from iTunes genre + BPM + artist (used internally for search)
        self._detected_genre = _detect_style(genre, bpm, artist)
        lbl = camelot_label(key, mode)
        self._mix_status.configure(
            text=f"Reference: {bpm:.1f} BPM  •  {key} {'Major' if mode == 'maj' else 'Minor'}  •  Camelot {lbl}",
            text_color=ACCENT2,
        )

    def _find_matches(self):
        if self._ref_bpm is None:
            self._mix_status.configure(
                text="Select or analyze a song first.", text_color=ERR)
            return
        genre_opt = self._detected_genre
        bpm_tol   = int(self._bpm_tol_slider.get())
        key_opt   = self._key_compat_var.get()
        max_steps = {"Same key": 0, "±1 step": 1, "±2 steps": 2}.get(key_opt, 1)

        self._match_gen = getattr(self, "_match_gen", 0) + 1
        mg = self._match_gen
        for w in list(self._mix_scroll.winfo_children()):
            w.destroy()
        self._anim_start("mix", self._mix_status, "Searching for similar songs", TXT2)
        self._mix_note.configure(
            text="This may take a minute or two — each candidate preview is downloaded and analyzed."
        )
        threading.Thread(
            target=self._do_find_matches,
            args=(genre_opt, self._ref_bpm, self._ref_key, self._ref_mode,
                  bpm_tol, max_steps, mg),
            daemon=True,
        ).start()

    def _do_find_matches(self, genre_opt, bpm, key, mode, bpm_tol, max_steps, mg):
        ref_artist = getattr(self, "_ref_artist", "")
        ref_id     = getattr(self, "_ref_track_id", "")

        # ── iTunes search ──
        if genre_opt and genre_opt in _STYLE_QUERIES:
            queries = list(_STYLE_QUERIES[genre_opt])
        else:
            queries = []
        if ref_artist:
            queries.append(ref_artist)
        if not queries:
            queries = ["deadmau5", "Eric Prydz", "Armin van Buuren", "FISHER", "Adam Beyer"]

        candidates = itunes_mix_search(queries, limit_per=20)
        candidates = [r for r in candidates if r["track_id"] != ref_id]

        if not candidates:
            self.after(0, lambda: self._anim_cancel("mix"))
            self.after(0, lambda: self._mix_status.configure(
                text="No candidates found. Check your internet connection.", text_color=ERR))
            return

        found = 0

        def analyze_one(rec):
            if getattr(self, "_match_gen", -1) != mg:
                return None
            b, k, m, _ = analyze_preview_url(rec["preview_url"])
            if b is None or k is None:
                return None
            # BPM detection on short previews often returns half or double the
            # true tempo.  Check all three multiples and use the closest match.
            b_adj = min((b, b * 2.0, b * 0.5), key=lambda x: abs(x - bpm))
            if abs(b_adj - bpm) > bpm_tol:
                return None
            if key and mode and not camelot_compatible(key, mode, k, m, max_steps):
                return None
            return {**rec, "match_bpm": round(b_adj, 1), "match_key": k, "match_mode": m}

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(analyze_one, r) for r in candidates]
            for fut in as_completed(futures):
                if getattr(self, "_match_gen", -1) != mg:
                    break
                res = fut.result()
                if res:
                    self.after(found * 80, lambda r=res, g=mg: self._add_match_card(r, g))
                    found += 1

        self.after(found * 80 + 50, lambda n=found, g=mg: self._on_matches_done(n, g))

    def _add_match_card(self, rec, mg):
        if getattr(self, "_match_gen", -1) != mg:
            return
        b   = rec["match_bpm"]
        k   = rec["match_key"]
        m   = rec["match_mode"]
        clbl = camelot_label(k, m)
        mode_str = "Major" if m == "maj" else "Minor"

        card = ctk.CTkFrame(self._mix_scroll, fg_color=CARD, corner_radius=10)
        card.pack(fill="x", pady=3, padx=2)

        play_btn = ctk.CTkButton(
            card, text="▶", width=32, height=32, corner_radius=16,
            fg_color="transparent", hover_color=BTN_BG,
            text_color=TXT3, font=("Arial", 12),
        )
        play_btn.configure(command=lambda rx=rec, b=play_btn: self._play_preview(rx, b))
        play_btn.pack(side="left", padx=(8, 2), pady=8)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=6)
        ctk.CTkLabel(info, text=rec["name"], text_color=TXT,
                     font=("Arial", 12, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=rec["artist"], text_color=ACCENT2,
                     font=("Arial", 10), anchor="w").pack(fill="x")

        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.pack(side="right", padx=12, pady=8)
        ctk.CTkLabel(meta, text=f"{b:.1f} BPM", text_color=ACCENT,
                     font=("Arial", 12, "bold")).pack(anchor="e")
        ctk.CTkLabel(meta, text=f"{k} {mode_str}  •  {clbl}",
                     text_color=TXT2, font=("Arial", 10)).pack(anchor="e")
        ctk.CTkButton(
            meta, text="Select", width=60, height=24, corner_radius=12,
            fg_color=ACCENT_G, hover_color="#179140", text_color="#04120a",
            font=("Arial", 10, "bold"),
            command=lambda rx=rec: self._select(rx),
        ).pack(anchor="e", pady=(4, 0))

    def _on_matches_done(self, found, mg):
        if getattr(self, "_match_gen", -1) != mg:
            return
        self._anim_cancel("mix")
        self._mix_note.configure(text="")
        if found == 0:
            self._mix_status.configure(
                text="No matches found. Try widening BPM tolerance or key range.",
                text_color=ERR)
        else:
            self._mix_status.configure(
                text=f"{found} match{'es' if found != 1 else ''} found.",
                text_color=ACCENT2)


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()