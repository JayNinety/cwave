#!/usr/bin/env bash
# CWave installer — installs dependencies and places `cw` on PATH.
set -euo pipefail

RED=$'\033[1;31m'
GRN=$'\033[1;32m'
YLW=$'\033[1;33m'
CYN=$'\033[1;36m'
DIM=$'\033[2m'
RST=$'\033[0m'

info()  { printf '%s%s%s\n' "$CYN" "$*" "$RST"; }
ok()    { printf '%s%s%s\n' "$GRN" "$*" "$RST"; }
warn()  { printf '%s%s%s\n' "$YLW" "$*" "$RST"; }
err()   { printf '%s%s%s\n' "$RED" "$*" "$RST" >&2; }

need_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      SUDO=(sudo)
    else
      err "This step needs root privileges (sudo not found)."
      exit 1
    fi
  else
    SUDO=()
  fi
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC=""
for candidate in \
  "${SCRIPT_DIR}/cwave.py" \
  "${SCRIPT_DIR}/cwave" \
  "./cwave.py" \
  "./cwave"
do
  if [[ -f "$candidate" ]]; then
    SRC="$(cd -- "$(dirname -- "$candidate")" && pwd)/$(basename -- "$candidate")"
    break
  fi
done

if [[ -z "$SRC" ]]; then
  err "Could not find cwave.py next to this script (or in the current directory)."
  err "Place install.sh and cwave.py in the same folder, then run: bash install.sh"
  exit 1
fi

echo
info "CWave installer"
echo "  source: $SRC"
echo

echo "Which distro are you on?"
echo "  1) Arch Linux"
echo "  2) Debian / Ubuntu / Linux Mint (and derivatives)"
echo "  3) Fedora"
echo "  4) Other"
echo
read -r -p "Choice [1-4]: " DISTRO_CHOICE
echo

install_pip_hint() {
  local pkg="$1"
  warn "  → not in the distro repos (or under a different name)."
  echo "     Install with pip:"
  echo "       pip install --user ${pkg}"
  echo "     (or: python3 -m pip install --user ${pkg})"
}

pkg_available_arch() {
  pacman -Si "$1" &>/dev/null
}

pkg_available_apt() {
  apt-cache show "$1" &>/dev/null 2>&1
}

pkg_available_dnf() {
  dnf info -q "$1" &>/dev/null 2>&1
}

# --------------------------------------------------------------------------- #
#  Other — list only
# --------------------------------------------------------------------------- #
if [[ "$DISTRO_CHOICE" == "4" ]]; then
  cat <<EOF
${CYN}Required dependencies${RST}
  System:
    • mpv          — playback
    • cava         — audio visualizer
    • chafa        — album / track covers
  Python 3.10+ modules:
    • python-mpv   (import name: mpv)
    • mutagen
    • Pillow       (import name: PIL)

${CYN}Optional${RST}
  • yt-dlp
  • pykakasi       — Japanese romaji lyrics
  • PyYAML         — paste YAML timed lyrics (Ctrl+V)
  • wl-clipboard or xclip / xsel — copy / paste lyrics

Install the packages with your distro's package manager, then re-run this
script on Arch / Debian / Fedora, or install the binary manually:

  chmod +x "$SRC"
  ${SUDO:+sudo }cp "$SRC" /usr/local/bin/cw

EOF
  # Still offer to install the binary if they want
  read -r -p "Copy cwave.py to /usr/local/bin/cw now? [y/N]: " COPY_ONLY
  if [[ "${COPY_ONLY,,}" == "y" || "${COPY_ONLY,,}" == "yes" ]]; then
    need_root
    chmod +x "$SRC"
    "${SUDO[@]}" cp "$SRC" /usr/local/bin/cw
    "${SUDO[@]}" chmod 755 /usr/local/bin/cw
    echo
    ok "Installation Succeeded!"
    echo "Run it typing: cw"
    echo "then press Enter."
  else
    info "Skipped binary install. Dependencies listed above."
  fi
  exit 0
fi

need_root

