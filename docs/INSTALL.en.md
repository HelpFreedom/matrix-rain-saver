# Installation and configuration

The detailed guide. For the short version see the [README](../README.en.md).
[Русская версия →](INSTALL.md)

---

## 1. Requirements

| Component | Requirement | Why |
|---|---|---|
| OS | Linux with **X11** | The window layer is built on Xlib/RandR/GLX |
| Server | Any WM, or none | Windows are `override-redirect`, so the WM leaves them alone |
| GPU | OpenGL **3.3 core** | The whole renderer is shader-based |
| Python | **3.11+** | Uses `tomllib` from the standard library |
| Build tools | `cmake`, `g++`, `make`, `curl`, `git` | To compile msdfgen (the glyph atlas generator) |
| Locker | `xsecurelock`, `xss-lock` | Input grabs and PAM password verification |

> **Wayland is not supported.** The project relies on X11-specific mechanisms
> (override-redirect windows, RandR, GLX, display-wide input grabs).

### Installing system dependencies

**Debian / Ubuntu / Mint:**

```sh
sudo apt update
sudo apt install python3.11 python3.11-venv cmake g++ make curl git \
                 libx11-dev libgl1-mesa-dev
# for the locker:
sudo apt install xsecurelock xss-lock
```

**Fedora:**

```sh
sudo dnf install python3.11 cmake gcc-c++ make curl git \
                 libX11-devel mesa-libGL-devel
sudo dnf install xsecurelock xss-lock
```

**Arch:**

```sh
sudo pacman -S python cmake gcc make curl git libx11 mesa
sudo pacman -S xsecurelock xss-lock
```

### Pre-flight check

```sh
python3 --version              # needs to be 3.11 or newer
glxinfo -B | grep "OpenGL core profile version"   # needs 3.3+
echo $XDG_SESSION_TYPE         # must be x11, not wayland
```

---

## 2. Quick install

```sh
git clone https://github.com/HelpFreedom/matrix-rain-saver.git
cd matrix-rain-saver
./install.sh
```

The script is idempotent — running it again breaks nothing.

### What `install.sh` does

1. **Finds Python 3.11+** — tries `python3.13`, `python3.12`, `python3.11`, then the
   system `python3` if it is new enough.
2. **Checks** for `cmake`, `g++`, `make`, `curl`, `git` and tells you the install
   command if something is missing.
3. **Creates a venv** in `.venv/` and installs `requirements.txt`
   (moderngl, numpy, python-xlib, Pillow, wcwidth).
4. **Builds msdfgen** into `build/` in core-only mode, without Skia or FreeType
   (the project only needs MSDF generation from contour descriptions).
