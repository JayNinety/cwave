#!/usr/bin/env python3
"""
CWave is licensed under the GNU General Public License
version 3 or (at your option) any later version.

CWave Terminal Music Player
  mpv        -> playback
  cava       -> audio visualizer
  chafa      -> album/track cover: sixel / kitty / iTerm image, or Unicode symbols
"""

import os
import re
import sys
import math
import json
import time
import codecs
import hashlib
import random
import fcntl
import struct
import signal
import shutil
import tempfile
import subprocess
import threading
import queue
import select
import termios
import tty
import configparser
import unicodedata
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace

try:
    import mpv
    from mutagen import File as MutagenFile
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from PIL import Image, ImageOps
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# --------------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------------- #

CONFIG_DIR  = Path.home() / ".config" / "cwave"
CONFIG_FILE = CONFIG_DIR / "config"
HISTORY_FILE = CONFIG_DIR / "history.json"
PLAYLISTS_DIR = CONFIG_DIR / "playlists"                       # saved stream playlists (*.json)
THUMB_DIR = Path.home() / ".cache" / "cwave" / "thumbs"  # downloaded thumbnails
STREAM_CACHE_FILE = Path.home() / ".cache" / "cwave" / "stream_urls.json"
LYRICS_DIR = Path.home() / ".cache" / "cwave" / "lyrics"  # cached timed lyrics (JSON)
CONFIG_VERSION = 16

DEFAULT_CONFIG = """
[general]
config_version = 16

[directories]
paths = ~/Music

[playback]
# autoplay  : play the next track of the same folder / playlist when one ends
autoplay = true
# shuffle   : pick a random track of the same folder / playlist instead of sequential
shuffle  = false
# loop      : after the last track of a folder/playlist, restart from the first.
#             Off by default — the player stops when the list ends. Toggle with R.
loop     = false
# resume    : seek to the last position when re-opening a track (history is always kept)
resume   = false
# songs played at least this many times get a symlink in the Most Played folder
most_played_threshold = 5
# folder name created under the first music directory (e.g. ~/Music/Most Played)
most_played_name = Most Played

[keybinds]
# single character; case-insensitive. Change to any letter you prefer.
shuffle = s
# key that opens the "add playlist" box (paste a YouTube / YouTube Music playlist URL)
add_playlist = y
# key that toggles folder/playlist loop (restart after last track)
loop = r

[streaming]
# Name of the virtual folder shown first in your music directory. It holds the playlists
# you add with the add_playlist key; they are saved as JSON files in
# ~/.config/cwave/playlists/ and streamed with mpv + yt-dlp.
playlists_name = Stream Playlists
# Single videos/tracks you add (a plain video URL instead of a playlist URL) are collected
# in one playlist with this name, inside the folder above.
single_tracks_name = Saved Tracks
# Streamed covers are 16:9 thumbnails. true = crop them to a centered square (1:1).
square_covers = true
# How many upcoming tracks (from the current playlist / folder) to pre-resolve with yt-dlp.
# Pre-resolved direct stream URLs load almost instantly instead of the usual ~5 s delay.
preload_count = 4
# How long a resolved direct URL stays valid (seconds). YouTube links expire; 30–60 min is safe.
preload_ttl = 2700
# Persist the resolved URL cache to disk so it survives restarts (within the TTL).
preload_disk_cache = true

[lyrics]
# Fetch timed lyrics from LiriQo (free multi-provider API, no key) for local
# files and streams. Prefers word/syllable timing when available; falls back
# to line-synced or plain. Synced lines are highlighted in real time.
enable = true
# Key that toggles the right panel between the file list and lyrics (case-insensitive).
# Visualizer always stays on the left.
toggle = l
# Convert Japanese lyrics to romaji (requires: pip install pykakasi). Off by default.
romaji = false
# Highlight granularity: syllable | word | line | off
# Default is word. Falls down the ladder when the preferred level is missing
# for a track (syllable → word → line → plain). "off" shows static text only.
sync = word
# Max lyric line width in terminal cells. 0 = use the full panel width
# (auto-wrap). Set a positive number only if you want a fixed cap.
max_width = 0
# Ctrl+C while the lyrics panel is open copies the current lyrics to the clipboard
# (wl-copy / xclip / xsel). true = include [mm:ss] timestamps; false = plain text.
copy_timestamps = false
# Allow a full-screen lyrics mode that hides cover, visualizer and file list.
# On by default. When true, the fullscreen_key enters/exits that mode.
fullscreen = true
# Key for full-screen lyrics (only works when fullscreen = true).
fullscreen_key = f

[style]
# Colors accept #rrggbb or a 256-color number (0-255)
title_color        = #ffffff
subtitle_color     = #cfcfcf
path_color         = #61a0ff
back_color         = #ffffff
file_color         = #d9d4ff
# color of the player's own folders (Stream Playlists, Most Played) in the file list
special_color      = #ffb86c
selected_bg        = #ffffff
selected_fg        = #000000
playing_color      = #7ed957
progress_color     = #d9d4ff
help_color         = #d9d4ff
viz_color          = #b6b6b6
cover_border_color = #d9d4ff

enable_cover       = true
cover_border       = 2
# How covers are drawn (needs chafa):
#   auto    = best image format the terminal supports, otherwise Unicode symbols
#   sixel | kitty | iterm = force that image format
#   symbols = Unicode characters (works everywhere, but blocky)
#   off     = no covers
cover_renderer     = auto
# Only for "symbols": chafa symbol set, e.g. braille, half, vhalf, block+border
# (empty = chafa's default mix)
cover_symbols      =

# Font sizes are relative weights used for bold emphasis.
# Terminal cells are fixed size; "large" applies bold, "normal" does not.
title_size         = large
subtitle_size      = normal
path_size          = normal
file_size          = normal
progress_size      = normal
help_size          = normal

# Track header shown on the player (left column, above the cover).
# Placeholders: {title} {artist} {album} {year} {genre} {container}
#               {channels} {bitrate} {samplerate} {duration} {path}
# Use \\n for a new line. Empty lines are kept.
# Default matches the previous hard-coded layout.
track_display = {title}\\n{year} - {artist}\\n[{album}]

# viz_bars   : number of bars, 0 = fill the available width
# viz_height : height in rows, 0 = use all the free vertical space
# Decimal values are fine, they get rounded.
viz_bars           = 0
viz_height         = 0
viz_bar_width      = 1
viz_gap            = 1
viz_mode           = bars
viz_fps            = 60
seek_seconds       = 5
"""

DEFAULT_COLORS = {
    "title_color": "#ffffff", "subtitle_color": "#cfcfcf", "path_color": "#61a0ff",
    "back_color": "#ffffff", "file_color": "#d9d4ff", "special_color": "#ffb86c",
    "selected_bg": "#ffffff",
    "selected_fg": "#000000", "playing_color": "#7ed957", "progress_color": "#d9d4ff",
    "help_color": "#d9d4ff", "viz_color": "#b6b6b6", "cover_border_color": "#d9d4ff",
}

# values carried over from an older config when it gets upgraded
KEEP_ON_MIGRATE = (
    "paths", "enable_cover", "viz_mode", "viz_fps", "seek_seconds",
    "track_display", "title_size", "subtitle_size",
    "autoplay", "shuffle", "resume", "most_played_threshold", "most_played_name",
)


def _read_cfg(text=None):
    cfg = configparser.ConfigParser(interpolation=None)
    try:
        if text is None:
            cfg.read(CONFIG_FILE)
        else:
            cfg.read_string(text)
    except configparser.Error:
        cfg = configparser.ConfigParser(interpolation=None)
    return cfg


def _set_option(text, sect, key, value):
    """Set `key = value` inside [sect] only (the same key can exist in several sections)."""
    m = re.search(rf"^\[{re.escape(sect)}\][ \t]*$", text, flags=re.M)
    if not m:
        return text
    start = m.end()
    nxt = re.search(r"^\[", text[start:], flags=re.M)
    end = start + nxt.start() if nxt else len(text)
    body, n = re.subn(rf"^{re.escape(key)}\s*=.*$", lambda _m: f"{key} = {value}",
                      text[start:end], count=1, flags=re.M)
    return text[:start] + body + text[end:] if n else text


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    exists = CONFIG_FILE.exists()
    cfg = _read_cfg() if exists else configparser.ConfigParser(interpolation=None)

    try:
        version = int(cfg.get("general", "config_version", fallback="1"))
    except ValueError:
        version = 1

    if exists and version >= CONFIG_VERSION:
        return cfg

    # First run, or config from an older layout: write the new defaults.
    # The old file is kept as config.bak. Configs from v4 on keep every value (only new
    # options are added); older layouts only carry over the non-visual settings.
    text = DEFAULT_CONFIG.strip() + "\n"
    if exists:
        try:
            shutil.copy(CONFIG_FILE, CONFIG_FILE.with_name("config.bak"))
        except Exception:
            pass
        carry = None if version >= 4 else KEEP_ON_MIGRATE
        for sect in cfg.sections():
            for key, val in cfg.items(sect):
                if key == "config_version" or (carry is not None and key not in carry):
                    continue
                text = _set_option(text, sect, key, val)
    CONFIG_FILE.write_text(text)
    return _read_cfg(text)


def expand(p):
    return Path(os.path.expanduser(p)).resolve()


def num(section, key, default, lo, hi):
    """Read a number from config. Accepts '7', '7.5', ' 7 ' ... rounds and clamps."""
    try:
        v = float(str(section.get(key, default)).strip())
        if math.isnan(v) or math.isinf(v):
            return default
    except (ValueError, TypeError):
        return default
    return int(max(lo, min(hi, round(v))))


def parse_bool(value, default):
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def parse_size(value, default="normal"):
    """Return True if the size should be rendered bold (large)."""
    if value is None:
        value = default
    v = str(value).strip().lower()
    if v in ("large", "big", "2", "bold", "l"):
        return True
    if v in ("normal", "small", "1", "regular", "n", "s"):
        return False
    return str(default).strip().lower() in ("large", "big", "2", "bold", "l")


# --------------------------------------------------------------------------- #
#  Terminal helpers
# --------------------------------------------------------------------------- #

ALT_ENTER = "\033[?1049h"
ALT_EXIT  = "\033[?1049l"
HIDE_CUR  = "\033[?25l"
SHOW_CUR  = "\033[?25h"
CLEAR     = "\033[2J\033[H"
RESET     = "\033[0m"
SYNC_ON   = "\033[?2026h"     # synchronized output (ignored by terminals without it)
SYNC_OFF  = "\033[?2026l"

UP_ICON = "\u2b06\ufe0e"      # ⬆ forced to text presentation
BLOCKS  = "▁▂▃▄▅▆▇█"