# --------------------------------------------------------------------------- #
#  Required packages per family
# --------------------------------------------------------------------------- #
case "$DISTRO_CHOICE" in
  1)
    info "Installing required packages (Arch)…"
    "${SUDO[@]}" pacman -Sy --needed --noconfirm \
      mpv cava chafa \
      python-mpv python-mutagen python-pillow \
      wl-clipboard
    ;;
  2)
    info "Installing required packages (Debian/Ubuntu/Mint)…"
    "${SUDO[@]}" apt-get update -y
    # Core system tools
    "${SUDO[@]}" apt-get install -y mpv cava chafa
    # Clipboard helpers (best-effort)
    "${SUDO[@]}" apt-get install -y wl-clipboard 2>/dev/null \
      || "${SUDO[@]}" apt-get install -y xclip 2>/dev/null \
      || "${SUDO[@]}" apt-get install -y xsel 2>/dev/null \
      || warn "No clipboard tool installed (wl-clipboard / xclip / xsel). Copy-paste lyrics may be unavailable."

    # Python libs from apt when possible
    APT_PY=()
    for p in python3-mutagen python3-pil; do
      if pkg_available_apt "$p"; then
        APT_PY+=("$p")
      fi
    done
    if ((${#APT_PY[@]})); then
      "${SUDO[@]}" apt-get install -y "${APT_PY[@]}"
    fi

    if pkg_available_apt python3-mpv; then
      "${SUDO[@]}" apt-get install -y python3-mpv
    else
      warn "python3-mpv is not in the default apt repos."
      install_pip_hint "python-mpv"
      echo
      read -r -p "Install python-mpv with pip now? [Y/n]: " PIP_MPV
      if [[ -z "${PIP_MPV}" || "${PIP_MPV,,}" == "y" || "${PIP_MPV,,}" == "yes" ]]; then
        python3 -m pip install --user python-mpv
      fi
    fi

    # mutagen / Pillow fallbacks
    python3 -c "import mutagen" 2>/dev/null || {
      warn "mutagen missing after apt."
      install_pip_hint "mutagen"
      python3 -m pip install --user mutagen || true
    }
    python3 -c "import PIL" 2>/dev/null || {
      warn "Pillow missing after apt."
      install_pip_hint "Pillow"
      python3 -m pip install --user Pillow || true
    }
    ;;
  3)
    info "Installing required packages (Fedora)…"
    "${SUDO[@]}" dnf install -y mpv cava chafa \
      python3-mutagen python3-pillow \
      wl-clipboard || true

    if pkg_available_dnf python3-mpv; then
      "${SUDO[@]}" dnf install -y python3-mpv
    else
      warn "python3-mpv is not in the default Fedora repos."
      install_pip_hint "python-mpv"
      echo
      read -r -p "Install python-mpv with pip now? [Y/n]: " PIP_MPV
      if [[ -z "${PIP_MPV}" || "${PIP_MPV,,}" == "y" || "${PIP_MPV,,}" == "yes" ]]; then
        python3 -m pip install --user python-mpv
      fi
    fi

    # cava sometimes lives in COPR / RPM Fusion — warn if still missing
    if ! command -v cava >/dev/null 2>&1; then
      warn "cava is not installed. Enable RPM Fusion or install from: https://github.com/karlstav/cava"
    fi
    ;;
  *)
    err "Invalid choice."
    exit 1
    ;;
esac

echo
ok "Required dependencies installed (or instructed)."
echo

# --------------------------------------------------------------------------- #
#  Optional: yt-dlp + pykakasi
# --------------------------------------------------------------------------- #
read -r -p "Install optional packages (yt-dlp, pykakasi for romaji)? [y/N]: " OPT_CHOICE
if [[ "${OPT_CHOICE,,}" == "y" || "${OPT_CHOICE,,}" == "yes" ]]; then
  echo
  case "$DISTRO_CHOICE" in
    1)
      # yt-dlp
      if pkg_available_arch yt-dlp; then
        info "Installing yt-dlp…"
        "${SUDO[@]}" pacman -S --needed --noconfirm yt-dlp
      else
        warn "yt-dlp is not in the main repos."
      fi
      # pykakasi
      if pkg_available_arch python-pykakasi; then
        info "Installing python-pykakasi…"
        "${SUDO[@]}" pacman -S --needed --noconfirm python-pykakasi
      else
        warn "python-pykakasi is not in the main repos."
        install_pip_hint "pykakasi"
      fi
      # pyyaml (YAML lyric paste) — quiet optional bonus if present
      if pkg_available_arch python-yaml; then
        "${SUDO[@]}" pacman -S --needed --noconfirm python-yaml || true
      fi
      ;;
    2)
      if pkg_available_apt yt-dlp; then
        info "Installing yt-dlp…"
        "${SUDO[@]}" apt-get install -y yt-dlp
      else
        warn "yt-dlp is not in the main repos."
      fi
      if pkg_available_apt python3-pykakasi; then
        info "Installing python3-pykakasi…"
        "${SUDO[@]}" apt-get install -y python3-pykakasi
      else
        warn "pykakasi is not in the main repos."
        install_pip_hint "pykakasi"
        read -r -p "Install pykakasi with pip now? [y/N]: " PIP_KK
        if [[ "${PIP_KK,,}" == "y" || "${PIP_KK,,}" == "yes" ]]; then
          python3 -m pip install --user pykakasi
        fi
      fi
      if pkg_available_apt python3-yaml; then
        "${SUDO[@]}" apt-get install -y python3-yaml || true
      fi
      ;;
    3)
      if pkg_available_dnf yt-dlp; then
        info "Installing yt-dlp…"
        "${SUDO[@]}" dnf install -y yt-dlp
      else
        warn "yt-dlp is not in the main repos."
      fi
      if pkg_available_dnf python3-pykakasi; then
        info "Installing python3-pykakasi…"
        "${SUDO[@]}" dnf install -y python3-pykakasi
      else
        warn "pykakasi is not in the main repos."
        install_pip_hint "pykakasi"
        read -r -p "Install pykakasi with pip now? [y/N]: " PIP_KK
        if [[ "${PIP_KK,,}" == "y" || "${PIP_KK,,}" == "yes" ]]; then
          python3 -m pip install --user pykakasi
        fi
      fi
      if pkg_available_dnf python3-pyyaml; then
        "${SUDO[@]}" dnf install -y python3-pyyaml || true
      fi
      ;;
  esac
else
  info "Skipped optional packages."
fi

# --------------------------------------------------------------------------- #
#  Install binary
# --------------------------------------------------------------------------- #
echo
info "Installing launcher to /usr/local/bin/cw …"
chmod +x "$SRC"
"${SUDO[@]}" cp "$SRC" /usr/local/bin/cw
"${SUDO[@]}" chmod 755 /usr/local/bin/cw

echo
ok "Installation Succeeded!"
echo "Run it typing: cw"
echo "and press Enter."
echo