5. **Downloads** the original Matrix MSDF atlas from
   [Rezmason/matrix](https://github.com/Rezmason/matrix) into `assets/` — it is not
   stored in this repository.
6. **Generates** the combined atlas `assets/atlas_combined.png`: the original Matrix
   glyphs plus the generated Cyrillic ones.

### Verifying the install

```sh
.venv/bin/python -m matrixrain --geometry 800x600+100+100 --timeout 10
```

An 800×600 window with rain should appear and close after 10 seconds.

---

## 3. Manual installation

If `install.sh` does not fit your setup (unusual distribution, your own msdfgen,
offline machine):

```sh
# 1. venv and dependencies
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. msdfgen (core-only) — skip if you already have it
git clone --depth 1 https://github.com/Chlumsky/msdfgen.git build/msdfgen-src
cmake -S build/msdfgen-src -B build/msdfgen-build \
      -DCMAKE_BUILD_TYPE=Release -DMSDFGEN_CORE_ONLY=ON \
      -DMSDFGEN_BUILD_STANDALONE=ON -DMSDFGEN_USE_VCPKG=OFF \
      -DMSDFGEN_USE_SKIA=OFF -DMSDFGEN_DISABLE_SVG=ON
cmake --build build/msdfgen-build -j$(nproc)
mkdir -p build/msdfgen/bin
cp $(find build/msdfgen-build -name msdfgen -type f -perm -u+x | head -1) build/msdfgen/bin/

# 3. The original atlas
bash atlas/fetch_assets.sh

# 4. The combined atlas with Cyrillic
.venv/bin/python atlas/build_atlas.py
```

The project also runs without the combined atlas — the rain falls using the original
Matrix glyphs, but there is nothing to render Cyrillic headlines with.

---

## 4. Running the screensaver

```sh
# All monitors; any key or noticeable mouse movement exits
.venv/bin/python -m matrixrain --standalone

# A single window at a given geometry — handy while tuning settings
.venv/bin/python -m matrixrain --geometry 1920x1080+0+0

# Exit automatically after N seconds (for testing)
.venv/bin/python -m matrixrain --standalone --timeout 30
```

### All flags

| Flag | Purpose |
|---|---|
| `--standalone` | Supervisor: one renderer process per monitor, exits on any input |
| `--geometry WxH+X+Y` | A single window at the given geometry |
| `--embed-window ID` | Draw inside a foreign window (this is how the xsecurelock saver module runs) |
| `--config PATH` | Use a specific configuration file |
| `--monitor NAME` | RandR monitor name, selecting the `[monitor.<name>]` section |
| `--timeout N` | Exit after N seconds |

### Idle autostart (without locking)

```sh
xset s 600      # treat 10 minutes of inactivity as idle
xss-lock -- /full/path/matrix-rain-saver/.venv/bin/python -m matrixrain --standalone
```

Add both lines to `~/.xinitrc`, `~/.xprofile` or your WM's autostart.

---

## 5. The locker

### One-time setup

```sh
# 1. xsecurelock itself
sudo apt install xsecurelock xss-lock

# 2. The PAM service that allows unlocking with your system password
sudo install -m 644 xsecurelock/pam.d/xsecurelock /etc/pam.d/xsecurelock
```

The PAM service file is two lines, `@include common-auth` and
`@include common-account`: it delegates to the same system stack that normal login
uses. The project stores no passwords of its own.

> On Fedora/Arch the included files have different names (`system-auth` instead of
> `common-auth`). Edit `/etc/pam.d/xsecurelock` accordingly.

### Locking

```sh
bin/matrix-lock            # lock right now
bin/matrix-lock --daemon   # prints the commands for idle auto-locking
```

### What it looks like in use

1. The screen locks and rain runs on every monitor.
2. Moving the mouse changes nothing — the rain simply continues.
3. **The moment you start typing your password**, the `SYSTEM FAILURE` dialog
   appears; the first key you pressed already counts as the first character of the
   password. The rain freezes.
4. `Enter` submits the password. A wrong one flashes the frame red and clears input.
5. `Esc` closes the dialog and returns to the rain (the screen stays locked).
6. If you type nothing for 45 seconds (`[lock] idle_timeout`), the dialog never
   appears and everything returns to the rain.

### Idle auto-locking

```sh
xset s 600
xss-lock -- /full/path/matrix-rain-saver/bin/matrix-lock
```

Use `bin/matrix-lock`, not `xsecurelock` directly: the script sets environment
variables without which the behaviour differs.

---

## 6. Configuration

```sh
mkdir -p ~/.config/matrix-rain
cp config/default.toml ~/.config/matrix-rain/config.toml
```

Your file is merged on top of the built-in defaults, so you may keep only the keys
you changed. Layer order:

```
built-in defaults  →  ~/.config/matrix-rain/config.toml  →  [monitor.<name>]  →  CLI flags
```

### Common tweaks

**Classic vertical rain:**

```toml
[rain]
direction = "vertical"
```

**Bigger/smaller glyphs** (this is the "font size"):

```toml
[glyphs]
cell_size = 26     # 20 pixels per cell by default
```

**A different palette:**

```toml
[palette]
preset = "amber"   # classic-green | amber | ice-blue | red | custom
```

**Your own colours:**

```toml
[palette]
preset = "custom"
text_color = [0.2, 0.9, 1.0]      # colour of settled headlines

[palette.custom]
stops = [                          # rain brightness gradient: [position, R, G, B]
    [0.00, 0.0, 0.0, 0.0],
    [0.50, 0.1, 0.4, 0.5],
    [1.00, 0.7, 1.0, 1.0],
]
```

**Cyrillic in the rain itself** (not only in headlines):

```toml
[glyphs]
rain_sequence_length = 96   # 57 by default — original Matrix glyphs only
```

**Per-monitor settings** (names as reported by `xrandr`):

```toml
[monitor.DP-2]
cell_size = 16        # smaller glyphs on the portrait monitor
```

**Discrete GPU on hybrid graphics:**

```toml
[display]
env = { DRI_PRIME = "1" }
```

**Low-powered machine:**

```toml
[display]
fps = 30
[bloom]
strength = 0.0     # disable the glow pass entirely
```

---

## 7. Your own headlines from a database

The project reads **any** SQLite database and ships none of its own. It needs a text
column and a timestamp column.

```toml
[feed]
db = "~/.local/share/matrix-rain/headlines.db"
db_table = "posts"
db_title_column = "title"
db_time_column = "created_at"
window_hours = 20          # show rows from the last 20 hours
refresh_seconds = 3600     # re-read the database once an hour
db_time_local = false      # true if timestamps are local time rather than UTC
exclude = ["^Error\\s*\\d"]  # regexes for filtering junk out
```

Creating a small database to try it:

```sh
mkdir -p ~/.local/share/matrix-rain
sqlite3 ~/.local/share/matrix-rain/headlines.db <<'SQL'
CREATE TABLE posts (title TEXT, created_at TEXT);
INSERT INTO posts VALUES ('FIRST HEADLINE',  datetime('now'));
INSERT INTO posts VALUES ('SECOND HEADLINE', datetime('now','-2 hours'));
SQL
```

Data requirements:

- Timestamps must be readable by SQLite's `datetime()` — `2026-08-20 09:15:00` and
  ISO-8601 both work. Rows with an empty timestamp are ignored.
- The database is opened **read-only** and is never modified.
- If it is missing or empty, the `fallback` phrases from the configuration are shown.

---

## 8. Redrawing the typeface

Letter shapes are axial polylines in [`atlas/skeletons.py`](../atlas/skeletons.py):
coordinates in a unit square with `y` growing downwards. Stroke width, cap height and
letter width live in [`atlas/stroke_expand.py`](../atlas/stroke_expand.py).

```sh
# Quick preview without starting GL -> assets/atlas_preview.png
.venv/bin/python atlas/preview.py "PREVIEW 123"

# Rebuild the atlas after your edits
.venv/bin/python atlas/build_atlas.py
```

Add new characters **at the end** of `GLYPH_ORDER` so the indices of existing glyphs
do not shift.

---

## 9. Troubleshooting

### Logs

xsecurelock hides its modules' output, so the wrappers write it to files:

```sh
$XDG_RUNTIME_DIR/matrix-rain-saver.log    # saver module output (the rain)
$XDG_RUNTIME_DIR/matrix-rain-auth.log     # auth module output (password dialog)
$XDG_RUNTIME_DIR/matrix-rain/auth.log     # tracebacks from auth module crashes
```

Usually that means `/run/user/1000/…`.

### Common problems

**`no matching GLXFBConfig` / `failed to create GL 3.3 core context`**
The driver does not provide OpenGL 3.3 core. Check `glxinfo -B`. On hybrid graphics,
try `[display] env = { DRI_PRIME = "1" }`.

**`cannot open X display`**
`DISPLAY` is unset, or you are in a Wayland session. Check `echo $DISPLAY` and
`echo $XDG_SESSION_TYPE`.

**`no monitors reported by RandR`**
The driver does not expose monitors through RandR. Work around it with an explicit
geometry: `--geometry 1920x1080+0+0`.

**Rain runs but no headlines appear**
The combined atlas has not been built — run `.venv/bin/python atlas/build_atlas.py`
and check that `assets/atlas_combined.png` and `assets/atlas.json` exist.

**Locker: `xsecurelock not found`**
`sudo apt install xsecurelock xss-lock`.

**Locker: the password is rejected**
The PAM service is missing, or it includes the wrong file names. Check
`/etc/pam.d/xsecurelock`; on Fedora/Arch replace `common-auth` with `system-auth`.

**Locker: `authproto_pam helper not found`**
The helper lives in a different directory. Find it and point at it explicitly:

```sh
find /usr -name authproto_pam 2>/dev/null
XSECURELOCK_AUTHPROTO_HELPER=/path/to/authproto_pam bin/matrix-lock
```

**The password dialog never appears**
It is not supposed to open from mouse movement or `Esc` — start typing your password
(see the locker section in the [README](../README.en.md)).

---

## 10. Updating and uninstalling

**Updating:**

```sh
git pull
./install.sh     # pulls new dependencies and rebuilds the atlas if needed
```

**Uninstalling:** the project installs nothing outside its own directory except two
optional things:

```sh
rm -rf /path/to/matrix-rain-saver     # the project itself, with venv and build
rm -rf ~/.config/matrix-rain          # your configuration
sudo rm -f /etc/pam.d/xsecurelock     # the locker's PAM service, if no longer needed
```

Temporary files in `$XDG_RUNTIME_DIR/matrix-rain/` disappear on reboot.