def parse_color(value, default):
    v = str(value).strip() if value is not None else ""
    if v.startswith("#") and len(v) == 7:
        try:
            return ("t", int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
        except ValueError:
            pass
    else:
        try:
            return ("p", max(0, min(255, int(float(v)))))
        except ValueError:
            pass
    return default if isinstance(default, tuple) else parse_color(default, ("p", 255))


def _sgr(spec, layer):
    if spec[0] == "t":
        return f"{layer};2;{spec[1]};{spec[2]};{spec[3]}"
    return f"{layer};5;{spec[1]}"


def style(fg=None, bg=None, bold=False):
    parts = ["0"]
    if bold:
        parts.append("1")
    if fg:
        parts.append(_sgr(fg, 38))
    if bg:
        parts.append(_sgr(bg, 48))
    return "\033[" + ";".join(parts) + "m"


def spec_rgb(spec):
    if spec[0] == "t":
        return spec[1:4]
    n = spec[1]
    base16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
              (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
              (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
    if n < 16:
        return base16[n]
    if n < 232:
        n -= 16
        lv = [0, 95, 135, 175, 215, 255]
        return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    v = 8 + (n - 232) * 10
    return (v, v, v)


def at(row, col, text):
    return f"\033[{row};{col}H{text}"


def term_size():
    return shutil.get_terminal_size((120, 36))


def cell_px():
    """Pixel size of one terminal cell (falls back to 10x20)."""
    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        r, c, xp, yp = struct.unpack("HHHH", buf)
        if r and c and xp and yp:
            return xp / c, yp / r
    except Exception:
        pass
    return 10.0, 20.0


def cw(s):
    """Display width of a string in terminal cells."""
    n = 0
    for ch in s:
        if unicodedata.combining(ch) or ch in "\u200b\ufe0e\ufe0f":
            continue
        n += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return n


def fit(s, w):
    if w <= 0:
        return ""
    if cw(s) <= w:
        return s
    out, cur = "", 0
    for ch in s:
        c = cw(ch)
        if cur + c > w - 1:
            break
        out += ch
        cur += c
    return out + "…"


def fit_left(s, w):
    """Truncate from the left (good for paths)."""
    if cw(s) <= w:
        return s
    out, cur = "", 0
    for ch in reversed(s):
        c = cw(ch)
        if cur + c > w - 1:
            break
        out = ch + out
        cur += c
    return "…" + out


def wrap_hyphen(s, w):
    """Wrap plain text to width w using hyphen continuations (no ellipsis).

    Example at w=8: "I love you." → ["I love y-", "ou."]
    Soft-wraps on spaces when possible; otherwise hyphenates mid-word.
    """
    if w <= 0:
        return [""]
    s = s or ""
    if not s:
        return [""]
    if w == 1:
        return [ch for ch in s] or [""]

    rows = []
    i = 0
    n = len(s)
    while i < n:
        # Skip leading spaces on new rows (except the very first)
        if rows and s[i].isspace():
            i += 1
            continue

        # Try to fit as much as possible
        width = 0
        j = i
        last_space = -1  # index in s of last space that fits
        while j < n:
            ch = s[j]
            c = cw(ch)
            if width + c > w:
                break
            if ch.isspace():
                last_space = j
            width += c
            j += 1

        if j >= n:
            # Rest of string fits
            rows.append(s[i:].rstrip())
            break

        if last_space > i:
            # Soft-wrap at the last space
            rows.append(s[i:last_space].rstrip())
            i = last_space + 1
            continue

        # No space in the window: hard-wrap with hyphen
        # Leave room for '-' when possible
        limit = w - 1 if w >= 2 else w
        width = 0
        j = i
        while j < n:
            c = cw(s[j])
            if width + c > limit:
                break
            width += c
            j += 1
        if j == i:
            # Single character wider than limit — emit it alone
            rows.append(s[i])
            i += 1
        else:
            rows.append(s[i:j] + ("-" if j < n else ""))
            i = j
    return [r for r in rows if r is not None] or [""]


def _skip_ansi(text: str, i: int) -> int:
    """Return index just past an ANSI escape at text[i], or i+1 on failure."""
    n = len(text)
    if i >= n or text[i] != "\033":
        return i
    j = i + 1
    if j >= n:
        return j
    # CSI: ESC [ ... final-byte. '[' is itself in the @-~ range, so consume it first.
    if text[j] == "[":
        j += 1
        while j < n and not ("@" <= text[j] <= "~"):
            j += 1
        if j < n:
            j += 1
        return j
    # OSC: ESC ] ... BEL or ST (ESC \)
    if text[j] == "]":
        j += 1
        while j < n:
            if text[j] == "\a":
                return j + 1
            if text[j] == "\033" and j + 1 < n and text[j + 1] == "\\":
                return j + 2
            j += 1
        return j
    # Two-char escape (ESC X)
    return j + 1


def pad_to_width(text, w):
    """Pad or hard-clip a (possibly styled) string so its *visible* width is w.

    ANSI SGR sequences are preserved; only printable width is measured.
    Always ends with RESET so styles never leak into the next cell/row.
    """
    if w <= 0:
        return ""
    visible = 0
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\033":
            j = _skip_ansi(text, i)
            out.append(text[i:j])
            i = j
            continue
        ch = text[i]
        c = cw(ch)
        if visible + c > w:
            break
        out.append(ch)
        visible += c
        i += 1
    if visible < w:
        out.append(" " * (w - visible))
    out.append(RESET)
    return "".join(out)

def _style_wrap(segments: list[tuple[str, str]], w: int) -> list[str]:
    """Wrap a list of (plain_text, sgr_prefix) segments into rows of width w.

    Soft-wraps on spaces when possible; otherwise hyphenates. Each output row
    is padded to exactly w cells and terminated with RESET.
    """
    if w <= 0:
        return [""]

    # Flatten to a list of (char, sgr) so we can reflow freely
    chars: list[tuple[str, str]] = []
    for text, sgr in segments:
        for ch in text:
            chars.append((ch, sgr))

    if not chars:
        return [pad_to_width("", w)]

    rows: list[str] = []
    i = 0
    n = len(chars)
    while i < n:
        # Skip leading spaces on continuation rows
        if rows:
            while i < n and chars[i][0].isspace():
                i += 1
            if i >= n:
                break

        width = 0
        j = i
        last_space = -1
        while j < n:
            c = cw(chars[j][0])
            if width + c > w:
                break
            if chars[j][0].isspace():
                last_space = j
            width += c
            j += 1

        if j >= n:
            end = n
            hyphen = False
        elif last_space > i:
            end = last_space
            j = last_space + 1  # skip the space
            hyphen = False
        else:
            # Hard wrap: leave room for '-' when more remains
            limit = w - 1 if w >= 2 else w
            width = 0
            j = i
            while j < n:
                c = cw(chars[j][0])
                if width + c > limit:
                    break
                width += c
                j += 1
            if j == i:
                j = i + 1
            end = j
            hyphen = j < n

        # Emit [i:end] with style changes
        parts = []
        cur_sgr = None
        for k in range(i, end):
            ch, sgr = chars[k]
            if sgr != cur_sgr:
                parts.append(sgr)
                cur_sgr = sgr
            parts.append(ch)
        if hyphen:
            # Hyphen in the current style
            if cur_sgr is None:
                parts.append(style(("p", 255)))
            parts.append("-")
        rows.append(pad_to_width("".join(parts), w))
        i = j if j > i else end
        if i < end:
            i = end
    return rows or [pad_to_width("", w)]


def center(s, w):
    pad = max(0, w - cw(s))
    left = pad // 2
    return " " * left + s + " " * (pad - left)


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# --------------------------------------------------------------------------- #
#  Media helpers
# --------------------------------------------------------------------------- #

def is_audio(p: Path) -> bool:
    return p.suffix.lower() in {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}


CHANNEL_LABELS = {
    1: "Mono",
    2: "Stereo",
    3: "2.1",
    4: "Quad",
    5: "5.0",
    6: "5.1 Surround",
    7: "6.1 Surround",
    8: "7.1 Surround",
}


def _channel_label(n):
    if not n or n <= 0:
        return ""
    name = CHANNEL_LABELS.get(int(n))
    if name:
        return f"{n} [{name}]"
    if n > 8:
        return f"{n} [Surround]"
    return str(n)


def get_metadata(path: Path) -> dict:
    meta = {
        "title": path.stem,
        "artist": "Unknown",
        "album": "Unknown",
        "year": "",
        "genre": "",
        "duration": 0,
        "container": path.suffix.upper().lstrip(".") or "?",
        "channels": 0,
        "channels_label": "",
        "bitrate": 0,       # bits per second
        "samplerate": 0,    # Hz
        "bitrate_label": "",
        "samplerate_label": "",
    }
    try:
        audio = MutagenFile(path, easy=True)
        if not audio:
            return meta
        meta["title"]  = (audio.get("title")  or [path.stem])[0]
        meta["artist"] = (audio.get("artist") or ["Unknown"])[0]
        meta["album"]  = (audio.get("album")  or ["Unknown"])[0]
        y = audio.get("date") or audio.get("year") or [""]
        meta["year"] = str(y[0])[:4] if y else ""
        g = audio.get("genre") or [""]
        meta["genre"] = str(g[0]).strip() if g else ""

        info = getattr(audio, "info", None)
        if info:
            meta["duration"] = getattr(info, "length", 0) or 0
            br = getattr(info, "bitrate", 0) or 0
            # mutagen reports bitrate in bps for most formats
            if br and br < 1000:  # some formats give kbps already
                br *= 1000
            meta["bitrate"] = int(br) if br else 0
            meta["samplerate"] = int(getattr(info, "sample_rate", 0) or 0)
            ch = getattr(info, "channels", 0) or 0
            meta["channels"] = int(ch) if ch else 0
    except Exception:
        pass

    # Non-easy tags sometimes hold genre better (ID3 TCON etc.)
    if not meta["genre"]:
        try:
            audio = MutagenFile(path)
            if audio and getattr(audio, "tags", None):
                for key in ("TCON", "genre", "\xa9gen", "GENRE"):
                    if key in audio.tags:
                        val = audio.tags[key]
                        if hasattr(val, "text"):
                            meta["genre"] = str(val.text[0]) if val.text else ""
                        elif isinstance(val, (list, tuple)):
                            meta["genre"] = str(val[0])
                        else:
                            meta["genre"] = str(val)
                        break
        except Exception:
            pass

    meta["channels_label"] = _channel_label(meta["channels"])
    if meta["bitrate"]:
        kbps = meta["bitrate"] / 1000.0
        meta["bitrate_label"] = f"{kbps:.0f} kbps" if kbps >= 10 else f"{kbps:.1f} kbps"
    if meta["samplerate"]:
        sr = meta["samplerate"]
        if sr >= 1000:
            meta["samplerate_label"] = f"{sr / 1000:g} kHz"
        else:
            meta["samplerate_label"] = f"{sr} Hz"
    return meta


def _tag_year(value) -> str:
    """'20210804' / '2021-08-04' / '2021/08/04' / '2021' -> '2021' (we only want the year)."""
    m = re.match(r"\s*(\d{4})", str(value or ""))
    return m.group(1) if m and 1000 <= int(m.group(1)) <= 2999 else ""


def enrich_from_mpv(mpv_player, meta: dict) -> dict:
    """Fill / refine fields using live mpv properties when available."""
    try:
        # Genre from metadata dict if mutagen missed it
        md = getattr(mpv_player, "metadata", None) or {}
        if isinstance(md, dict):
            md = {str(k).lower(): v for k, v in md.items()}      # tag-name case differs per format
            if not meta.get("year"):
                for key in ("date", "year", "originaldate", "originalyear", "release_date", "releasedate"):
                    y = _tag_year(md.get(key))
                    if y:
                        meta["year"] = y
                        break
            if not meta.get("genre") and md.get("genre"):
                meta["genre"] = str(md["genre"])
            if not meta.get("title") or meta["title"] == "Unknown":
                if md.get("title"):
                    meta["title"] = str(md["title"])
            if not meta.get("artist") or meta["artist"] == "Unknown":
                if md.get("artist"):
                    meta["artist"] = str(md["artist"])
            if not meta.get("album") or meta["album"] == "Unknown":
                if md.get("album"):
                    meta["album"] = str(md["album"])

        # Channels: prefer layout string from mpv when present
        ch_layout = None
        try:
            ch_layout = mpv_player.audio_channels  # often a layout string
        except Exception:
            pass
        try:
            nch = mpv_player._get_property("audio-params/channel-count")
            if nch:
                meta["channels"] = int(nch)
        except Exception:
            pass
        if ch_layout and isinstance(ch_layout, str) and ch_layout.strip():
            # mpv may return "stereo", "5.1", "7.1(side)", etc.
            layout = ch_layout.strip()
            n = meta.get("channels") or 0
            if n:
                meta["channels_label"] = f"{n} [{layout}]"
            else:
                meta["channels_label"] = layout
        elif meta.get("channels"):
            meta["channels_label"] = _channel_label(meta["channels"])

        # Bitrate (mpv reports approximate bps)
        try:
            br = mpv_player.audio_bitrate
            if br and br > 0:
                meta["bitrate"] = int(br)
                kbps = br / 1000.0
                meta["bitrate_label"] = f"{kbps:.0f} kbps" if kbps >= 10 else f"{kbps:.1f} kbps"
        except Exception:
            pass
        try:
            # demux bitrate is often more stable for the stream
            br = mpv_player._get_property("current-tracks/audio/demux-bitrate")
            if br and br > 0:
                meta["bitrate"] = int(br)
                kbps = br / 1000.0
                meta["bitrate_label"] = f"{kbps:.0f} kbps" if kbps >= 10 else f"{kbps:.1f} kbps"
        except Exception:
            pass

        # Sample rate
        try:
            sr = mpv_player.audio_samplerate
            if sr and sr > 0:
                meta["samplerate"] = int(sr)
                if sr >= 1000:
                    meta["samplerate_label"] = f"{sr / 1000:g} kHz"
                else:
                    meta["samplerate_label"] = f"{sr} Hz"
        except Exception:
            pass
        try:
            sr = mpv_player._get_property("audio-params/samplerate")
            if sr and sr > 0:
                meta["samplerate"] = int(sr)
                if sr >= 1000:
                    meta["samplerate_label"] = f"{sr / 1000:g} kHz"
                else:
                    meta["samplerate_label"] = f"{sr} Hz"
        except Exception:
            pass
    except Exception:
        pass
    return meta


def find_external_cover(path: Path):
    stem = path.with_suffix("")
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = Path(str(stem) + ext)
        if candidate.is_file():
            try:
                return Image.open(candidate).convert("RGB")
            except Exception:
                pass
    return None


def _image_from_bytes(data) -> Image.Image | None:
    """Open image bytes as RGB PIL Image, or None on failure."""
    if not data:
        return None
    try:
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None


def extract_cover(path: Path):
    """External sidecar first, then embedded art (ID3 APIC, FLAC/Ogg pictures, MP4 covr)."""
    img = find_external_cover(path)
    if img:
        return img

    # --- mutagen (most containers) ---
    try:
        audio = MutagenFile(path)
        if audio is not None:
            # FLAC / Ogg / Opus: pictures list on the file object
            pictures = getattr(audio, "pictures", None) or []
            if pictures:
                img = _image_from_bytes(getattr(pictures[0], "data", None))
                if img:
                    return img

            tags = getattr(audio, "tags", None)
            if tags is not None:
                # MP4 / M4A covr
                try:
                    covr = tags.get("covr") if hasattr(tags, "get") else None
                    if covr is None and "covr" in tags:
                        covr = tags["covr"]
                    if covr:
                        data = covr[0]
                        img = _image_from_bytes(getattr(data, "data", data))
                        if img:
                            return img
                except Exception:
                    pass

                # ID3 APIC (MP3 and others that carry ID3)
                apics = []
                try:
                    apics = tags.getall("APIC")
                except Exception:
                    pass
                if not apics:
                    try:
                        for k in list(tags.keys()):
                            if str(k).startswith("APIC"):
                                apics.append(tags[k])
                    except Exception:
                        pass
                for frame in apics:
                    img = _image_from_bytes(getattr(frame, "data", None))
                    if img:
                        return img
    except Exception:
        pass

    # --- direct ID3 fallback (some MP3s mutagen File() mishandles) ---
    try:
        from mutagen.id3 import ID3
        id3 = ID3(path)
        for frame in id3.getall("APIC"):
            img = _image_from_bytes(getattr(frame, "data", None))
            if img:
                return img
    except Exception:
        pass

    # --- MP4 direct fallback ---
    try:
        mp4 = MP4(path)
        if "covr" in mp4:
            img = _image_from_bytes(mp4["covr"][0])
            if img:
                return img
    except Exception:
        pass

    # --- FLAC direct fallback ---
    try:
        flac = FLAC(path)
        if flac.pictures:
            img = _image_from_bytes(flac.pictures[0].data)
            if img:
                return img
    except Exception:
        pass

    return None


COVER_RENDERERS = ("auto", "sixel", "kitty", "iterm", "symbols", "off")
_CHAFA_FORMAT = {"sixel": "sixels", "kitty": "kitty", "iterm": "iterm", "symbols": "symbols"}
_chafa_attempt = {}       # format -> index of the argument set that worked (older chafa lacks some options)


def chafa_path():
    return shutil.which("chafa")


def detect_cover_format() -> str:
    """Which image format does this terminal support: "sixel", "kitty" or "iterm"?
    "symbols" (Unicode characters) when it supports none. Run once, before the UI starts,
    because chafa briefly talks to the terminal to find out."""
    exe = chafa_path()
    if not exe:
        return "symbols"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        Image.new("RGB", (8, 8), (128, 128, 128)).save(f.name, "PNG")
        tmp = f.name
    try:
        # chafa's output is captured here, so let it probe the controlling tty (newer versions);
        # older versions fall back to guessing from the environment
        for extra in (["--probe", "1", "--probe-mode", "ctty"], ["--probe", "1"], []):
            try:
                r = subprocess.run([exe, *extra, "--size", "2x1", tmp], capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode != 0:
                continue
            head = r.stdout[:64]
            if b"\x1bP" in head:
                return "sixel"
            if b"\x1b_G" in head:
                return "kitty"
            if b"\x1b]1337" in head:
                return "iterm"
            return "symbols"
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return "symbols"


def chafa_render(img, fmt: str, cols: int, rows: int, cell_w: float, cell_h: float,
                 border: int, border_rgb, symbols: str = ""):
    """Render `img` into a cols x rows cell box with chafa.

    Returns ("pixels", escape_sequence) for sixel / kitty / iterm,
            ("rows", [line, ...])       for symbols (one string per terminal row),
            or None when it cannot be rendered."""
    exe = chafa_path()
    if exe is None or img is None or cols < 2 or rows < 1 or fmt not in _CHAFA_FORMAT:
        return None

    pixel = fmt != "symbols"
    if pixel:
        # Real images: we fit the picture to the exact pixel box ourselves and draw the border
        # on it, then chafa only has to encode it.
        box_w, box_h = int(cols * cell_w), int(rows * cell_h)
        if box_w < 16 or box_h < 16:
            return None
        inner_w = max(8, box_w - 2 * border)
        inner_h = max(8, box_h - 2 * border)
        scale = min(inner_w / img.width, inner_h / img.height)
        work = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                          Image.Resampling.LANCZOS)
        if border > 0:
            work = ImageOps.expand(work, border=border, fill=tuple(border_rgb))
        attempts = [
            ["--exact-size", "on", "--align", "left,top", "--animate", "off"],
            ["--scale", "max", "--align", "left,top", "--animate", "off"],
            ["--scale", "max"],
        ]
    else:
        # Unicode symbols: chafa does the scaling in character cells (no border - it would be mush)
        work = img.copy()
        work.thumbnail((640, 640))
        common = ["--font-ratio", f"{cell_w / cell_h:.4f}", "--colors", "full", "--scale", "max"]
        if symbols:
            common += ["--symbols", symbols]
        attempts = [common + ["--align", "left,top", "--animate", "off"], common, []]

    base = ["-f", _CHAFA_FORMAT[fmt], "--size", f"{cols}x{rows}"]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        work.save(f.name, "PNG")
        tmp = f.name
    out = None
    try:
        for i in range(_chafa_attempt.get(fmt, 0), len(attempts)):
            try:
                r = subprocess.run([exe, *base, *attempts[i], tmp], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if r.returncode == 0 and r.stdout.strip():
                _chafa_attempt[fmt] = i
                out = r.stdout.decode("utf-8", "replace")
                break
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    if out is None:
        return None

    if pixel:
        return ("pixels", out.rstrip("\r\n"))
    lines = [ln.rstrip("\r") for ln in out.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    return ("rows", lines)


def fmt_time(s):
    if not s or s < 0:
        s = 0
    s = int(s)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def resample(data, n):
    """Resize a list of values to n entries (max when shrinking, linear when growing)."""
    m = len(data)
    if n <= 0:
        return []
    if m == 0:
        return [0] * n
    if m == n:
        return list(data)
    out = []
    for i in range(n):
        if m > n:
            lo = int(i * m / n)
            hi = max(lo + 1, int(math.ceil((i + 1) * m / n)))
            out.append(max(data[lo:hi]))
        else:
            pos = min(max((i + 0.5) * m / n - 0.5, 0), m - 1)
            i0 = int(pos)
            i1 = min(i0 + 1, m - 1)
            out.append(data[i0] + (data[i1] - data[i0]) * (pos - i0))
    return out


# --------------------------------------------------------------------------- #
#  Play history + Most Played
# --------------------------------------------------------------------------- #

def load_play_history() -> dict:
    """Return {path_str: {play_count, last_position, last_played, title, artist}}."""
    if not HISTORY_FILE.is_file():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tracks"), dict):
            return data["tracks"]
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_play_history(tracks: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated": datetime.now(timezone.utc).isoformat(),
            "tracks": tracks,
        }
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(HISTORY_FILE)
    except Exception:
        pass


def update_most_played(tracks: dict, music_root: Path, folder_name: str, threshold: int) -> None:
    """Create/update ~/Music/Most Played with symlinks to tracks played >= threshold times."""
    if threshold < 1 or not folder_name:
        return
    try:
        dest = music_root / folder_name
        dest.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    wanted = {}
    for path_str, info in tracks.items():
        try:
            count = int(info.get("play_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count < threshold:
            continue
        src = Path(path_str)
        if not src.is_file():
            continue
        wanted[src.resolve()] = src

    # Remove stale symlinks that no longer qualify
    try:
        for entry in dest.iterdir():
            if not entry.is_symlink():
                continue
            try:
                target = entry.resolve()
            except Exception:
                try:
                    entry.unlink()
                except Exception:
                    pass
                continue
            if target not in wanted:
                try:
                    entry.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # Ensure a symlink exists for every qualifying track
    for resolved, src in wanted.items():
        link = dest / src.name
        try:
            if link.exists() or link.is_symlink():
                try:
                    if link.resolve() == resolved:
                        continue
                except Exception:
                    pass
                # name collision with a different file → prefix with parent dir
                link = dest / f"{src.parent.name} - {src.name}"
                if link.exists() or link.is_symlink():
                    try:
                        if link.resolve() == resolved:
                            continue
                    except Exception:
                        pass
                    continue
            os.symlink(src, link)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Track display template
# --------------------------------------------------------------------------- #

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _format_track_lines(template: str, meta: dict, playing_path: Path | None) -> list[str]:
    """Expand track_display template into a list of display lines."""
    if not template:
        return ["Nothing playing"] if not playing_path else [playing_path.stem]

    def repl(m):
        key = m.group(1).lower()
        if key == "title":
            return meta.get("title") or (playing_path.stem if playing_path else "")
        if key == "artist":
            return meta.get("artist") or ""
        if key == "album":
            return meta.get("album") or ""
        if key == "year":
            return meta.get("year") or ""
        if key == "genre":
            return meta.get("genre") or ""
        if key == "container":
            return meta.get("container") or ""
        if key == "channels":
            return meta.get("channels_label") or ""
        if key == "bitrate":
            return meta.get("bitrate_label") or ""
        if key == "samplerate":
            return meta.get("samplerate_label") or ""
        if key == "duration":
            return fmt_time(meta.get("duration") or 0)
        if key == "path":
            return str(playing_path) if playing_path else ""
        return m.group(0)

    # Support both real newlines and the literal \n that appears in config files
    text = template.replace("\\n", "\n")
    text = _PLACEHOLDER_RE.sub(repl, text)
    # Clean up common leftover separators when a field is empty
    # e.g. " -  []" or " - " at ends
    lines = []
    for raw in text.split("\n"):
        line = raw
        # collapse multiple spaces
        line = re.sub(r"[ \t]{2,}", " ", line)
        # tidy separators around empty fields
        line = re.sub(r"\s*-\s*-\s*", " - ", line)
        line = re.sub(r"\[\s*\]", "", line)
        line = re.sub(r"\(\s*\)", "", line)
        line = re.sub(r"^\s*[-–—|:]\s*", "", line)
        line = re.sub(r"\s*[-–—|:]\s*$", "", line)
        line = line.strip()
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- #
#  Stream playlists (yt-dlp lists the videos, mpv streams them)
# --------------------------------------------------------------------------- #

class StreamEntry:
    """Virtual browser entry for the streaming feature.

    kind: "root" (the playlists folder) | "playlist" | "track".
    It mimics the few pathlib.Path methods the browser / player code relies on,
    so a streamed track can be selected, played and tracked like a local file."""
    __slots__ = ("kind", "name", "data", "file")

    def __init__(self, kind, name, data=None, file=None):
        self.kind, self.name, self.data, self.file = kind, name, data or {}, file

    def is_dir(self):
        return self.kind != "track"

    def is_file(self):
        return self.kind == "track"

    def resolve(self):
        return self

    @property
    def stem(self):
        return self.name

    @property
    def key(self):
        if self.kind == "track":
            return ("track", self.data.get("url") or self.name)
        if self.kind == "playlist":
            return ("playlist", str(self.file))
        return ("root", "")

    def __eq__(self, other):
        return isinstance(other, StreamEntry) and self.key == other.key

    def __hash__(self):
        return hash(self.key)

    def __str__(self):                  # the URL for a track (this is what mpv plays)
        return self.key[1]


class PlaylistError(Exception):
    pass


_PL_CACHE = {}


def read_playlist(f: Path):
    """Load a saved playlist JSON (cached until the file changes). None if unreadable."""
    try:
        st = f.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    hit = _PL_CACHE.get(str(f))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
        return None
    _PL_CACHE[str(f)] = (sig, data)
    return data


def list_playlists() -> list:
    out = []
    try:
        files = sorted(PLAYLISTS_DIR.glob("*.json"))
    except OSError:
        files = []
    for f in files:
        data = read_playlist(f)
        if data is not None:
            out.append(StreamEntry("playlist", clean_playlist_title(data.get("title") or f.stem), file=f))
    out.sort(key=lambda e: natural_key(e.name))
    return out


def clean_playlist_title(title: str) -> str:
    """YouTube Music names albums "Album - Name" (also "Single - ..." / "EP - ...").
    Show just the name."""
    cleaned = re.sub(r"^\s*(?:Album|Single|EP)\s+-\s+", "", str(title or ""))
    return cleaned.strip() or str(title or "").strip()


def center_square(img):
    """Crop an image to a centered square (16:9 thumbnails -> 1:1)."""
    w, h = img.size
    side = min(w, h)
    if w == h:
        return img
    x0, y0 = (w - side) // 2, (h - side) // 2
    return img.crop((x0, y0, x0 + side, y0 + side))


def _single_video(info):
    """Track dict for a single video/song (yt-dlp returns the full info for those)."""
    if not isinstance(info, dict) or not info.get("id") or not info.get("title"):
        return None
    vid = str(info["id"])
    link = str(info.get("webpage_url") or info.get("original_url") or "")
    if not link.startswith("http"):
        link = f"https://www.youtube.com/watch?v={vid}"
    thumbs = [t for t in (info.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    best = max(thumbs, key=lambda t: t.get("width") or t.get("height") or 0, default=None)
    artist = re.sub(r"\s*-\s*Topic$", "",
                    str(info.get("artist") or info.get("channel") or info.get("uploader") or "")).strip()
    dur = info.get("duration")
    track = {
        "id": vid,
        "url": link,
        "title": str(info["title"]).strip(),
        "artist": artist,
        "duration": int(dur) if isinstance(dur, (int, float)) else 0,
        "thumbnail": str(info.get("thumbnail") or (best or {}).get("url") or ""),
    }
    # extra facts that a full extraction knows (a playlist listing does not)
    year = str(info.get("release_year") or "") or _tag_year(info.get("release_date"))
    if _tag_year(year):
        track["year"] = _tag_year(year)
    if info.get("album"):
        track["album"] = str(info["album"]).strip()
    if isinstance(info.get("genre"), str) and info["genre"].strip():
        track["genre"] = info["genre"].strip()
    return track


def add_single_track(track: dict, list_title: str) -> bool:
    """Append a track to the 'single tracks' playlist. False if it is already there."""
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    f = PLAYLISTS_DIR / "saved-tracks.json"
    now = datetime.now(timezone.utc).isoformat()
    data = dict(read_playlist(f) or {"version": 1, "id": "saved-tracks", "url": "", "added": now,
                                     "tracks": []})
    tracks = [t for t in data["tracks"] if isinstance(t, dict)]
    if any(t.get("url") == track["url"] or (track["id"] and t.get("id") == track["id"]) for t in tracks):
        return False
    data.update(title=list_title, updated=now, tracks=tracks + [track])
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return True


def fetch_playlist(url: str) -> dict:
    """Ask yt-dlp about a URL (a playlist is listed flat: nothing is downloaded).
    Returns {id, title, tracks}; for a single video also {"single": True}."""
    exe = shutil.which("yt-dlp")
    if not exe:
        raise PlaylistError("yt-dlp not found - install it to add playlists")
    cmd = [exe, "--flat-playlist", "--yes-playlist", "--no-warnings", "-J", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise PlaylistError("yt-dlp took too long")
    except OSError as e:
        raise PlaylistError(f"could not run yt-dlp: {e}")

    out = (r.stdout or "").strip()
    if not out:
        lines = [ln.strip() for ln in (r.stderr or "").splitlines() if ln.strip()]
        raise PlaylistError(re.sub(r"^ERROR:\s*", "", lines[-1] if lines else "yt-dlp failed")[:200])
    try:
        info = json.loads(out)
    except ValueError:
        raise PlaylistError("unexpected output from yt-dlp")
    entries = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(entries, list):
        track = _single_video(info)               # a plain video / song URL
        if track is None:
            raise PlaylistError("that URL is not a playlist or video")
        return {"single": True, "id": track["id"], "title": track["title"], "tracks": [track]}

    tracks = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or "").strip()
        if title in ("[Private video]", "[Deleted video]"):
            continue
        vid = str(e.get("id") or "")
        link = str(e.get("url") or e.get("webpage_url") or "")
        if not link.startswith("http"):
            if not vid:
                continue
            link = f"https://www.youtube.com/watch?v={vid}"
        thumbs = [t for t in (e.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
        best = max(thumbs, key=lambda t: t.get("width") or t.get("height") or 0, default=None)
        artist = re.sub(r"\s*-\s*Topic$", "", str(e.get("channel") or e.get("uploader") or "")).strip()
        dur = e.get("duration")
        tracks.append({
            "id": vid,
            "url": link,
            "title": title or vid or "Untitled",
            "artist": artist,
            "duration": int(dur) if isinstance(dur, (int, float)) else 0,
            "thumbnail": best["url"] if best else str(e.get("thumbnail") or ""),
        })
    if not tracks:
        raise PlaylistError("the playlist is empty or private")
    return {"id": str(info.get("id") or ""),
            "title": clean_playlist_title(info.get("title") or "Playlist"),
            "tracks": tracks}


def save_playlist(info: dict, url: str) -> Path:
    """Write the playlist to PLAYLISTS_DIR/<id>.json (adding the same one again refreshes it)."""
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    pid = re.sub(r"[^A-Za-z0-9._-]", "_", info.get("id") or "") \
        or hashlib.sha1(url.encode()).hexdigest()[:12]
    f = PLAYLISTS_DIR / f"{pid}.json"
    now = datetime.now(timezone.utc).isoformat()
    old = read_playlist(f)
    payload = {
        "version": 1,
        "title": info["title"],
        "url": url,
        "id": pid,
        "added": (old or {}).get("added") or now,
        "updated": now,
        "tracks": info["tracks"],
    }
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return f


def stream_metadata(entry: StreamEntry) -> dict:
    """Same shape as get_metadata(), built from what the playlist file knows."""
    d = entry.data
    return {
        "title": d.get("title") or entry.name,
        "artist": d.get("artist") or "",
        "album": d.get("album") or d.get("playlist") or "",     # real album if known, else the playlist
        "year": str(d.get("year") or ""),
        "genre": d.get("genre") or "",
        "duration": d.get("duration") or 0,
        "container": "STREAM",
        "channels": 0,
        "channels_label": "",
        "bitrate": 0,
        "samplerate": 0,
        "bitrate_label": "",
        "samplerate_label": "",
    }


def trim_black_bars(img):
    """YouTube thumbnails often have black bars (square art inside a 16:9 frame, or a
    16:9 picture inside a 4:3 frame). Crop them, but only when the geometry matches exactly
    and the bars really are black, so dark artwork is never cut."""
    try:
        w, h = img.size
        gray = img.convert("L")
        dark = lambda box: box[2] > box[0] and box[3] > box[1] and gray.crop(box).getextrema()[1] <= 24
        if 1.6 < w / h < 1.9:                                   # pillarbox in a 16:9 frame
            for ratio in (1.0, 4 / 3):
                cwid = int(round(h * ratio))
                x0 = (w - cwid) // 2
                if 0 < cwid < w * 0.95 and dark((0, 0, x0 - 6, h)) and dark((x0 + cwid + 6, 0, w, h)):
                    return img.crop((x0, 0, x0 + cwid, h))
        elif 1.25 < w / h < 1.4:                                # letterbox in a 4:3 frame
            chei = int(round(w * 9 / 16))
            y0 = (h - chei) // 2
            if 0 < chei < h * 0.95 and dark((0, 0, w, y0 - 4)) and dark((0, y0 + chei + 4, w, h)):
                return img.crop((0, y0, w, y0 + chei))
    except Exception:
        pass
    return img


def fetch_thumbnail(d: dict):
    """Download (and cache) the thumbnail of a streamed track. Returns a PIL image or None."""
    vid = re.sub(r"[^A-Za-z0-9_-]", "", str(d.get("id") or ""))
    cache = THUMB_DIR / f"{vid}.img" if vid else None
    data = None
    if cache and cache.is_file():
        try:
            data = cache.read_bytes()
        except OSError:
            data = None
    if data is None:
        urls = []
        if vid:
            urls.append(f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")    # 404 on older videos
        if d.get("thumbnail"):
            urls.append(str(d["thumbnail"]))
        if vid:
            urls.append(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg")
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    blob = resp.read(8 * 1024 * 1024)
                if blob and _image_from_bytes(blob) is not None:
                    data = blob
                    break
            except Exception:
                continue
        if data and cache:
            try:
                THUMB_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(data)
            except OSError:
                pass
    img = _image_from_bytes(data)
    return trim_black_bars(img) if img else None


def _end_reason(event):
    """Best-effort 'reason' of an mpv end-file event across python-mpv versions."""
    try:
        if isinstance(event, dict):
            reason = event.get("reason")
            if reason is None and isinstance(event.get("event"), dict):
                reason = event["event"].get("reason")
            return reason
        reason = getattr(event, "reason", None)
        data = getattr(event, "data", None)
        if reason is None and data is not None:
            reason = getattr(data, "reason", None)
            if reason is None and isinstance(data, dict):
                reason = data.get("reason")
        return reason
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Stream URL pre-resolver (yt-dlp → direct media URL)
# --------------------------------------------------------------------------- #

class StreamURLCache:
    """Resolve YouTube page URLs to direct stream URLs in the background.

    The expensive step when playing a stream is yt-dlp extraction (~3–6 s).
    Once we have the direct googlevideo / media URL, mpv opens it almost
    instantly. Entries are kept in memory and optionally on disk, with a TTL
    (YouTube signed URLs expire after a few hours).
    """

    def __init__(self, ttl=2700, disk=True, workers=1):
        self.ttl = max(60, int(ttl))
        self.disk = bool(disk)
        self._lock = threading.Lock()
        # page_url -> {"direct": str, "expires": float (unix), "fetched": float}
        self._mem = {}
        self._pending = set()          # page URLs currently being resolved
        self._q = queue.Queue()
        self._load_disk()
        self._stop = False
        self._workers = []
        for _ in range(max(1, int(workers))):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)

    # ------------------------------------------------------------------ cache
    def _load_disk(self):
        if not self.disk or not STREAM_CACHE_FILE.is_file():
            return
        try:
            data = json.loads(STREAM_CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            now = time.time()
            with self._lock:
                for url, entry in data.items():
                    if not isinstance(entry, dict):
                        continue
                    exp = float(entry.get("expires") or 0)
                    direct = entry.get("direct")
                    if direct and exp > now + 30:
                        self._mem[url] = {
                            "direct": str(direct),
                            "expires": exp,
                            "fetched": float(entry.get("fetched") or exp - self.ttl),
                        }
        except Exception:
            pass

    def _save_disk(self):
        if not self.disk:
            return
        try:
            now = time.time()
            with self._lock:
                payload = {
                    u: {"direct": e["direct"], "expires": e["expires"],
                        "fetched": e.get("fetched", now)}
                    for u, e in self._mem.items()
                    if e.get("expires", 0) > now + 30 and e.get("direct")
                }
            STREAM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STREAM_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(STREAM_CACHE_FILE)
        except Exception:
            pass

    def get(self, page_url: str):
        """Return a still-valid direct URL, or None."""
        if not page_url:
            return None
        now = time.time()
        with self._lock:
            e = self._mem.get(page_url)
            if e and e.get("expires", 0) > now and e.get("direct"):
                return e["direct"]
            if e:
                self._mem.pop(page_url, None)
        return None

    def put(self, page_url: str, direct: str):
        if not page_url or not direct:
            return
        now = time.time()
        with self._lock:
            self._mem[page_url] = {
                "direct": direct,
                "expires": now + self.ttl,
                "fetched": now,
            }
            self._pending.discard(page_url)
        self._save_disk()

    def invalidate(self, page_url: str):
        with self._lock:
            self._mem.pop(page_url, None)
            self._pending.discard(page_url)
        self._save_disk()

    def is_pending(self, page_url: str) -> bool:
        with self._lock:
            return page_url in self._pending

    def enqueue(self, page_url: str, priority=False):
        """Request background resolution of *page_url* (no-op if already cached/pending)."""
        if not page_url or not page_url.startswith("http"):
            return
        with self._lock:
            e = self._mem.get(page_url)
            if e and e.get("expires", 0) > time.time() + 60:
                return
            if page_url in self._pending:
                return
            self._pending.add(page_url)
        if priority:
            # simple priority: put a sentinel so the worker can prefer it
            self._q.put((0, page_url))
        else:
            self._q.put((1, page_url))

    def enqueue_many(self, urls, priority_first=True):
        for i, u in enumerate(urls):
            self.enqueue(u, priority=(priority_first and i == 0))

    # ---------------------------------------------------------------- worker
    def _worker(self):
        while not self._stop:
            try:
                prio, url = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                direct = self._resolve(url)
                if direct:
                    self.put(url, direct)
                else:
                    with self._lock:
                        self._pending.discard(url)
            except Exception:
                with self._lock:
                    self._pending.discard(url)
            finally:
                self._q.task_done()

    @staticmethod
    def _resolve(page_url: str) -> str | None:
        """Run yt-dlp -g and return the first direct media URL, or None."""
        exe = shutil.which("yt-dlp")
        if not exe:
            return None
        cmd = [
            exe,
            "-g",
            "-f", "bestaudio/best",
            "--no-playlist",
            "--no-warnings",
            "--no-check-certificates",
            page_url,
        ]
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if r.returncode != 0:
            return None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("http"):
                return line
        return None

    def stop(self):
        self._stop = True


# --------------------------------------------------------------------------- #
#  Lyrics (LiriQo multi-provider → cached JSON with timestamps)
# --------------------------------------------------------------------------- #

_LRC_LINE_RE = re.compile(
    r"\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]\s*(.*)$"
)
_LRC_WORD_RE = re.compile(
    r"<(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?>\s*([^\s<]*)"
)


def _lrc_time_to_ms(m: re.Match) -> int:
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    frac = m.group(3) or "0"
    ms = int((frac + "000")[:3])
    return minutes * 60_000 + seconds * 1_000 + ms


def parse_lrc(synced: str) -> list[dict]:
    """Parse standard or Enhanced LRC into a list of line dicts.

    Each line: {"start_ms": int, "text": str, "words": [{"start_ms": int, "text": str}, ...] | None}
    Word-level timing is present when the source used Enhanced LRC (<mm:ss.xx> tags).
    """
    if not synced or not isinstance(synced, str):
        return []
    lines = []
    for raw in synced.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # skip metadata tags like [ar:…] [ti:…] [offset:…]
        if re.match(r"^\[\s*[a-zA-Z]", raw):
            continue
        m = _LRC_LINE_RE.match(raw)
        if not m:
            continue
        start_ms = _lrc_time_to_ms(m)
        rest = (m.group(4) or "").strip()
        words = None
        # Enhanced / karaoke LRC: <mm:ss.xx>word <mm:ss.xx>word …
        if "<" in rest and ">" in rest:
            found = list(_LRC_WORD_RE.finditer(rest))
            if found:
                words = []
                plain_parts = []
                for wm in found:
                    w_ms = _lrc_time_to_ms(wm)
                    w_txt = (wm.group(4) or "").strip()
                    if w_txt:
                        words.append({"start_ms": w_ms, "text": w_txt})
                        plain_parts.append(w_txt)
                rest = " ".join(plain_parts) if plain_parts else rest
        lines.append({
            "start_ms": start_ms,
            "text": rest,
            "words": words,
        })
    lines.sort(key=lambda x: x["start_ms"])
    return lines


def _lyrics_cache_key(title: str, artist: str, duration: float | int | None) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    a = re.sub(r"\s+", " ", (artist or "").strip().lower())
    d = int(round(float(duration or 0)))
    raw = f"{t}|{a}|{d}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _lyrics_cache_path(key: str) -> Path:
    return LYRICS_DIR / f"{key}.json"


def load_cached_lyrics(key: str) -> dict | None:
    path = _lyrics_cache_path(key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and (data.get("lines") is not None or data.get("instrumental")):
            return data
    except Exception:
        pass
    return None


def save_cached_lyrics(key: str, data: dict) -> None:
    try:
        LYRICS_DIR.mkdir(parents=True, exist_ok=True)
        path = _lyrics_cache_path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _liriqo_track_to_lines(track: dict) -> tuple[list[dict], bool]:
    """Convert a LiriQo track object into our line list + has_word_sync flag.

    Word token text is kept as returned (including trailing spaces). Joining
    tokens with '' later avoids the artificial widening that happens when
    syllable/character tokens are re-spaced.
    """
    timed = track.get("timed") or []
    if not isinstance(timed, list) or not timed:
        return [], False

    words_map = track.get("words") if isinstance(track.get("words"), dict) else {}

    lines = []
    has_word = False
    for entry in timed:
        if not isinstance(entry, dict):
            continue
        try:
            start_ms = int(entry.get("start") if entry.get("start") is not None else 0)
        except (TypeError, ValueError):
            start_ms = 0
        text = (entry.get("text") or "").strip()
        if not text and not entry.get("words"):
            continue

        words = None
        raw_words = entry.get("words")
        if not raw_words and words_map:
            lid = entry.get("id")
            if lid is not None:
                raw_words = words_map.get(str(lid)) or words_map.get(lid)

        if isinstance(raw_words, list) and raw_words:
            words = []
            plain_parts = []
            for w in raw_words:
                if not isinstance(w, dict):
                    continue
                # Keep original spacing inside the token (often ends with a space)
                w_txt = w.get("text")
                if w_txt is None:
                    continue
                w_txt = str(w_txt)
                if not w_txt.strip():
                    # Preserve pure whitespace tokens so joins stay correct
                    if w_txt:
                        words.append({"start_ms": start_ms, "text": w_txt})
                        plain_parts.append(w_txt)
                    continue
                try:
                    w_ms = int(w.get("start") if w.get("start") is not None else start_ms)
                except (TypeError, ValueError):
                    w_ms = start_ms
                words.append({"start_ms": w_ms, "text": w_txt})
                plain_parts.append(w_txt)
            if words:
                has_word = True
                joined = "".join(plain_parts)
                if not text:
                    text = joined.strip()
            else:
                words = None

        lines.append({
            "start_ms": start_ms,
            "text": text,
            "words": words,
        })

    lines.sort(key=lambda x: x["start_ms"])
    return lines, has_word


# Preferred sync ladder (higher = richer). "character" counts as syllable.
_SYNC_RANK = {
    "syllable": 3,
    "character": 3,
    "word": 2,
    "line": 1,
    "plain": 0,
    "": 0,
}


def _normalize_sync_pref(value: str | None) -> str:
    v = (value or "word").strip().lower()
    if v in ("syllable", "syll", "syl", "character", "char"):
        return "syllable"
    if v in ("word", "words"):
        return "word"
    if v in ("line", "lines"):
        return "line"
    if v in ("off", "none", "disable", "disabled", "plain"):
        return "off"
    return "word"


def _tokens_are_chars(words: list, text: str = "") -> bool:
    """True when the timed token list looks like per-character / syllable karaoke."""
    if not words:
        return False
    stripped = [str(w.get("text") or "").strip() for w in words]
    stripped = [t for t in stripped if t]
    if not stripped:
        return False
    med = sorted(len(t) for t in stripped)[len(stripped) // 2]
    n_space_words = max(1, len((text or "").split())) if text else 1
    return med <= 1 or len(stripped) > n_space_words * 2


def _clipboard_copy(text: str) -> bool:
    """Copy text to the system clipboard. Tries wl-copy, xclip, xsel, pbcopy."""
    if not text:
        return False
    payload = text.encode("utf-8", "replace")
    candidates = [
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
    ]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(
                cmd, input=payload, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=3,
            )
            if r.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _clipboard_paste() -> str | None:
    """Read text from the system clipboard. Tries wl-paste, xclip, xsel, pbpaste."""
    candidates = [
        ["wl-paste", "-n"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["pbpaste"],
    ]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", "replace")
        except Exception:
            continue
    return None


_LRC_LINE_RE = re.compile(
    r"^\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)$"
)
_LRC_WORD_RE = re.compile(
    r"<(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?>\s*([^<]*)"
)


def _lrc_stamp_to_ms(m: re.Match, g_min=1, g_sec=2, g_frac=3) -> int:
    mins = int(m.group(g_min))
    secs = int(m.group(g_sec))
    frac = m.group(g_frac) or "0"
    if len(frac) == 1:
        frac = frac + "00"
    elif len(frac) == 2:
        frac = frac + "0"
    elif len(frac) > 3:
        frac = frac[:3]
    return (mins * 60 + secs) * 1000 + int(frac)


def _normalize_pasted_lines(raw_lines) -> tuple[list[dict], bool, bool]:
    """Normalize a list of line dicts from YAML/JSON into our internal shape.

    Returns (lines, has_word, any_timed).
    """
    lines_out: list[dict] = []
    has_word = False
    any_timed = False
    if not isinstance(raw_lines, list):
        return [], False, False

    for entry in raw_lines:
        if not isinstance(entry, dict):
            if isinstance(entry, str) and entry.strip():
                lines_out.append({"start_ms": 0, "text": entry.strip(), "words": None})
            continue
        text = entry.get("text")
        if text is None:
            text = entry.get("line") or entry.get("lyric") or ""
        text = str(text) if text is not None else ""
        try:
            start_ms = int(entry.get("start_ms", entry.get("start", 0)) or 0)
        except (TypeError, ValueError):
            start_ms = 0
        try:
            end_ms = entry.get("end_ms", entry.get("end"))
            end_ms = int(end_ms) if end_ms is not None else None
        except (TypeError, ValueError):
            end_ms = None

        words_raw = entry.get("words") or entry.get("syllables") or entry.get("tokens")
        words = None
        if isinstance(words_raw, list) and words_raw:
            words = []
            for w in words_raw:
                if not isinstance(w, dict):
                    continue
                w_txt = w.get("text")
                if w_txt is None:
                    continue
                w_txt = str(w_txt)
                try:
                    w_ms = int(w.get("start_ms", w.get("start", start_ms)) or start_ms)
                except (TypeError, ValueError):
                    w_ms = start_ms
                words.append({"start_ms": w_ms, "text": w_txt})
            if words:
                has_word = True
                if not text.strip():
                    text = "".join(w["text"] for w in words).rstrip()
            else:
                words = None

        if not text.strip() and not words:
            continue
        if start_ms > 0 or words:
            any_timed = True
        item = {"start_ms": start_ms, "text": text, "words": words}
        if end_ms is not None:
            item["end_ms"] = end_ms
        lines_out.append(item)

    lines_out.sort(key=lambda x: x.get("start_ms") or 0)
    return lines_out, has_word, any_timed


def _structured_lyrics_from_obj(obj: dict) -> dict | None:
    """Convert a YAML/JSON lyrics object into our cache dict."""
    if not isinstance(obj, dict):
        return None

    # Already in our cache shape
    if isinstance(obj.get("lines"), list) and (
        obj.get("source") or obj.get("sync_level") is not None or "has_word_sync" in obj
    ):
        lines, has_word, any_timed = _normalize_pasted_lines(obj.get("lines"))
        if not lines and not obj.get("plain") and not obj.get("instrumental"):
            return None
        plain = obj.get("plain")
        if not plain and lines:
            plain = "\n".join(ln.get("text") or "" for ln in lines)
        if has_word:
            level = "word"
        elif any_timed:
            level = "line"
        else:
            level = obj.get("sync_level") or "plain"
        return {
            "source": "user",
            "provider": "paste",
            "sync_level": level,
            "instrumental": bool(obj.get("instrumental")),
            "synced": bool(any_timed and not obj.get("instrumental")),
            "has_word_sync": has_word,
            "plain": plain,
            "lines": lines,
            "missing": False,
            "user_override": True,
        }

    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    raw_lines = obj.get("lines") or obj.get("timed") or obj.get("lyrics")
    lines, has_word, any_timed = _normalize_pasted_lines(raw_lines)
    plain = obj.get("plain")
    if isinstance(plain, str):
        plain = plain.strip() or None
    else:
        plain = None
    if not plain and lines:
        plain = "\n".join(ln.get("text") or "" for ln in lines if ln.get("text"))

    instrumental = bool(obj.get("instrumental") or meta.get("instrumental"))
    if instrumental and not lines and not plain:
        return {
            "source": "user",
            "provider": "paste",
            "sync_level": "plain",
            "instrumental": True,
            "synced": False,
            "has_word_sync": False,
            "plain": None,
            "lines": [],
            "missing": False,
            "user_override": True,
        }

    if not lines and not plain:
        return None

    if not lines and plain:
        lines = [{"start_ms": 0, "text": p, "words": None}
                 for p in plain.splitlines() if p.strip()]
        any_timed = False
        has_word = False

    if has_word:
        sync_level = "word"
        synced = True
    elif any_timed:
        sync_level = "line"
        synced = True
    else:
        sync_level = "plain"
        synced = False

    return {
        "source": "user",
        "provider": "paste",
        "sync_level": sync_level,
        "instrumental": False,
        "synced": synced,
        "has_word_sync": has_word,
        "plain": plain,
        "lines": lines,
        "missing": False,
        "user_override": True,
    }


def _try_parse_structured_lyrics(text: str) -> dict | None:
    """Try JSON, then YAML (PyYAML if installed), for structured timed lyrics."""
    stripped = text.strip()
    if not stripped:
        return None

    # JSON (our cache format or same shape as the YAML example)
    if stripped[0] in "{[":
        try:
            obj = json.loads(stripped)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            return _structured_lyrics_from_obj(obj)
        if isinstance(obj, list):
            return _structured_lyrics_from_obj({"lines": obj})

    # YAML heuristics: top-level keys typical of this format
    looks_yaml = bool(re.search(
        r"(?m)^(version|metadata|lines|plain|sync_level|instrumental)\s*:",
        stripped,
    ))
    if not looks_yaml:
        return None

    try:
        import yaml  # type: ignore
    except ImportError:
        # Soft dependency — user can `pip install pyyaml` for YAML paste
        return None

    try:
        obj = yaml.safe_load(stripped)
    except Exception:
        return None
    if isinstance(obj, dict):
        return _structured_lyrics_from_obj(obj)
    if isinstance(obj, list):
        return _structured_lyrics_from_obj({"lines": obj})
    return None


def parse_lyrics_text(raw: str) -> dict | None:
    """Parse pasted lyrics: YAML/JSON timed, enhanced LRC, plain LRC, or plain text.

    Structured YAML example (word sync)::

        version: '1.0'
        metadata: {title: ..., artist: ...}
        lines:
          - text: Hello world
            start_ms: 1000
            words:
              - {text: 'Hello ', start_ms: 1000}
              - {text: world, start_ms: 1400}
        plain: |
          Hello world

    Requires ``pip install pyyaml`` only for YAML; JSON of the same shape works
    with the stdlib. LRC and plain text need no extra deps.
    """
    if not raw or not str(raw).strip():
        return None
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")

    structured = _try_parse_structured_lyrics(text)
    if structured is not None:
        return structured

    lines_out: list[dict] = []
    plain_parts: list[str] = []
    has_word = False
    any_timed = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Skip common LRC metadata tags
        if re.match(r"^\[(ar|ti|al|by|offset|re|ve|length):", line, re.I):
            continue
        m = _LRC_LINE_RE.match(line)
        if m:
            start_ms = _lrc_stamp_to_ms(m)
            rest = (m.group(4) or "").strip()
            words = None
            # Enhanced LRC: <mm:ss.xx>word
            if rest and "<" in rest and _LRC_WORD_RE.search(rest):
                words = []
                for wm in _LRC_WORD_RE.finditer(rest):
                    w_ms = _lrc_stamp_to_ms(wm)
                    w_txt = (wm.group(4) or "").rstrip()
                    if not w_txt:
                        continue
                    # Keep a trailing space so sequential join reconstructs the line
                    if not w_txt.endswith(" "):
                        w_txt = w_txt + " "
                    words.append({"start_ms": w_ms, "text": w_txt})
                if words:
                    has_word = True
                    rest = "".join(w["text"] for w in words).rstrip()
                else:
                    words = None
            if rest or words:
                any_timed = True
                lines_out.append({
                    "start_ms": start_ms,
                    "text": rest,
                    "words": words,
                })
                plain_parts.append(rest)
            continue
        # Untimed line
        plain_parts.append(line)
        lines_out.append({"start_ms": 0, "text": line, "words": None})

    if not lines_out:
        return None

    # If nothing was timed, treat as plain text
    if not any_timed:
        for ln in lines_out:
            ln["start_ms"] = 0
            ln["words"] = None
        sync_level = "plain"
        synced = False
        has_word = False
    elif has_word:
        sync_level = "word"
        synced = True
    else:
        sync_level = "line"
        synced = True

    plain = "\n".join(plain_parts)
    return {
        "source": "user",
        "provider": "paste",
        "sync_level": sync_level,
        "instrumental": False,
        "synced": synced,
        "has_word_sync": has_word,
        "plain": plain,
        "lines": lines_out,
        "missing": False,
        "user_override": True,
    }


def delete_cached_lyrics(key: str) -> bool:
    path = _lyrics_cache_path(key)
    try:
        if path.is_file():
            path.unlink()
            return True
    except Exception:
        pass
    return False


def _pick_liriqo_track(payload: dict, preferred: str) -> dict | None:
    """Choose the best track for the user's preferred sync level (fall downward only).

    Priority is strict: never select a *richer* tier than requested.
    syllable/character (3) > word (2) > line (1) > plain (0)
    """
    tracks = []
    primary = payload.get("primary")
    if isinstance(primary, dict) and (primary.get("timed") or primary.get("plain")):
        tracks.append(primary)
    for t in payload.get("tracks") or []:
        if isinstance(t, dict) and t is not primary and (t.get("timed") or t.get("plain")):
            tracks.append(t)
    if not tracks:
        return None

    if preferred == "off":
        return tracks[0]

    want = _SYNC_RANK.get(preferred, 2)

    def rank(t: dict) -> int:
        lvl = (t.get("syncLevel") or "").lower()
        r = _SYNC_RANK.get(lvl, 0)
        if r == 0 and (t.get("timed") or []):
            r = 1  # timed without explicit level ≈ line
        # If the provider claims word/line but tokens look like per-character
        # karaoke, treat it as syllable so a "word" preference can reject it.
        if r >= 2 and preferred == "word":
            timed = t.get("timed") or []
            sample_words = []
            for entry in timed[:8]:
                for w in (entry.get("words") or [])[:12]:
                    if isinstance(w, dict):
                        sample_words.append(str(w.get("text") or "").strip())
            sample_words = [s for s in sample_words if s]
            if sample_words:
                med = sorted(len(s) for s in sample_words)[len(sample_words) // 2]
                # Many single-char tokens → character/syllable tier
                if med <= 1 and len(sample_words) >= 6:
                    r = 3
        return r

    candidates = [(rank(t), i, t) for i, t in enumerate(tracks)]
    # Exact preferred tier first
    exact = [c for c in candidates if c[0] == want]
    if exact:
        exact.sort(key=lambda c: c[1])
        return exact[0][2]
    # Otherwise closest lower tier
    below = [c for c in candidates if 0 < c[0] < want]
    if below:
        below.sort(key=lambda c: (-c[0], c[1]))
        return below[0][2]
    # Nothing usable at or below preference — plain text / whatever is left
    plain = [c for c in candidates if c[2].get("plain") or c[2].get("timed")]
    return plain[0][2] if plain else tracks[0]


def fetch_liriqo_lyrics(
    title: str,
    artist: str,
    album: str = "",
    duration: float | int | None = None,
    preferred_sync: str = "word",
) -> dict | None:
    """Query LiriQo (multi-provider). Returns a JSON-ready dict or None.

    Shape:
      {
        "source": "liriqo",
        "provider": str | None,
        "sync_level": str,
        "instrumental": bool,
        "synced": bool,
        "has_word_sync": bool,
        "plain": str | None,
        "lines": [ {"start_ms", "text", "words"?}, … ]
      }
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title or not artist:
        return None

    preferred_sync = _normalize_sync_pref(preferred_sync)

    base = "https://api.liriqo-alfarrizi.my.id/v1/lyrics"
    headers = {
        "User-Agent": "CWave/1.0 (https://github.com/cwave; terminal music player)",
        "Accept": "application/json",
    }

    params: dict = {
        "title": title,
        "artist": artist,
        "fast": "1",
    }
    if album:
        params["album"] = album
    try:
        if duration and float(duration) > 0:
            dur = int(round(float(duration)))
            if 1 <= dur <= 3600:
                params["duration"] = dur
    except (TypeError, ValueError):
        pass

    try:
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{base}?{q}", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None

    if not isinstance(payload, dict) or payload.get("error"):
        return None

    track = _pick_liriqo_track(payload, preferred_sync)
    if not isinstance(track, dict):
        return None

    sync_level = (track.get("syncLevel") or "").lower() or "line"
    provider = track.get("provider") or track.get("upstreamProvider")

    lines, has_word = _liriqo_track_to_lines(track)
    plain = track.get("plain")
    if isinstance(plain, str):
        plain = plain.strip() or None
    else:
        plain = None
    if not plain and lines:
        plain = "\n".join(ln["text"] for ln in lines if ln.get("text"))

    instrumental = bool(track.get("instrumental"))
    if instrumental or (not lines and not plain):
        return {
            "source": "liriqo",
            "provider": provider,
            "sync_level": "plain",
            "instrumental": True if instrumental else False,
            "synced": False,
            "has_word_sync": False,
            "plain": None,
            "lines": [],
            "missing": not instrumental,
        }

    synced = bool(lines)
    if not lines and plain:
        lines = [{"start_ms": 0, "text": p, "words": None} for p in plain.splitlines() if p.strip()]
        synced = False
        sync_level = "plain"

    # Honour the user's preferred tier at the data level so rendering stays simple.
    if preferred_sync in ("line", "off") and lines:
        for ln in lines:
            ln["words"] = None
        has_word = False
        if preferred_sync == "line" and synced:
            sync_level = "line"
    elif preferred_sync == "word" and lines and has_word:
        # Collapse character/syllable token streams into true word-level timing
        # (or drop to line highlight) so letter-by-letter karaoke never appears
        # when the user asked for words.
        for ln in lines:
            words = ln.get("words") or []
            if not words:
                continue
            tokens = [str(w.get("text") or "") for w in words]
            stripped = [t.strip() for t in tokens if t.strip()]
            if not stripped:
                ln["words"] = None
                continue
            med = sorted(len(t) for t in stripped)[len(stripped) // 2]
            text = ln.get("text") or ""
            n_space_words = max(1, len(text.split()))
            if med <= 1 or len(stripped) > n_space_words * 2:
                # Character-level stream → no per-token highlight in word mode
                ln["words"] = None
        has_word = any(ln.get("words") for ln in lines)
        if not has_word and synced:
            sync_level = "line"

    return {
        "source": "liriqo",
        "provider": provider,
        "sync_level": sync_level,
        "instrumental": False,
        "synced": synced,
        "has_word_sync": has_word or sync_level in ("word", "syllable", "character"),
        "plain": plain,
        "lines": lines,
        "preferred_sync": preferred_sync,
    }


def current_lyric_index(lines: list[dict], position_ms: int) -> int:
    """Index of the active line for position_ms, or -1 before the first line."""
    if not lines:
        return -1
    active = -1
    for i, ln in enumerate(lines):
        if ln["start_ms"] <= position_ms:
            active = i
        else:
            break
    return active


def current_word_index(words: list[dict] | None, position_ms: int) -> int:
    if not words:
        return -1
    active = -1
    for i, w in enumerate(words):
        if w["start_ms"] <= position_ms:
            active = i
        else:
            break
    return active


_JP_RE = re.compile(r"[\u3040-\u30FF\u31F0-\u9FFF\uFF66-\uFF9D]")


def contains_japanese(text: str) -> bool:
    return bool(text and _JP_RE.search(text))


def make_romaji_engine():
    """Return a callable text -> romaji, or None if pykakasi is not installed."""
    try:
        import pykakasi
        kks = pykakasi.kakasi()
        def _romaji(text: str) -> str:
            if not text or not contains_japanese(text):
                return text
            try:
                parts = kks.convert(text)
                return " ".join(p.get("hepburn") or p.get("passport") or "" for p in parts).strip()
            except Exception:
                return text
        return _romaji
    except Exception:
        return None


def ensure_romaji_on_lyrics(data: dict, engine) -> dict:
    """Add a 'romaji' field to each line that needs it. Mutates and returns data."""
    if not data or not engine:
        return data
    lines = data.get("lines") or []
    changed = False
    for ln in lines:
        if ln.get("romaji") is not None:
            continue
        text = ln.get("text") or ""
        if contains_japanese(text):
            ln["romaji"] = engine(text)
            changed = True
        else:
            ln["romaji"] = ""
    if changed:
        data["has_romaji"] = True
    return data


# --------------------------------------------------------------------------- #
#  Player
# --------------------------------------------------------------------------- #

class Player:
    def __init__(self):
        self.cfg = load_config()
        paths = self.cfg.get("directories", "paths", fallback="~/Music")
        self.roots = [expand(p.strip()) for p in paths.split(",") if p.strip()]
        if not self.roots:
            self.roots = [Path.home() / "Music"]
        self.root = self.roots[0]
        self.cwd = self.root
        self.history = []

        s = dict(self.cfg["style"]) if self.cfg.has_section("style") else {}
        col = lambda k: parse_color(s.get(k), parse_color(DEFAULT_COLORS[k], ("p", 255)))
        self.c_title  = col("title_color")
        self.c_sub    = col("subtitle_color")
        self.c_path   = col("path_color")
        self.c_back   = col("back_color")
        self.c_file   = col("file_color")
        self.c_special = col("special_color")
        self.c_sel_bg = col("selected_bg")
        self.c_sel_fg = col("selected_fg")
        self.c_play   = col("playing_color")
        self.c_prog   = col("progress_color")
        self.c_help   = col("help_color")
        self.c_viz    = col("viz_color")
        self.c_border = col("cover_border_color")

        self.enable_cover = parse_bool(s.get("enable_cover"), True)
        self.cover_border = num(s, "cover_border", 2, 0, 10)
        rend = str(s.get("cover_renderer", "auto")).strip().lower()
        self.cover_renderer = rend if rend in COVER_RENDERERS else "auto"
        sym = str(s.get("cover_symbols", "") or "").strip()
        self.cover_symbols = sym if re.fullmatch(r"[A-Za-z0-9+\-,._]+", sym) and not sym.startswith("-") else ""
        self.cover_format = None        # sixel | kitty | iterm | symbols - resolved in run()
        if self.cover_renderer == "off":
            self.enable_cover = False
        self.viz_bars     = num(s, "viz_bars", 0, 0, 256)       # 0 = auto
        self.viz_h        = num(s, "viz_height", 0, 0, 100)     # 0 = auto
        self.viz_bw       = num(s, "viz_bar_width", 1, 1, 10)
        self.viz_gap      = num(s, "viz_gap", 1, 0, 10)
        self.viz_fps      = num(s, "viz_fps", 30, 1, 144)
        self.seek_sec     = num(s, "seek_seconds", 5, 1, 600)
        mode = str(s.get("viz_mode", "bars")).strip().lower()
        self.viz_mode = mode if mode in ("bars", "blocks", "dots", "thin") else "bars"

        # relative sizes -> bold
        self.bold_title    = parse_size(s.get("title_size"), "large")
        self.bold_subtitle = parse_size(s.get("subtitle_size"), "normal")
        self.bold_path     = parse_size(s.get("path_size"), "normal")
        self.bold_file     = parse_size(s.get("file_size"), "normal")
        self.bold_progress = parse_size(s.get("progress_size"), "normal")
        self.bold_help     = parse_size(s.get("help_size"), "normal")

        # track display template
        raw_tpl = s.get("track_display", "{title}\\n{year} - {artist} [{album}]")
        self.track_template = str(raw_tpl).replace("\\n", "\n") if raw_tpl is not None else "{title}\n{year} - {artist} [{album}]"

        # playback options
        pb = dict(self.cfg["playback"]) if self.cfg.has_section("playback") else {}
        self.autoplay = parse_bool(pb.get("autoplay"), True)
        self.shuffle = parse_bool(pb.get("shuffle"), False)
        self.loop = parse_bool(pb.get("loop"), False)
        self.resume_enabled = parse_bool(pb.get("resume"), False)
        self.most_played_threshold = num(pb, "most_played_threshold", 5, 1, 100000)
        self.most_played_name = str(pb.get("most_played_name") or "Most Played").strip() or "Most Played"

        kb = dict(self.cfg["keybinds"]) if self.cfg.has_section("keybinds") else {}
        sk = str(kb.get("shuffle", "s")).strip()
        self.shuffle_key = sk[0].lower() if sk else "s"
        ak = str(kb.get("add_playlist", "y")).strip()
        self.add_playlist_key = ak[0].lower() if ak else "y"
        rk = str(kb.get("loop", "r")).strip()
        self.loop_key = rk[0].lower() if rk else "r"

        # lyrics
        ly = dict(self.cfg["lyrics"]) if self.cfg.has_section("lyrics") else {}
        self.enable_lyrics = parse_bool(ly.get("enable"), True)
        lk = str(ly.get("toggle", "l")).strip()
        self.lyrics_key = lk[0].lower() if lk else "l"
        self.lyrics_romaji = parse_bool(ly.get("romaji"), False)
        self.lyrics_sync = _normalize_sync_pref(ly.get("sync", "word"))
        try:
            self.lyrics_max_width = max(0, int(float(str(ly.get("max_width", "0")).strip() or "0")))
        except (TypeError, ValueError):
            self.lyrics_max_width = 0
        self.lyrics_copy_timestamps = parse_bool(ly.get("copy_timestamps"), False)
        self.lyrics_fullscreen_enabled = parse_bool(ly.get("fullscreen"), False)
        fk = str(ly.get("fullscreen_key", "f")).strip()
        self.lyrics_fullscreen_key = fk[0].lower() if fk else "f"
        self.lyrics = None          # parsed JSON dict or None
        self.lyrics_visible = False # right panel shows lyrics instead of file list
        self.lyrics_fullscreen = False  # entire screen is lyrics only
        self._lyrics_key = None     # cache key of the currently loaded lyrics
        self._lyrics_fetching = False
        self._romaji_engine = None  # lazy pykakasi instance
        self.lyrics_scroll = 0      # display-row offset into the rendered lyric buffer
        self.lyrics_scroll_manual = False  # user scrolled; pause autoscroll until reset
        self._lyrics_scroll_until = 0.0  # monotonic time when manual scroll expires
        # Right-panel lyrics cache: avoid rebuilding/writing the full panel every viz frame
        self._lyrics_panel_key = None
        self._lyrics_panel_cache = ""

        st = dict(self.cfg["streaming"]) if self.cfg.has_section("streaming") else {}
        self.stream_name = str(st.get("playlists_name") or "").strip() or "Stream Playlists"
        self.square_covers = parse_bool(st.get("square_covers"), True)
        self.single_name = str(st.get("single_tracks_name") or "").strip() or "Saved Tracks"
        self.preload_count = num(st, "preload_count", 4, 0, 30)
        self.preload_ttl = num(st, "preload_ttl", 2700, 60, 86400)
        self.preload_disk = parse_bool(st.get("preload_disk_cache"), True)
        self.stream_cache = StreamURLCache(
            ttl=self.preload_ttl, disk=self.preload_disk, workers=1,
        )

        self.play_history = load_play_history()

        # ytdl=True lets mpv resolve YouTube links through yt-dlp (libmpv has it off by default)
        self.mpv = mpv.MPV(video=False, terminal=False, quiet=True,
                           input_default_bindings=False, input_vo_keyboard=False,
                           ytdl=True, ytdl_format="bestaudio/best")
        self.playing = None
        self.meta = {}
        self.cover_img = None
        self._cover_cache = (None, None)
        self.paused = False
        self._track_ended = False
        self._switch_until = 0.0       # monotonic time; ignore end-file until then
        self._play_started_at = 0.0    # when current track began
        self._last_pos_save = 0.0      # last periodic position save
        self._resume_pos = None
        self._pending_resume = None    # seek target applied after file loads

        # stream playlists: vpath is the virtual folder chain we are inside ([] = normal browsing)
        self.vpath = []
        self.status = None             # (text, expires_at) shown above the help hint
        self._adding = False           # a playlist is being fetched in the background
        self._stream_dirty = False     # playlists changed on disk -> refresh the listing
        self._track_error = False      # mpv failed to play the current stream
        self._stream_fail = 0          # consecutive stream failures (stops the auto-skip loop)
        self._meta_pending = False     # a stream finished loading: re-read its tags

        self.files = []
        self.sel = 0
        self.cava_bars = self.viz_bars if self.viz_bars > 0 else 64
        self.viz = [0] * self.cava_bars
        self.cava = None
        self.cava_cfg = None
        self.running = True

        # redraw flags: full = whole screen, right = file list panel only
        self.full_dirty = True
        self.right_dirty = False
        self._layout = None
        self._dyn_cache = {}

        self._start_cava()
        self._scan()
        self._register_mpv_events()

        signal.signal(signal.SIGWINCH, lambda *a: setattr(self, "full_dirty", True))
        signal.signal(signal.SIGINT,  self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, *a):
        self.running = False

    # ------------------------------------------------------------------ cava
    def _start_cava(self):
        cfg = tempfile.NamedTemporaryFile("w", suffix=".cava", delete=False)
        cfg.write(f"""
[general]
bars = {self.cava_bars}
framerate = {self.viz_fps}
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 100
[input]
method = pulse
""")
        cfg.close()
        self.cava_cfg = cfg.name
        try:
            self.cava = subprocess.Popen(
                ["cava", "-p", cfg.name],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1
            )
            threading.Thread(target=self._cava_reader, daemon=True).start()
        except Exception:
            self.cava = None

    def _cava_reader(self):
        while self.running and self.cava and self.cava.poll() is None:
            line = self.cava.stdout.readline()
            if not line:
                break
            try:
                vals = [int(x) for x in line.strip().rstrip(";").split(";") if x.isdigit()]
                if vals:
                    self.viz = vals
            except Exception:
                pass

    def _cava_alive(self):
        return self.cava is not None and self.cava.poll() is None

    # ----------------------------------------------------------- file browser
    def _scan(self):
        if self.vpath:
            self.files = self._stream_listing()
        else:
            try:
                items = sorted(self.cwd.iterdir(),
                               key=lambda p: (not p.is_dir(), natural_key(p.name)))
                self.files = [p for p in items if p.is_dir() or is_audio(p)]
            except Exception:
                self.files = []
            if self.cwd == self.root:
                # the player's own folders go first: Stream Playlists, then Most Played
                mp = [p for p in self.files if p.is_dir() and p.name == self.most_played_name]
                self.files = mp + [p for p in self.files if p not in mp]
                self.files.insert(0, StreamEntry("root", self.stream_name))
        self.sel = min(self.sel, max(0, len(self.files) - 1))

    def _is_special(self, p):
        """Folders that belong to the player itself (not to the user's own music)."""
        if isinstance(p, StreamEntry):
            return p.kind == "root"
        return (not self.vpath and self.cwd == self.root
                and p.is_dir() and p.name == self.most_played_name)

    def _stream_listing(self):
        """Contents of the virtual folder we are in: the playlists, or one playlist's tracks."""
        if len(self.vpath) == 1:
            return list_playlists()
        pl = self.vpath[-1]
        return self._playlist_tracks(pl.file, pl.name)

    def _playlist_tracks(self, f, fallback_name=""):
        data = read_playlist(f) if f else None
        if not data:
            return []
        album = clean_playlist_title(data.get("title") or fallback_name)
        return [StreamEntry("track", t.get("title") or t.get("id") or "Untitled",
                            data={**t, "playlist": album}, file=f)
                for t in data["tracks"] if isinstance(t, dict) and t.get("url")]

    def can_go_up(self):
        return bool(self.vpath) or bool(self.history) or self.cwd != self.root

    def go_up(self):
        """Leave the current folder and re-select it in the parent listing."""
        left_path = None   # Path we just left (filesystem)
        left_entry = None  # StreamEntry we just left (virtual stream tree)
        if self.vpath:
            left_entry = self.vpath.pop()
        elif self.history:
            left_path = self.cwd
            self.cwd = self.history.pop()
        elif self.cwd != self.root:
            left_path = self.cwd
            self.cwd = self.cwd.parent
        else:
            return
        self._scan()
        # Prefer the folder we came from; fall back to the first item
        self.sel = 0
        if left_path is not None:
            for i, p in enumerate(self.files):
                if not isinstance(p, StreamEntry) and p == left_path:
                    self.sel = i
                    break
        elif left_entry is not None:
            for i, p in enumerate(self.files):
                if isinstance(p, StreamEntry) and p.kind == left_entry.kind and p.name == left_entry.name:
                    self.sel = i
                    break
        self.right_dirty = True

    def enter(self):
        if not self.files:
            return
        p = self.files[self.sel]
        if isinstance(p, StreamEntry):
            if p.is_dir():
                self.vpath.append(p)
                self.sel = 0
                self._scan()
                self.right_dirty = True
                # Start resolving the first few tracks as soon as the playlist is opened
                if self.preload_count > 0 and p.kind == "playlist":
                    urls = []
                    for t in self.files[: self.preload_count]:
                        u = self._page_url(t)
                        if u:
                            urls.append(u)
                    if urls:
                        self.stream_cache.enqueue_many(urls, priority_first=True)
            else:
                self.play(p)
            return
        if p.is_dir():
            self.history.append(self.cwd)
            self.cwd = p
            self.sel = 0
            self._scan()
            self.right_dirty = True
        else:
            self.play(p)

    # -------------------------------------------------------------- playback
    def _register_mpv_events(self):
        try:
            @self.mpv.event_callback("end-file")
            def _on_end_file(event):
                # Ignore events that arrive while we are loading another file
                if time.monotonic() < self._switch_until:
                    return
                # Natural EOF only. python-mpv may put reason on the event,
                # event.data, or as a nested dict — accept common shapes.
                reason = None
                try:
                    if isinstance(event, dict):
                        reason = event.get("reason")
                        if reason is None and isinstance(event.get("event"), dict):
                            reason = event["event"].get("reason")
                    else:
                        reason = getattr(event, "reason", None)
                        data = getattr(event, "data", None)
                        if reason is None and data is not None:
                            reason = getattr(data, "reason", None)
                            if reason is None and isinstance(data, dict):
                                reason = data.get("reason")
                except Exception:
                    reason = None
                # 0 / eof = natural end. Also accept missing reason only if the
                # track has been playing for a while (see _check_track_end).
                if reason in (0, "eof", "EOF", None):
                    # Require the current track to have actually started
                    if time.monotonic() - self._play_started_at > 1.0:
                        self._track_ended = True

            @self.mpv.event_callback("file-loaded")
            def _on_file_loaded(event):
                # Safe point to apply resume seek
                if self._pending_resume is not None:
                    pos = self._pending_resume
                    self._pending_resume = None
                    try:
                        self.mpv.seek(pos, reference="absolute")
                    except Exception:
                        pass

            @self.mpv.event_callback("end-file")
            def _on_end_file_error(event):
                # A stream that cannot be opened (private/removed video, yt-dlp problem...)
                if isinstance(self.playing, StreamEntry) and _end_reason(event) in (4, "error", "ERROR"):
                    self._track_error = True

            @self.mpv.event_callback("file-loaded")
            def _on_stream_loaded(event):
                self._stream_fail = 0
                if isinstance(self.playing, StreamEntry):
                    self._meta_pending = True
        except Exception:
            pass

    def play(self, path: Path):
        # Persist position of the track we're leaving (while it's still loaded)
        if self.playing and self.playing.resolve() != path.resolve():
            self._save_position(force=True)

        # Ignore end-file events for a short window (covers async stop of old file)
        self._switch_until = time.monotonic() + 1.5
        self._track_ended = False
        self._play_started_at = time.monotonic()
        self._last_pos_save = time.monotonic()

        self.playing = path
        self._track_error = False
        if isinstance(path, StreamEntry):
            self.meta = stream_metadata(path)
            self.cover_img = None               # the thumbnail arrives from a background thread
            if self.enable_cover:
                self._start_cover_fetch(path)
        else:
            self.meta = get_metadata(path)
            self.cover_img = extract_cover(path) if self.enable_cover else None
        self._cover_cache = (None, None)
        self._pending_resume = None

        key = str(path.resolve())
        entry = self.play_history.get(key)
        if self.resume_enabled and entry:
            try:
                pos = float(entry.get("last_position") or 0)
                # Only resume if we stopped more than a couple seconds in and
                # not near the very end (so finished tracks start over)
                dur = float(self.meta.get("duration") or 0)
                if pos > 2.0 and (not dur or pos < dur - 3.0):
                    self._pending_resume = pos
            except (TypeError, ValueError):
                pass

        # Prefer a pre-resolved direct stream URL (skips the ~5 s yt-dlp step)
        play_url = str(path)
        self._playing_direct = False
        self._direct_retry = False
        if isinstance(path, StreamEntry):
            page_url = path.data.get("url") or str(path)
            direct = self.stream_cache.get(page_url)
            if direct:
                play_url = direct
                self._playing_direct = True
            else:
                # resolve the current track first (priority), then upcoming ones
                self.stream_cache.enqueue(page_url, priority=True)
            self._schedule_stream_preload(path)

        try:
            self.mpv.pause = False
        except Exception:
            pass
        self.mpv.play(play_url)
        self.paused = False

        # Record play count after starting
        self._record_play(path)
        self.full_dirty = True

        # Lyrics: reset and start background fetch (if enabled)
        self.lyrics = None
        self._lyrics_key = None
        self.lyrics_scroll = 0
        self.lyrics_scroll_manual = False
        if self.enable_lyrics:
            self._start_lyrics_fetch()

        # Fallback resume seek if file-loaded event is slow/missing
        if self._pending_resume is not None:
            try:
                # small wait so demuxer is ready
                time.sleep(0.05)
                self.mpv.seek(self._pending_resume, reference="absolute")
                self._pending_resume = None
            except Exception:
                pass

    def _page_url(self, entry) -> str:
        if isinstance(entry, StreamEntry):
            return str(entry.data.get("url") or "")
        return ""

    def _schedule_stream_preload(self, current: StreamEntry):
        """Enqueue the next *preload_count* tracks from the same playlist for resolution."""
        if self.preload_count <= 0 or not isinstance(current, StreamEntry):
            return
        tracks = self._autoplay_pool() if self.playing else []
        if not tracks:
            return
        try:
            cur_key = current.resolve()
            idxs = [i for i, p in enumerate(tracks) if p.resolve() == cur_key]
            start = (idxs[0] + 1) % len(tracks) if idxs else 0
        except Exception:
            start = 0
        urls = []
        for i in range(min(self.preload_count, len(tracks))):
            p = tracks[(start + i) % len(tracks)]
            u = self._page_url(p)
            if u and u != self._page_url(current):
                urls.append(u)
        if urls:
            self.stream_cache.enqueue_many(urls, priority_first=True)

    def _record_play(self, path: Path):
        key = str(path.resolve())
        entry = self.play_history.get(key) or {}
        try:
            count = int(entry.get("play_count") or 0)
        except (TypeError, ValueError):
            count = 0
        entry["play_count"] = count + 1
        entry["last_played"] = datetime.now(timezone.utc).isoformat()
        # Do not clobber a previously saved position on re-play
        if "last_position" not in entry:
            entry["last_position"] = 0.0
        if self.meta:
            entry["title"] = self.meta.get("title") or path.stem
            entry["artist"] = self.meta.get("artist") or ""
        self.play_history[key] = entry
        save_play_history(self.play_history)
        update_most_played(
            self.play_history, self.root,
            self.most_played_name, self.most_played_threshold,
        )

    def _save_position(self, force=False):
        if not self.playing:
            return
        # During the switch grace period the old demuxer may already be gone
        if not force and time.monotonic() < self._switch_until:
            return
        try:
            pos = self.mpv.time_pos
            if pos is None:
                return
            pos = float(pos)
        except Exception:
            return
        if pos < 0:
            return
        key = str(self.playing.resolve())
        entry = self.play_history.get(key) or {}
        entry["last_position"] = pos
        if "play_count" not in entry:
            entry["play_count"] = 0
        if "last_played" not in entry:
            entry["last_played"] = datetime.now(timezone.utc).isoformat()
        self.play_history[key] = entry
        save_play_history(self.play_history)
        self._last_pos_save = time.monotonic()

    def _maybe_save_position(self):
        """Periodic position checkpoint while a track is playing."""
        if not self.playing or self.paused:
            return
        if time.monotonic() - self._last_pos_save < 2.0:
            return
        self._save_position()

    def _audio_files_in_cwd(self):
        return [p for p in self.files
                if (isinstance(p, StreamEntry) and p.kind == "track")
                or (not isinstance(p, StreamEntry) and p.is_file() and is_audio(p))]

    def _autoplay_pool(self):
        """Tracks of the folder / playlist the CURRENT track belongs to (not the one being browsed)."""
        cur = self.playing
        if isinstance(cur, StreamEntry):
            return self._playlist_tracks(cur.file) if cur.file else self._audio_files_in_cwd()
        try:
            items = sorted(cur.parent.iterdir(), key=lambda p: (not p.is_dir(), natural_key(p.name)))
            return [p for p in items if p.is_file() and is_audio(p)]
        except Exception:
            return self._audio_files_in_cwd()

    def _play_next(self):
        """Autoplay / shuffle: pick and play the next track in the current folder.

        Sequential mode stops after the last track unless `loop` is on
        (then it wraps to the first). Shuffle always picks another track.
        """
        if not self.autoplay and not self.shuffle:
            return
        tracks = self._autoplay_pool() if self.playing else self._audio_files_in_cwd()
        if not tracks:
            return

        nxt = None
        if self.shuffle:
            def _same(a, b):
                try:
                    if isinstance(a, StreamEntry) or isinstance(b, StreamEntry):
                        return a == b
                    return a.resolve() == b.resolve()
                except Exception:
                    return a == b
            choices = [p for p in tracks if not self.playing or not _same(p, self.playing)]
            if not choices:
                if self.loop:
                    choices = tracks
                else:
                    self.set_status("End of folder", ttl=4)
                    return
            nxt = random.choice(choices)
        else:
            # sequential within the current folder listing
            if self.playing:
                try:
                    idxs = []
                    for i, p in enumerate(tracks):
                        try:
                            if isinstance(self.playing, StreamEntry) or isinstance(p, StreamEntry):
                                if p == self.playing:
                                    idxs.append(i)
                            elif p.resolve() == self.playing.resolve():
                                idxs.append(i)
                        except Exception:
                            if p == self.playing:
                                idxs.append(i)
                    if idxs:
                        next_i = idxs[0] + 1
                        if next_i >= len(tracks):
                            if self.loop:
                                nxt = tracks[0]
                            else:
                                self.set_status("End of folder", ttl=4)
                                return
                        else:
                            nxt = tracks[next_i]
                    else:
                        nxt = tracks[0]
                except Exception:
                    nxt = tracks[0]
            else:
                nxt = tracks[0]

        if nxt:
            # keep selection in sync when possible
            try:
                self.sel = self.files.index(nxt)
            except ValueError:
                pass
            self.play(nxt)

    def toggle_loop(self):
        self.loop = not self.loop
        state = "ON" if self.loop else "OFF"
        self.set_status(f"Loop folder {state}", ttl=3)
        self.full_dirty = True

    def _check_track_end(self):
        if time.monotonic() < self._switch_until:
            return

        if self._track_error:
            self._track_error = False
            self._handle_stream_error()
            return

        # Poll-based detection (reliable even when end-file reason is missing)
        if not self._track_ended and self.playing and not self.paused:
            try:
                pos = self.mpv.time_pos
                dur = self.mpv.duration
                eof = bool(getattr(self.mpv, "eof_reached", False))
                idle = bool(getattr(self.mpv, "idle_active", False))
                pos = float(pos) if pos is not None else 0.0
                dur = float(dur) if dur is not None else float(self.meta.get("duration") or 0)
                playing_long_enough = (time.monotonic() - self._play_started_at) > 1.5
                near_end = dur > 0 and pos >= max(0.0, dur - 1.0)
                if playing_long_enough and (eof or (idle and near_end) or near_end):
                    # Avoid false positives right after seek/resume
                    if pos > 1.0 or eof or idle:
                        self._track_ended = True
            except Exception:
                pass

        if not self._track_ended:
            return
        self._track_ended = False
        # Finished tracks should resume from the start next time
        if self.playing:
            key = str(self.playing.resolve())
            entry = self.play_history.get(key) or {}
            entry["last_position"] = 0.0
            self.play_history[key] = entry
            save_play_history(self.play_history)
        if self.autoplay or self.shuffle:
            self._play_next()

    def _refresh_meta_from_mpv(self):
        if self.playing and self.meta is not None:
            self.meta = enrich_from_mpv(self.mpv, self.meta)
            if isinstance(self.playing, StreamEntry):
                try:
                    codec = self.mpv.audio_codec_name
                    if codec:
                        self.meta["container"] = str(codec).upper()
                except Exception:
                    pass

    def toggle_pause(self):
        if not self.playing:
            return
        self.mpv.pause = not self.mpv.pause
        self.paused = bool(self.mpv.pause)
        if self.paused:
            self._save_position(force=True)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.full_dirty = True

    def seek(self, delta):
        try:
            pos = self.mpv.time_pos or 0
            self.mpv.seek(max(0, pos + delta), reference="absolute")
        except Exception:
            pass

    # ------------------------------------------------------------- streaming
    def set_status(self, text, ttl=None):
        """Short message shown above the help hint. ttl=None keeps it until replaced."""
        self.status = (text, time.monotonic() + ttl if ttl else float("inf"))
        self.right_dirty = True

    def _poll_stream_events(self):
        if self._meta_pending:
            # tags (year, genre...) only exist once mpv has opened the stream
            self._meta_pending = False
            before = _format_track_lines(self.track_template, self.meta or {}, self.playing)
            self._refresh_meta_from_mpv()
            if _format_track_lines(self.track_template, self.meta or {}, self.playing) != before:
                self.full_dirty = True
        if self._stream_dirty:
            self._stream_dirty = False
            if self.vpath:
                self._scan()
            self.right_dirty = True
        st = self.status
        if st and st[1] <= time.monotonic():
            self.status = None
            self.right_dirty = True

    def _start_cover_fetch(self, entry):
        data = dict(entry.data)

        def work():
            img = fetch_thumbnail(data)
            if img is None or self.playing != entry:      # failed, or the user moved on
                return
            if self.square_covers:
                img = center_square(img)
            self.cover_img = img
            self._cover_cache = (None, None)
            self.full_dirty = True

        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------------------- lyrics
    def _start_lyrics_fetch(self):
        """Load from cache or fetch from LiriQo in a background thread."""
        if not self.enable_lyrics or not self.playing or not self.meta:
            return
        title = (self.meta.get("title") or "").strip()
        artist = (self.meta.get("artist") or "").strip()
        if not title or not artist or artist.lower() in ("unknown", ""):
            return
        album = (self.meta.get("album") or "").strip()
        duration = self.meta.get("duration") or 0
        key = _lyrics_cache_key(title, artist, duration)
        self._lyrics_key = key

        # Instant cache hit
        cached = load_cached_lyrics(key)
        if cached is not None:
            self.lyrics = self._apply_romaji(cached)
            if self.lyrics_visible or self.lyrics_fullscreen:
                self.full_dirty = True
            return

        if self._lyrics_fetching:
            return
        self._lyrics_fetching = True
        playing_snapshot = self.playing

        def work():
            try:
                data = fetch_liriqo_lyrics(
                    title, artist, album, duration, preferred_sync=self.lyrics_sync,
                )
                if data is None:
                    # Negative cache so we don't hammer the API every track change
                    data = {
                        "source": "liriqo",
                        "instrumental": False,
                        "synced": False,
                        "has_word_sync": False,
                        "plain": None,
                        "lines": [],
                        "missing": True,
                    }
                save_cached_lyrics(key, data)
                # Only apply if the user is still on the same track
                if self.playing is playing_snapshot and self._lyrics_key == key:
                    self.lyrics = self._apply_romaji(data)
                    if self.lyrics_visible or self.lyrics_fullscreen:
                        self.full_dirty = True
            finally:
                self._lyrics_fetching = False

        threading.Thread(target=work, daemon=True).start()

    def _apply_romaji(self, data: dict) -> dict:
        if not self.lyrics_romaji or not data:
            return data
        if self._romaji_engine is None:
            self._romaji_engine = make_romaji_engine()
            if self._romaji_engine is None:
                # only warn once
                if not getattr(self, "_romaji_warned", False):
                    self._romaji_warned = True
                    self.set_status("Romaji needs: pip install pykakasi", ttl=8)
                return data
        ensure_romaji_on_lyrics(data, self._romaji_engine)
        # Persist romaji into cache so we don't recompute
        if data.get("has_romaji") and self._lyrics_key:
            save_cached_lyrics(self._lyrics_key, data)
        return data

    def toggle_lyrics(self):
        """Toggle the right panel between file list and lyrics. Visualizer stays."""
        if not self.enable_lyrics:
            self.set_status("Lyrics disabled in config (lyrics.enable = false)", ttl=5)
            return
        if self.lyrics_fullscreen:
            self.lyrics_fullscreen = False
        self.lyrics_visible = not self.lyrics_visible
        if self.lyrics_visible:
            # Re-enable autoscroll whenever the panel is opened
            self.lyrics_scroll_manual = False
            self.lyrics_scroll = 0
            if self.lyrics is None and self.playing:
                self._start_lyrics_fetch()
        self._invalidate_lyrics_panel()
        self.full_dirty = True

    def toggle_lyrics_fullscreen(self):
        if not self.enable_lyrics:
            self.set_status("Lyrics disabled in config (lyrics.enable = false)", ttl=5)
            return
        if not self.lyrics_fullscreen_enabled:
            self.set_status("Full-screen lyrics disabled (lyrics.fullscreen = false)", ttl=5)
            return
        self.lyrics_fullscreen = not self.lyrics_fullscreen
        if self.lyrics_fullscreen:
            self.lyrics_visible = True
            self.lyrics_scroll_manual = False
            self.lyrics_scroll = 0
            if self.lyrics is None and self.playing:
                self._start_lyrics_fetch()
        self.full_dirty = True

    def _handle_stream_error(self):
        # If we used a cached direct URL that has expired / failed, drop it and
        # retry once via the original page URL (yt-dlp will re-extract).
        if (isinstance(self.playing, StreamEntry)
                and getattr(self, "_playing_direct", False)
                and not getattr(self, "_direct_retry", False)):
            page_url = self._page_url(self.playing)
            if page_url:
                self.stream_cache.invalidate(page_url)
                self.stream_cache.enqueue(page_url, priority=True)
                self._playing_direct = False
                self._direct_retry = True
                try:
                    self.mpv.play(page_url)
                    return
                except Exception:
                    pass

        name = (self.meta or {}).get("title") or "this track"
        self._stream_fail += 1
        if self._stream_fail >= 5:
            self.set_status("Stopped after 5 failures (check yt-dlp)", ttl=12)
            return
        self.set_status(f"Can't play \u201c{name}\u201d", ttl=8)
        if self.autoplay or self.shuffle:
            self._play_next()

    def add_playlist_prompt(self):
        if self._adding:
            self.set_status("Already adding something...", ttl=4)
            return
        if not shutil.which("yt-dlp"):
            self.set_status("yt-dlp not found - install it to add from YouTube", ttl=8)
            return
        url = self._prompt_url()
        self.full_dirty = True
        if not url:
            return
        if not re.match(r"^https?://", url, re.I):
            self.set_status("That doesn't look like a URL", ttl=8)
            return
        self._adding = True
        self.set_status("Fetching...")
        threading.Thread(target=self._add_playlist_worker, args=(url,), daemon=True).start()

    def _add_playlist_worker(self, url):
        try:
            info = fetch_playlist(url)
            if info.get("single"):
                track = info["tracks"][0]
                if add_single_track(track, self.single_name):
                    self.set_status(f"Added \u201c{track['title']}\u201d to \u201c{self.single_name}\u201d", ttl=8)
                else:
                    self.set_status(f"Already in \u201c{self.single_name}\u201d", ttl=8)
            else:
                save_playlist(info, url)
                self.set_status(f"Added \u201c{info['title']}\u201d ({len(info['tracks'])} tracks)", ttl=8)
            self._stream_dirty = True
        except Exception as e:
            self.set_status(f"Couldn't add: {e}", ttl=12)
        finally:
            self._adding = False

    def _prompt_url(self):
        """Full-screen text box. Returns the typed/pasted text, or None if cancelled."""
        fd = sys.stdin.fileno()
        t = style(self.c_title, bold=True)
        d = style(self.c_file)
        s = style(self.c_sub)
        k = style(self.c_path)
        input_row = 7
        self._screen([
            f"{t}Add playlist{RESET}", "",
            f"{d}Paste a YouTube or YouTube Music playlist or video URL{RESET}",
            f"{s}Playlists are saved in \u201c{self.stream_name}\u201d, single videos in \u201c{self.single_name}\u201d.{RESET}", "",
            "", "",
            f"{s}[Enter] add   [Esc] cancel{RESET}",
        ])

        def draw(text):
            shown = fit_left(text, max(10, term_size().columns - 10))
            self._present(at(input_row, 4, f"{k}> {d}{shown}{RESET}\033[K") + SHOW_CUR,
                          hide_cursor=False)

        dec = codecs.getincrementaldecoder("utf-8")("ignore")
        text, buf, in_paste = "", "", False
        draw(text)
        sys.stdout.write("\033[?2004h")          # bracketed paste: a pasted newline must not submit
        sys.stdout.flush()
        try:
            while self.running:
                r, _, _ = select.select([fd], [], [], 0.2)
                if r:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        return None
                    buf += dec.decode(chunk)
                elif buf == "\x1b":
                    return None                  # a lone Esc = cancel
                else:
                    buf = ""                     # drop an unfinished escape sequence
                    continue

                i, changed = 0, False
                while i < len(buf):
                    ch = buf[i]
                    if ch == "\x1b":
                        if i + 1 >= len(buf):
                            break
                        if buf[i + 1] == "[":
                            j = i + 2
                            while j < len(buf) and not ("@" <= buf[j] <= "~"):
                                j += 1
                            if j >= len(buf):
                                break
                            seq = buf[i + 2:j + 1]
                            if seq == "200~":
                                in_paste = True
                            elif seq == "201~":
                                in_paste = False
                            i = j + 1
                        elif buf[i + 1] == "O":
                            if i + 2 >= len(buf):
                                break
                            i += 3
                        else:
                            i += 2
                        continue
                    i += 1
                    if ch in "\r\n":
                        if in_paste:
                            continue
                        return text.strip()
                    if ch in "\x7f\b":
                        text, changed = text[:-1], True
                    elif ch == "\x15":           # Ctrl+U clears the line
                        text, changed = "", True
                    elif ch == "\x03":
                        return None
                    elif ch >= " ":
                        text, changed = text + ch, True
                buf = buf[i:]
                if changed:
                    draw(text)
        finally:
            sys.stdout.write("\033[?2004l" + HIDE_CUR)
            sys.stdout.flush()
        return None

    # ---------------------------------------------------------------- layout
    def _make_layout(self):
        cols, rows = term_size()
        if cols < 50 or rows < 14:
            return None

        cell_w, cell_h = cell_px()
        margin = max(2, round(cols * 0.042))
        left_w = max(20, round(cols * 0.30))
        right_x0 = max(margin + left_w + 4, round(cols * 0.526))
        right_w = max(10, cols - right_x0 - margin)

        # visualizer bars: fit them exactly to the column width
        gap = self.viz_gap
        if self.viz_bars > 0:
            bw = max(1, (left_w + gap) // self.viz_bars - gap)
            n = min(self.viz_bars, max(1, (left_w + gap) // (bw + gap)))
        else:
            bw = self.viz_bw
            n = max(1, (left_w + gap) // (bw + gap))
        left_w = n * bw + (n - 1) * gap

        # How many text lines the track header will occupy
        header_lines = _format_track_lines(self.track_template, self.meta or {}, self.playing)
        header_h = max(1, len(header_lines))

        # cover area is a square the width of the column, shrunk to leave room for the visualizer
        # header starts at row 2; cover starts after header
        cover_top = 2 + header_h
        cover_rows = max(1, min(rows - cover_top - 4, math.ceil(left_w * cell_w / cell_h)))
        time_row = cover_top + cover_rows
        viz_top = time_row + 1
        avail = rows - 1 - viz_top + 1
        viz_h = min(self.viz_h, avail) if self.viz_h > 0 else avail

        return SimpleNamespace(
            cols=cols, rows=rows, margin=margin,
            left_x=margin + 1, left_w=left_w,
            right_x=right_x0 + 1, right_w=right_w,
            cover_top=cover_top, cover_rows=cover_rows,
            box_w=int(left_w * cell_w), box_h=int(cover_rows * cell_h),
            cell_w=cell_w, cell_h=cell_h,
            time_row=time_row, viz_top=viz_top, viz_h=max(1, viz_h),
            bars_n=n, bar_w=bw, gap=gap,
            list_top=4, list_vis=max(1, rows - 6), help_row=rows - 1,
            header_h=header_h,
        )

    # --------------------------------------------------------------- drawing
    def _present(self, s, hide_cursor=True):
        # Re-hide and park the cursor at 1,1 after each frame. draw_dynamic only
        # rewrites changed viz rows, so without this the cursor stays on the last
        # updated bar and foot paints a small block there that jumps with the music.
        # Pass hide_cursor=False when the URL prompt needs a visible caret.
        if hide_cursor:
            s = s + HIDE_CUR + "\033[H"
        sys.stdout.write(SYNC_ON + s + SYNC_OFF)
        sys.stdout.flush()

    def _resolve_cover_format(self):
        if self.cover_renderer == "off":
            self.cover_format = None
        elif self.cover_renderer == "auto":
            self.cover_format = detect_cover_format()
        else:
            self.cover_format = self.cover_renderer

    def _active_cover_format(self):
        return self.cover_format or ("symbols" if self.cover_renderer == "auto" else self.cover_renderer)

    def _cover_render(self, L):
        """The cover of the current track as terminal output, already positioned."""
        if not (self.enable_cover and self.cover_img):
            return ""
        fmt = self._active_cover_format()
        key = (str(self.playing), fmt, L.left_w, L.cover_rows, L.box_w, L.box_h,
               self.cover_border, self.cover_symbols)
        if self._cover_cache[0] != key:
            res = chafa_render(self.cover_img, fmt, L.left_w, L.cover_rows, L.cell_w, L.cell_h,
                               self.cover_border, spec_rgb(self.c_border), self.cover_symbols)
            self._cover_cache = (key, res)
        res = self._cover_cache[1]
        if not res:
            return ""
        kind, data = res
        if kind == "pixels":
            return at(L.cover_top, L.left_x, data)
        return "".join(at(L.cover_top + i, L.left_x, ln) for i, ln in enumerate(data[:L.cover_rows]))

    def _left_static(self, L):
        out = []
        lines = _format_track_lines(self.track_template, self.meta or {}, self.playing)
        if not self.playing and (not lines or all(not ln.strip() for ln in lines)):
            lines = ["Nothing playing"]

        for i, text in enumerate(lines):
            row = 2 + i
            if i == 0:
                st = style(self.c_title, bold=self.bold_title)
            else:
                st = style(self.c_sub, bold=self.bold_subtitle)
            out.append(at(row, L.left_x, st + fit(text, L.left_w) + RESET))

        cover = self._cover_render(L)
        if cover:
            out.append(cover)
        return "".join(out)

    def _right_panel(self, L):
        x, w = L.right_x, L.right_w
        out = []

        # current path
        if self.vpath:
            rel = "/".join(e.name for e in self.vpath) + "/"
        else:
            home = str(Path.home())
            rel = str(self.cwd)
            if rel == home or rel.startswith(home + os.sep):
                rel = "~" + rel[len(home):]
            if not rel.endswith("/"):
                rel += "/"
        out.append(at(2, x, style(self.c_path, bold=self.bold_path) + center(fit_left(rel, w), w) + RESET))

        # back entry
        if self.can_go_up():
            out.append(at(3, x, style(self.c_back) + center(f"{UP_ICON} back to previous directory", w) + RESET))
        else:
            out.append(at(3, x, " " * w))

        # list
        vis = L.list_vis
        start = max(0, min(self.sel - vis // 2, len(self.files) - vis))
        rows_out = {}
        for i in range(start, min(len(self.files), start + vis)):
            p = self.files[i]
            name = p.name + ("/" if p.is_dir() else "")
            name = fit(name, w - 2)
            is_sel = (i == self.sel)
            is_play = bool(self.playing) and (p == self.playing or p.resolve() == self.playing.resolve())

            if is_sel:
                body = style(self.c_sel_fg, self.c_sel_bg, bold=True) + f" {name} " + RESET
                used = cw(name) + 2
            else:
                fg = self.c_play if is_play else (self.c_special if self._is_special(p) else self.c_file)
                st = style(fg, bold=self.bold_file)
                body = st + f" {name}" + RESET
                used = cw(name) + 1
            rows_out[L.list_top + i - start] = body + " " * max(0, w - used)

        if not self.files:
            msg = (f" (no playlists yet - press {self.add_playlist_key.upper()} to add one)"
                   if self.vpath else " (no audio files)")
            rows_out[L.list_top] = style(self.c_sub) + fit(msg, w).ljust(w) + RESET

        for r in range(L.list_top, L.list_top + vis):
            out.append(at(r, x, rows_out.get(r, " " * w)))

        # status line (adding a playlist, errors...) just above the help hint
        st = self.status
        if st and st[1] > time.monotonic():
            msg = fit(st[0], w - 1)
            out.append(at(L.help_row - 1, x, " " * (w - cw(msg)) + style(self.c_sub) + msg + RESET))
        else:
            out.append(at(L.help_row - 1, x, " " * w))

        # bottom-right help hint
        hint = "[Q] quit  [H] help"
        out.append(at(L.help_row, x, " " * (w - cw(hint)) + style(self.c_help, bold=self.bold_help) + hint + RESET))
        return "".join(out)

    def draw_full(self):
        # refine metadata from mpv once the file is open
        self._refresh_meta_from_mpv()
        L = self._make_layout()
        self._layout = L
        self._dyn_cache = {}
        self.full_dirty = False
        self.right_dirty = False
        if L is None:
            self._present(CLEAR + "Terminal too small")
            return

        if self.lyrics_fullscreen and self.enable_lyrics:
            try:
                pos = self.mpv.time_pos or 0
            except Exception:
                pos = 0
            self._present(self._lyrics_fullscreen_panel(L, int(pos * 1000)))
            return

        left = self._left_static(L)          # may take a moment (chafa) - done before touching screen
        if self.lyrics_visible and self.enable_lyrics:
            try:
                pos = self.mpv.time_pos or 0
            except Exception:
                pos = 0
            right = self._lyrics_right_panel(L, int(pos * 1000))
        else:
            right = self._right_panel(L)
        # kitty-protocol images survive a screen clear, so delete them explicitly
        wipe = "\033_Ga=d\033\\" if self._active_cover_format() == "kitty" else ""
        self._present(wipe + CLEAR + left + right)

    def draw_right(self):
        self.right_dirty = False
        if not self._layout:
            return
        if self.lyrics_fullscreen:
            return
        if self.lyrics_visible and self.enable_lyrics:
            try:
                pos = self.mpv.time_pos or 0
            except Exception:
                pos = 0
            self._present(self._lyrics_right_panel(self._layout, int(pos * 1000)))
        else:
            self._present(self._right_panel(self._layout))

    def _viz_rows(self, L):
        n, bw, gap, h = L.bars_n, L.bar_w, L.gap, L.viz_h
        data = resample(self.viz, n)
        mode = self.viz_mode
        levels = [max(0.0, min(100.0, float(v))) / 100.0 * h * 8 for v in data]
        rows = []
        for r in range(h - 1, -1, -1):          # r = row index counted from the bottom
            parts = []
            for lv in levels:
                if mode == "bars":
                    e = int(round(lv)) - r * 8
                    cell = "█" * bw if e >= 8 else (BLOCKS[e - 1] * bw if e > 0 else " " * bw)
                else:
                    filled = r < int(round(lv / 8))
                    if not filled:
                        cell = " " * bw
                    elif mode == "blocks":
                        cell = "█" * bw
                    elif mode == "dots":
                        cell = "•" + " " * (bw - 1)
                    else:
                        cell = "│" + " " * (bw - 1)
                parts.append(cell)
            rows.append((" " * gap).join(parts))
        return rows

    def _lyric_segments(self, ln: dict, is_active: bool, pos_ms: int) -> list[tuple[str, str]]:
        """Return (plain_text, sgr_prefix) segments for one lyric entry.

        Always uses the full line text so nothing is hidden. Word/syllable
        timings only control which spans are highlighted.
        """
        text = ln.get("text") or ""
        if not text:
            return [("", style(self.c_sub))]

        dim = style(self.c_sub)
        past = style(self.c_title)
        active = style(self.c_play, bold=True)
        sync = self.lyrics_sync

        if not is_active or sync == "off":
            return [(text, dim)]

        words = ln.get("words") or []
        # syllable mode keeps character/syllable tokens; word mode only when
        # tokens look like real words (character streams are stripped at fetch).
        use_words = bool(words) and (
            sync == "syllable"
            or (sync == "word" and not _tokens_are_chars(words, text))
        )
        if not use_words:
            return [(text, active)]

        # Map each timed word onto a span inside `text` by sequential search.
        # Untimed gaps (and any trailing text) stay visible.
        widx = current_word_index(words, pos_ms)
        segments: list[tuple[str, str]] = []
        cursor = 0
        matched_any = False

        for j, word in enumerate(words):
            raw = word.get("text")
            if raw is None:
                continue
            token = str(raw)
            # Prefer the raw token (may include trailing space); fall back to stripped
            candidates = [token]
            stripped = token.strip()
            if stripped and stripped != token:
                candidates.append(stripped)
            pos = -1
            matched = ""
            for cand in candidates:
                if not cand:
                    continue
                pos = text.find(cand, cursor)
                if pos < 0:
                    pos = text.lower().find(cand.lower(), cursor)
                if pos >= 0:
                    matched = text[pos:pos + len(cand)]
                    break
            if pos < 0 or not matched:
                continue
            matched_any = True
            if pos > cursor:
                # Gap between timed words — dim (or past if we've already passed it)
                gap_style = past if j <= widx else dim
                segments.append((text[cursor:pos], gap_style if is_active else dim))
            if j == widx:
                sgr = active
            elif j < widx:
                sgr = past
            else:
                sgr = dim
            segments.append((matched, sgr))
            cursor = pos + len(matched)

        if cursor < len(text):
            tail_style = past if (matched_any and widx >= 0 and widx >= len(words) - 1) else dim
            # If we're still mid-line and the active word is in the middle, tail is future
            if matched_any and 0 <= widx < len(words) - 1:
                tail_style = dim
            segments.append((text[cursor:], tail_style))

        if not segments:
            # Mapping failed entirely — fall back to whole-line highlight
            return [(text, active)]
        return segments

    def _lyric_entry_rows(self, ln: dict, is_active: bool, pos_ms: int, w: int, show_romaji: bool) -> list[str]:
        """Render one lyric entry into one or more display rows of exact width w."""
        segments = self._lyric_segments(ln, is_active, pos_ms)
        rows = _style_wrap(segments, w)

        if show_romaji:
            romaji = (ln.get("romaji") or "").strip()
            if romaji:
                r_st = style(self.c_play) if is_active and self.lyrics_sync != "off" else style(self.c_sub)
                rows.extend(_style_wrap([(romaji, r_st)], w))
        return rows or [pad_to_width("", w)]

    def _lyrics_rows(self, h: int, w: int, pos_ms: int) -> list[str]:
        """Build styled lyric lines for a panel of height h and width w.

        Long lines wrap with a trailing '-' on the continued row. Word/syllable
        highlight never inserts extra spaces (no artificial widening). Output
        rows are hard-clipped to exactly `w` cells so nothing spills into the
        cover column. Autoscroll keeps the active entry visible through the
        end of the song; manual scroll (↑/↓ while lyrics are open) overrides.
        """
        empty = [" " * w] * h
        data = self.lyrics
        if not data:
            msg = "Fetching lyrics…" if self._lyrics_fetching else "No lyrics"
            return [pad_to_width(style(self.c_sub) + center(msg, w) + RESET, w)] + empty[1:]

        if data.get("instrumental") or data.get("missing"):
            msg = "Instrumental" if data.get("instrumental") else "No lyrics found"
            return [pad_to_width(style(self.c_sub) + center(msg, w) + RESET, w)] + empty[1:]

        lines = data.get("lines") or []
        show_romaji = self.lyrics_romaji and any(ln.get("romaji") for ln in lines)

        if not lines:
            plain = (data.get("plain") or "").strip().splitlines()
            if not plain:
                return [pad_to_width(style(self.c_sub) + center("No synced lyrics", w) + RESET, w)] + empty[1:]
            lines = [{"start_ms": 0, "text": p, "words": None} for p in plain]

        # Build the full display buffer with a map of entry → row range
        sync_off = self.lyrics_sync == "off" or not data.get("synced")
        idx = -1 if sync_off else current_lyric_index(lines, pos_ms)

        all_rows: list[str] = []
        entry_ranges: list[tuple[int, int, int]] = []  # (entry_i, row_start, row_end)
        for i, ln in enumerate(lines):
            is_active = (i == idx)
            chunk = self._lyric_entry_rows(ln, is_active, pos_ms, w, show_romaji)
            r0 = len(all_rows)
            all_rows.extend(chunk)
            entry_ranges.append((i, r0, len(all_rows)))

        total = len(all_rows)
        if total == 0:
            return empty

        # --- window selection (autoscroll or manual) ---
        max_scroll = max(0, total - h)
        # Manual scroll is temporary: after a short idle, resume following the active line
        if self.lyrics_scroll_manual and time.monotonic() > self._lyrics_scroll_until:
            self.lyrics_scroll_manual = False
        if self.lyrics_scroll_manual:
            scroll = max(0, min(self.lyrics_scroll, max_scroll))
            self.lyrics_scroll = scroll
        else:
            # Keep the active entry visible. Prefer it in the lower third so
            # upcoming lines still show; when near the end, pin to the bottom.
            if idx < 0 or not entry_ranges:
                scroll = 0
            else:
                _, a0, a1 = entry_ranges[min(idx, len(entry_ranges) - 1)]
                active_h = max(1, a1 - a0)
                # Target: active block ends near 2/3 of the viewport
                target_end = min(total, a1 + max(0, (h - active_h) // 3))
                scroll = max(0, target_end - h)
                # Always include the active block start
                if a0 < scroll:
                    scroll = a0
                if a1 > scroll + h:
                    scroll = max(0, a1 - h)
                # Pin to end when the active entry is among the last ones
                if a1 >= total - 1 or idx >= len(lines) - 2:
                    scroll = max_scroll
            scroll = max(0, min(scroll, max_scroll))
            self.lyrics_scroll = scroll

        window = all_rows[scroll:scroll + h]
        while len(window) < h:
            window.append(" " * w)
        # Final safety: every row exactly w cells
        return [pad_to_width(r, w) for r in window[:h]]

    def _lyrics_frame_key(self, pos_ms: int, L) -> tuple:
        """Cheap signature of what the lyrics panel would show.

        Used to skip full rebuild/write when only the visualizer needs a new frame.
        Changes when the active line/word, scroll, layout, status, or lyrics data
        change — not on every millisecond of playback.
        """
        data = self.lyrics
        lines = (data.get("lines") or []) if data else []
        sync_off = self.lyrics_sync == "off" or not (data and data.get("synced"))
        idx = -1 if sync_off or not lines else current_lyric_index(lines, pos_ms)
        widx = -1
        if idx >= 0 and self.lyrics_sync in ("word", "syllable"):
            words = lines[idx].get("words") if idx < len(lines) else None
            if words:
                widx = current_word_index(words, pos_ms)
        st = self.status
        status_on = bool(st and st[1] > time.monotonic())
        status_msg = st[0] if status_on else ""
        return (
            id(data) if data is not None else 0,
            idx,
            widx,
            self.lyrics_scroll,
            self.lyrics_scroll_manual,
            getattr(L, "right_w", 0),
            getattr(L, "list_vis", 0),
            status_on,
            status_msg,
            self.lyrics_romaji,
            self.lyrics_sync,
        )

    def _invalidate_lyrics_panel(self):
        """Force the next draw_dynamic to rebuild the lyrics column."""
        self._lyrics_panel_key = None
        self._lyrics_panel_cache = ""

    def _lyrics_right_panel(self, L, pos_ms: int) -> str:
        """Render lyrics into the right column (same geometry as the file list)."""
        x, w = L.right_x, L.right_w
        out = []
        # Header
        title = (self.meta.get("title") or "Lyrics") if self.meta else "Lyrics"
        out.append(at(2, x, style(self.c_path, bold=self.bold_path) + center(fit(title, w), w) + RESET))
        bits = []
        if self.lyrics_romaji:
            bits.append("romaji")
        sync = self.lyrics_sync
        if self.lyrics and self.lyrics.get("sync_level"):
            # Show effective level when it differs from preference
            eff = self.lyrics.get("sync_level")
            if sync != "off" and eff and eff != sync:
                bits.append(f"{sync}→{eff}")
            else:
                bits.append(sync)
        else:
            bits.append(sync)
        if self.lyrics_scroll_manual:
            bits.append("scroll")
        mode = " · ".join(bits) if bits else "lyrics"
        out.append(at(3, x, style(self.c_sub) + center(f"lyrics · {mode}", w) + RESET))

        # Leave one cell of margin so the terminal never wraps a full-width row
        text_w = max(8, w - 1)
        if self.lyrics_max_width > 0:
            text_w = max(8, min(text_w, self.lyrics_max_width))
        h = L.list_vis
        rows = self._lyrics_rows(h, text_w, pos_ms)
        for i, text in enumerate(rows):
            out.append(at(L.list_top + i, x, text))

        # status
        st = self.status
        if st and st[1] > time.monotonic():
            msg = fit(st[0], w - 1)
            out.append(at(L.help_row - 1, x, " " * (w - cw(msg)) + style(self.c_sub) + msg + RESET))
        else:
            out.append(at(L.help_row - 1, x, " " * w))

        hint = f"[{self.lyrics_key.upper()}] files  [Q] quit  [H] help"
        out.append(at(L.help_row, x, " " * (w - cw(hint)) + style(self.c_help, bold=self.bold_help) + hint + RESET))
        return "".join(out)

    def _lyrics_fullscreen_panel(self, L, pos_ms: int) -> str:
        """Full-screen lyrics only."""
        cols, rows = L.cols, L.rows
        margin = max(2, cols // 10)
        x = margin
        w = max(20, cols - 2 * margin)
        text_w = w
        if self.lyrics_max_width > 0:
            text_w = max(8, min(text_w, self.lyrics_max_width))
        out = [CLEAR]
        title = (self.meta.get("title") or "") if self.meta else ""
        artist = (self.meta.get("artist") or "") if self.meta else ""
        header = f"{title}  ·  {artist}".strip(" ·")
        out.append(at(2, x, style(self.c_title, bold=True) + center(fit(header, w), w) + RESET))
        try:
            pos = self.mpv.time_pos or 0
            dur = self.mpv.duration or 0
        except Exception:
            pos, dur = 0, 0
        dur = dur or (self.meta.get("duration") if self.meta else 0) or 0
        prog = f"{fmt_time(pos)} / {fmt_time(dur)}"
        out.append(at(3, x, style(self.c_prog) + center(prog, w) + RESET))

        h = max(1, rows - 6)
        lyric_rows = self._lyrics_rows(h, text_w, pos_ms)
        for i, text in enumerate(lyric_rows):
            out.append(at(5 + i, x, text))

        fk = self.lyrics_fullscreen_key.upper()
        hint = f"[{fk}] exit full-screen  [{self.lyrics_key.upper()}] side panel  [Q] quit"
        out.append(at(rows - 1, x, " " * (w - cw(hint)) + style(self.c_help) + hint + RESET))
        return "".join(out)

    def draw_dynamic(self):
        """Progress line + visualizer. Lyrics live on the right (or full-screen)."""
        L = self._layout
        if not L:
            return

        # Full-screen lyrics: redraw the whole frame from dynamic path
        if self.lyrics_fullscreen and self.enable_lyrics:
            try:
                pos = self.mpv.time_pos or 0
            except Exception:
                pos = 0
            pos_ms = int(pos * 1000)
            frame = self._lyrics_fullscreen_panel(L, pos_ms)
            # Always present (timestamps change every second)
            self._present(frame)
            return

        try:
            pos = self.mpv.time_pos or 0
            dur = self.mpv.duration or 0
        except Exception:
            pos, dur = 0, 0
        dur = dur or self.meta.get("duration") or 0
        if not self.playing:
            pos, dur = 0, 0
        pct = max(0, min(100, int(round(pos / dur * 100)))) if dur else 0
        prog = f"{fmt_time(pos)} / {fmt_time(dur)} ({pct}%)"

        lines = {L.time_row: style(self.c_prog, bold=self.bold_progress) + center(prog, L.left_w) + RESET}

        # Visualizer always on the left
        if self._cava_alive():
            vstyle = style(self.c_viz)
            for i, text in enumerate(self._viz_rows(L)):
                lines[L.viz_top + i] = vstyle + text + RESET
        else:
            msg = center("visualizer unavailable (is cava installed / configured?)"[:L.left_w], L.left_w)
            for i in range(L.viz_h):
                lines[L.viz_top + i] = (style(self.c_sub) + msg + RESET) if i == 0 else " " * L.left_w

        out = []
        for row, text in lines.items():
            if self._dyn_cache.get(row) != text:
                self._dyn_cache[row] = text
                out.append(at(row, L.left_x, text))

        # Lyrics panel: only rebuild/write when highlight, scroll, or status changes.
        # Rewriting the whole right column at viz_fps was the main cause of stutter.
        if self.lyrics_visible and self.enable_lyrics and not self.lyrics_fullscreen:
            pos_ms = int(pos * 1000)
            key = self._lyrics_frame_key(pos_ms, L)
            if key != self._lyrics_panel_key:
                self._lyrics_panel_key = key
                self._lyrics_panel_cache = self._lyrics_right_panel(L, pos_ms)
                out.append(self._lyrics_panel_cache)

        if out:
            self._present("".join(out))

    # ----------------------------------------------------------- other screens
    def _screen(self, lines):
        out = [CLEAR]
        for i, line in enumerate(lines):
            out.append(at(2 + i, 4, line))
        self._present("".join(out))

    def help_screen(self):
        t = style(self.c_title, bold=True)
        k = style(self.c_path)
        d = style(self.c_file)
        s = style(self.c_sub)
        sk = self.shuffle_key.upper()
        yk = self.add_playlist_key.upper()
        rk = self.loop_key.upper()
        lk = self.lyrics_key.upper()
        fk = self.lyrics_fullscreen_key.upper()
        shuffle_state = "ON" if self.shuffle else "OFF"
        loop_state = "ON" if self.loop else "OFF"
        lyrics_state = "lyrics" if self.lyrics_visible else "files"
        fs_state = "ON" if self.lyrics_fullscreen else "OFF"
        rows = [
            f"{t}Keybinds{RESET}", "",
            f"{k}↑ / ↓      {d}Move selection{RESET}",
            f"{k}Enter      {d}Play file / open folder{RESET}",
            f"{k}← / →      {d}Seek ±{self.seek_sec}s{RESET}",
            f"{k}Space      {d}Pause / resume{RESET}",
            f"{k}Backspace  {d}Previous directory{RESET}",
            f"{k}{sk}          {d}Toggle shuffle (now {shuffle_state}){RESET}",
            f"{k}{rk}          {d}Toggle loop folder (now {loop_state}){RESET}",
            f"{k}{yk}          {d}Add a YouTube / YT Music playlist or video (paste URL){RESET}",
            f"{k}{lk}          {d}Toggle right panel: files ↔ lyrics (now {lyrics_state}){RESET}",
            f"{k}{fk}          {d}Full-screen lyrics (now {fs_state}; needs lyrics.fullscreen=true){RESET}",
            f"{k}↑ / ↓      {d}Scroll lyrics when the lyrics panel is open{RESET}",
            f"{k}Ctrl+C     {d}Copy lyrics to clipboard (when lyrics panel is open){RESET}",
            f"{k}Ctrl+V     {d}Paste lyrics from clipboard (overrides API / cache){RESET}",
            f"{k}Delete     {d}Delete cached lyrics for this track (confirm Y/N){RESET}",
            f"{k}I          {d}Track info{RESET}",
            f"{k}H          {d}This help{RESET}",
            f"{k}Q          {d}Quit{RESET}", "",
            f"{t}Config{RESET}", "",
            f"{d}{CONFIG_FILE}{RESET}", "",
            f"{s}Colors        #rrggbb or 0-255",
            f"track_display  template with {{title}} {{artist}} … and \\n",
            f"title_size / subtitle_size / …   large | normal",
            f"autoplay / shuffle / loop / resume     true | false",
            f"most_played_threshold / name    Most Played folder",
            f"lyrics.enable / toggle          timed lyrics (L swaps right panel)",
            f"lyrics.romaji                   Japanese → romaji (needs pykakasi)",
            f"lyrics.sync    syllable | word | line | off   (default: word)",
            f"lyrics.copy_timestamps          Ctrl+C includes [mm:ss] stamps",
            f"lyrics.fullscreen / key         full-screen lyrics mode",
            f"keybinds.shuffle / loop         keys to toggle shuffle / loop",
            f"playlists_name / add_playlist  stream folder name / key to add",
            f"preload_count / preload_ttl   upcoming tracks to pre-resolve",
            f"preload_disk_cache            keep resolved URLs across restarts",
            f"cover_renderer  auto | sixel | kitty | iterm | symbols | off",
            f"viz_mode      bars | blocks | dots | thin",
            f"viz_bars / viz_height   0 = automatic",
            f"viz_fps       lower = less CPU{RESET}", "",
            f"{s}Press any key…{RESET}",
        ]
        self._screen(rows)
        self._wait_key()
        self.full_dirty = True

    def info_screen(self):
        if not self.playing:
            return
        self._refresh_meta_from_mpv()
        m = self.meta
        t = style(self.c_title, bold=True)
        d = style(self.c_file)
        s = style(self.c_sub)

        def row(label, value):
            val = value if value not in (None, "", 0, "Unknown") else "—"
            return f"{d}{label:<12}: {val}{RESET}"

        bitrate_str = m.get("bitrate_label") or "—"
        if m.get("samplerate_label"):
            if bitrate_str != "—":
                bitrate_str = f"{bitrate_str}  ·  {m['samplerate_label']}"
            else:
                bitrate_str = m["samplerate_label"]

        rows = [
            f"{t}Track Info{RESET}", "",
            row("Title", m.get("title")),
            row("Artist", m.get("artist")),
            row("Album", m.get("album")),
            row("Year", m.get("year")),
            row("Genre", m.get("genre")),
            row("Duration", fmt_time(m.get("duration", 0))),
            row("Container", m.get("container")),
            row("Channels", m.get("channels_label")),
            row("Bitrate", bitrate_str),
            row("Path", str(self.playing)),
            "",
            f"{s}Press any key…{RESET}",
        ]
        self._screen(rows)
        self._wait_key()
        self.full_dirty = True

    def _wait_key(self):
        fd = sys.stdin.fileno()
        select.select([fd], [], [])
        os.read(fd, 64)

    # ----------------------------------------------------------------- input
    @staticmethod
    def _parse_keys(data: bytes):
        text = data.decode("utf-8", "ignore")
        csi = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
               "1~": "home", "7~": "home", "4~": "end", "8~": "end", "5~": "pgup", "6~": "pgdn",
               "3~": "delete"}
        keys, i = [], 0
        while i < len(text):
            ch = text[i]
            if ch == "\x1b":
                if i + 1 < len(text) and text[i + 1] in "[O":
                    j = i + 2
                    while j < len(text) and not ("@" <= text[j] <= "~"):
                        j += 1
                    keys.append(csi.get(text[i + 2:j + 1], ""))
                    i = j + 1
                else:
                    keys.append("esc")
                    i += 1
                continue
            keys.append({"\r": "enter", "\n": "enter", " ": "space",
                         "\x7f": "backspace", "\b": "backspace",
                         "\x03": "ctrl+c", "\x16": "ctrl+v"}.get(ch, ch))
            i += 1
        return keys

    def _lyrics_scroll_by(self, delta: int):
        """Manual scroll while the lyrics panel is open. Pauses autoscroll briefly."""
        self.lyrics_scroll_manual = True
        self._lyrics_scroll_until = time.monotonic() + 4.0  # resume follow after idle
        self.lyrics_scroll = max(0, self.lyrics_scroll + delta)
        self._invalidate_lyrics_panel()
        self.right_dirty = True
        if self.lyrics_fullscreen:
            self.full_dirty = True

    def _copy_lyrics(self):
        """Copy current lyrics to the clipboard (Ctrl+C while lyrics are open)."""
        data = self.lyrics
        if not data or data.get("missing") or data.get("instrumental"):
            self.set_status("No lyrics to copy", ttl=3)
            return
        lines = data.get("lines") or []
        chunks = []
        if lines:
            for ln in lines:
                text = (ln.get("text") or "").strip()
                if not text:
                    continue
                if self.lyrics_copy_timestamps and ln.get("start_ms") is not None:
                    ms = int(ln["start_ms"])
                    m, s = divmod(ms // 1000, 60)
                    chunks.append(f"[{m:02d}:{s:02d}] {text}")
                else:
                    chunks.append(text)
        elif data.get("plain"):
            chunks = [data["plain"].strip()]
        body = "\n".join(chunks).strip()
        if not body:
            self.set_status("No lyrics to copy", ttl=3)
            return
        ok = _clipboard_copy(body)
        if ok:
            kind = "with timestamps" if self.lyrics_copy_timestamps else "plain"
            self.set_status(f"Lyrics copied ({kind})", ttl=3)
        else:
            self.set_status("Copy failed — install wl-copy or xclip", ttl=5)

    def _paste_lyrics(self):
        """Replace current track lyrics with clipboard text (Ctrl+V while lyrics open)."""
        if not self.enable_lyrics:
            return
        if not self.playing or not self._lyrics_key:
            self.set_status("Play a track first to paste lyrics", ttl=4)
            return
        raw = _clipboard_paste()
        if raw is None:
            self.set_status("Clipboard empty / unavailable (wl-paste or xclip)", ttl=5)
            return
        data = parse_lyrics_text(raw)
        if not data:
            # YAML paste needs PyYAML; detect so the status is useful
            looks_yaml = bool(re.search(
                r"(?m)^(version|metadata|lines|plain)\s*:",
                str(raw),
            ))
            if looks_yaml:
                try:
                    import yaml  # noqa: F401
                except ImportError:
                    self.set_status("YAML lyrics need: pip install pyyaml", ttl=6)
                    return
            self.set_status("Clipboard has no usable lyrics", ttl=4)
            return
        data = self._apply_romaji(data)
        save_cached_lyrics(self._lyrics_key, data)
        self.lyrics = data
        self.lyrics_scroll = 0
        self.lyrics_scroll_manual = False
        self._invalidate_lyrics_panel()
        level = data.get("sync_level") or "plain"
        n = len(data.get("lines") or [])
        self.set_status(f"Lyrics pasted ({n} lines, {level})", ttl=4)
        self.right_dirty = True
        if self.lyrics_fullscreen:
            self.full_dirty = True

    def _confirm_yes_no(self, title: str, detail: str = "") -> bool:
        """Blocking Y/N prompt. Returns True for yes."""
        fd = sys.stdin.fileno()
        t = style(self.c_title, bold=True)
        d = style(self.c_file)
        s = style(self.c_sub)
        rows = [f"{t}{title}{RESET}", ""]
        if detail:
            rows.append(f"{d}{detail}{RESET}")
            rows.append("")
        rows.append(f"{s}[Y] yes    [N] no / Esc{RESET}")
        self._screen(rows)
        try:
            while self.running:
                r, _, _ = select.select([fd], [], [], 0.3)
                if not r:
                    continue
                for k in self._parse_keys(os.read(fd, 64)):
                    if k in ("y", "Y"):
                        return True
                    if k in ("n", "N", "esc", "q", "Q"):
                        return False
        finally:
            self.full_dirty = True
        return False

    def _delete_lyrics(self):
        """Delete cached lyrics for the current track (Del while lyrics open)."""
        if not self.enable_lyrics:
            return
        if not self.playing:
            self.set_status("Nothing playing", ttl=3)
            return
        has = bool(
            self.lyrics
            and not self.lyrics.get("missing")
            and (
                self.lyrics.get("lines")
                or self.lyrics.get("plain")
                or self.lyrics.get("instrumental")
            )
        )
        if not has and not (self._lyrics_key and _lyrics_cache_path(self._lyrics_key).is_file()):
            self.set_status("No lyrics to delete", ttl=3)
            return
        title = (self.meta.get("title") if self.meta else None) or "this track"
        ok = self._confirm_yes_no(
            "Delete lyrics?",
            f"Remove cached lyrics for “{fit(str(title), 40)}”",
        )
        if not ok:
            self.set_status("Delete cancelled", ttl=2)
            return
        key = self._lyrics_key
        if key:
            delete_cached_lyrics(key)
        self.lyrics = {
            "source": "user",
            "instrumental": False,
            "synced": False,
            "has_word_sync": False,
            "plain": None,
            "lines": [],
            "missing": True,
        }
        self.lyrics_scroll = 0
        self.lyrics_scroll_manual = False
        self._invalidate_lyrics_panel()
        self.set_status("Lyrics deleted", ttl=3)
        self.right_dirty = True
        if self.lyrics_fullscreen:
            self.full_dirty = True

    def handle_key(self, k):
        n = len(self.files)
        lyrics_nav = (
            self.enable_lyrics
            and (self.lyrics_visible or self.lyrics_fullscreen)
        )
        if k == "up":
            if lyrics_nav:
                self._lyrics_scroll_by(-1)
            else:
                self.sel = max(0, self.sel - 1); self.right_dirty = True
        elif k == "down":
            if lyrics_nav:
                self._lyrics_scroll_by(1)
            else:
                self.sel = min(max(0, n - 1), self.sel + 1); self.right_dirty = True
        elif k == "pgup":
            if lyrics_nav:
                self._lyrics_scroll_by(-10)
            else:
                self.sel = max(0, self.sel - 10); self.right_dirty = True
        elif k == "pgdn":
            if lyrics_nav:
                self._lyrics_scroll_by(10)
            else:
                self.sel = min(max(0, n - 1), self.sel + 10); self.right_dirty = True
        elif k == "home":
            if lyrics_nav:
                self.lyrics_scroll_manual = True
                self._lyrics_scroll_until = time.monotonic() + 4.0
                self.lyrics_scroll = 0
                self.right_dirty = True
                if self.lyrics_fullscreen:
                    self.full_dirty = True
            else:
                self.sel = 0; self.right_dirty = True
        elif k == "end":
            if lyrics_nav:
                self.lyrics_scroll_manual = True
                self._lyrics_scroll_until = time.monotonic() + 4.0
                self.lyrics_scroll = 10**9
                self.right_dirty = True
                if self.lyrics_fullscreen:
                    self.full_dirty = True
            else:
                self.sel = max(0, n - 1); self.right_dirty = True
        elif k == "right":
            self.seek(self.seek_sec)
        elif k == "left":
            self.seek(-self.seek_sec)
        elif k == "enter":
            # File manager is fully suspended while lyrics occupy the right panel
            if not lyrics_nav:
                self.enter()
        elif k == "space":
            self.toggle_pause()
        elif k == "backspace":
            if not lyrics_nav:
                self.go_up()
        elif k in ("q", "Q"):
            self.running = False
        elif k in ("h", "H"):
            self.help_screen()
        elif k in ("i", "I"):
            self.info_screen()
        elif k == "ctrl+c":
            if lyrics_nav:
                self._copy_lyrics()
            else:
                self.running = False
        elif k == "ctrl+v":
            if lyrics_nav:
                self._paste_lyrics()
        elif k == "delete":
            if lyrics_nav:
                self._delete_lyrics()
        elif isinstance(k, str) and len(k) == 1 and k.lower() == self.shuffle_key:
            if not lyrics_nav:
                self.toggle_shuffle()
        elif isinstance(k, str) and len(k) == 1 and k.lower() == self.loop_key:
            if not lyrics_nav:
                self.toggle_loop()
        elif isinstance(k, str) and len(k) == 1 and k.lower() == self.add_playlist_key:
            if not lyrics_nav:
                self.add_playlist_prompt()
        elif isinstance(k, str) and len(k) == 1 and k.lower() == self.lyrics_key:
            self.toggle_lyrics()
        elif isinstance(k, str) and len(k) == 1 and k.lower() == self.lyrics_fullscreen_key:
            self.toggle_lyrics_fullscreen()

    def run(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        if self.enable_cover:
            if chafa_path() is None:
                self.enable_cover = False
                self.set_status("chafa not found - install it to show covers", ttl=12)
            else:
                self._resolve_cover_format()      # chafa probes the terminal: do it before the UI starts
        sys.stdout.write(ALT_ENTER + HIDE_CUR)
        sys.stdout.flush()

        try:
            tty.setcbreak(fd)
            # Deliver Ctrl+C as a normal byte so we can use it to copy lyrics
            # instead of raising SIGINT / KeyboardInterrupt.
            try:
                attrs = termios.tcgetattr(fd)
                attrs[6][termios.VINTR] = b'\x00'
                termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            except Exception:
                pass
            tick = 1.0 / self.viz_fps
            while self.running:
                self._check_track_end()
                self._maybe_save_position()
                self._poll_stream_events()
                if self.full_dirty:
                    self.draw_full()
                elif self.right_dirty:
                    self.draw_right()
                self.draw_dynamic()

                r, _, _ = select.select([fd], [], [], tick)
                if r:
                    for k in self._parse_keys(os.read(fd, 64)):
                        if k:
                            self.handle_key(k)
        finally:
            self._save_position(force=True)
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if self.cava:
                self.cava.terminate()
            if self.cava_cfg:
                try:
                    os.unlink(self.cava_cfg)
                except Exception:
                    pass
            try:
                self.stream_cache.stop()
            except Exception:
                pass
            self.mpv.terminate()
            sys.stdout.write(RESET + SHOW_CUR + ALT_EXIT)
            sys.stdout.flush()


if __name__ == "__main__":
    Player().run()
