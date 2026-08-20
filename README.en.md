# matrix-rain-saver

**Matrix rain as an X11 screensaver and a real screen locker — with headlines the
rain decodes on the fly.**

[Русская версия →](README.md) · [Install & configure →](docs/INSTALL.en.md) ·
[Architecture →](ARCHITECTURE.md)

![The rain decoding a headline](docs/demo.gif)

---

## What this is

Streams of code flow **horizontally, left to right** — and draw a headline as they
pass: a flickering scramble runs ahead of the emerging text, and the settled letters
stay behind in a different colour. The Cyrillic face is **custom-made** in the
Matrix-Code style: a monolinear 123/1024 em stroke, square terminals, and 45° cuts
instead of curves.

The renderer is a port of the [Rezmason/matrix](https://github.com/Rezmason/matrix)
GPGPU pipeline (rain, bloom, palette, MSDF glyphs) from WebGL/regl to Python +
moderngl (OpenGL 3.3 core). The text reveal logic is inspired by
[meanwhile](https://github.com/tomdavenport/meanwhile).

Everything runs **offline**: no process in this project ever touches the network.

## Features

- **One continuous world across all monitors.** Rain streams cross screen borders
  freely: every renderer process deterministically simulates the whole world from a
  shared time base and draws only its own crop. Any number of monitors (auto-detected
  via RandR), mixed orientations included.
- **Headlines from any SQLite database.** Point it at a file, name the columns, and
  the saver shows recent rows from the last N hours, re-reading once an hour. No
  database? It runs on built-in phrases.
- **A real locker** built on [xsecurelock](https://github.com/google/xsecurelock):
  input grabs, crash resistance and **system password verification through PAM** —
  with our looks: full-screen rain and a `SYSTEM FAILURE` dialog.
- **Careful typography.** Long headlines are split into two balanced lines at a word
  boundary; a phrase never breaks across monitors and never appears on a part of the
  screen the rain has not covered yet.
- **Film-grade bloom** — highpass → blur pyramid → composite; palettes
  (classic-green, amber, ice-blue, red or your own) and dozens of settings in a
  single commented TOML file.
- **The typeface is yours to redraw**: glyphs are defined as axial skeletons in a
  plain Python file, and rebuilding the atlas is one command.

<table>
<tr>
<td width="50%"><img src="docs/rain.jpg" alt="Rain with phrases"></td>
<td width="50%"><img src="docs/lock-dialog.jpg" alt="Locker dialog"></td>
</tr>
<tr>
<td align="center"><sub>Saver: phrases emerging from the rain</sub></td>
<td align="center"><sub>Locker: password entry, rain frozen</sub></td>
</tr>
</table>

## Requirements

| | |
|---|---|
| OS | Linux + **X11** (any WM; developed on DWM). **Wayland is not supported** |
| GPU | OpenGL 3.3+ — any Mesa/NVIDIA driver from this decade will do |
| Python | 3.11+ |
| Build tools | `cmake`, `g++`, `make`, `curl`, `git` — to build msdfgen (atlas generator) |
| Locker | `xsecurelock` + `xss-lock` from your distribution's repositories |

## Installation

```sh
git clone https://github.com/HelpFreedom/matrix-rain-saver.git
cd matrix-rain-saver
./install.sh
```

`install.sh` is idempotent and does everything for you: creates a venv on Python
3.11+, installs the dependencies, builds msdfgen, downloads the original Matrix
atlas and generates the combined atlas with the Cyrillic glyphs.

For details, including a manual install and idle auto-locking, see
[docs/INSTALL.en.md](docs/INSTALL.en.md).

## Running it

```sh
# Screensaver across all monitors; any key or mouse movement exits
.venv/bin/python -m matrixrain --standalone

# A single window at a given geometry (for debugging and tuning)
.venv/bin/python -m matrixrain --geometry 1920x1080+0+0
```

### The locker

One-time setup:

```sh
sudo apt install xsecurelock xss-lock
sudo install -m 644 xsecurelock/pam.d/xsecurelock /etc/pam.d/xsecurelock
```

Usage:

```sh
bin/matrix-lock            # lock now
bin/matrix-lock --daemon   # prints the xss-lock command for idle auto-locking
```

While the screen is locked, the rain keeps running. **The password dialog appears as
soon as you start typing your password** — the first letter or digit you press opens
the dialog and becomes the first character of the password. Moving the mouse does not
open it (the rain simply continues), and `Esc` closes a dialog that is already open.
While the dialog is up, the rain freezes on every monitor.

<details>
<summary>Why this, and not "press Esc"</summary>

xsecurelock starts the auth module on **any** input, but forwards the waking
keystroke to it only if that keystroke is **printable**. That is xsecurelock's own
safeguard (see `auth_child.c`, function `ContainsNonControl`): control keys — `Esc`
included — are always discarded, and mouse movement produces no characters at all.
So "open the dialog on Esc" is technically impossible on xsecurelock: that `Esc`
never reaches the module. Opening on the first printable key is reliable and, as a
bonus, does not lose the first character of the password.
</details>

Unlocking uses your **system password**: the stock `authproto_pam` helper performs
the check, our code never handles the password itself (and wipes its buffer after
use). A wrong password flashes the frame red.

## Where the headlines come from

By default (`[feed] db = ""`) there is no database and the built-in phrases are
shown — the project works immediately after installation. To show your own records,
point it at **any** SQLite database that has a title column and a timestamp column:

```toml
[feed]
db = "~/.local/share/matrix-rain/headlines.db"
db_table = "posts"
db_title_column = "title"
db_time_column = "created_at"
window_hours = 20        # take rows from the last 20 hours
refresh_seconds = 3600   # re-read once an hour
```

The file is opened **read-only** and never modified. Rows with an empty timestamp are
ignored, duplicates are collapsed, and junk is filtered out by the `exclude` regexes.
No database ships with this project — the data source is entirely yours.

## Configuration

Every setting is documented inline in [config/default.toml](config/default.toml):
palettes, rain speed and density, glyph size, text reveal timings, bloom, locker
behaviour, and per-monitor overrides.

Copy the file and change only the keys you need:

```sh
mkdir -p ~/.config/matrix-rain
cp config/default.toml ~/.config/matrix-rain/config.toml
```

Layers are applied in this order: built-in defaults → your file → the
`[monitor.<name>]` section → command-line flags.

## Redrawing the typeface

Glyphs are axial polylines in [atlas/skeletons.py](atlas/skeletons.py) — plain
coordinates in a unit square. After editing:

```sh
.venv/bin/python atlas/build_atlas.py            # rebuild the atlas
.venv/bin/python atlas/preview.py "HELLO"        # quick preview without GL
```

> Fun fact: the original Matrix-Code set has no digit 6 — ours does.

## Limitations

- **Wayland is not supported** — the project is built entirely on X11 (RandR,
  override-redirect windows, GLX). Porting it would require a separate window layer.
- **Switching to another TTY** (`Ctrl+Alt+F2`) is a trait shared by all X11 lockers:
  the locker itself does not block it. It grants no access to your unlocked session
  (other TTYs require a login), but if you want it forbidden outright, enable
  `DontVTSwitch` in your Xorg configuration.
- No user-space locker is truly unbreakable: a user with root on the machine can do
  anything. This is true of every screen locker.
- There is no automated test suite in the repository — verification was done by hand.

## How it works

A detailed walkthrough lives in [ARCHITECTURE.md](ARCHITECTURE.md) (in Russian): the
render frame graph and every shader, process synchronisation via flock and file
flags, the PAM wire protocol, MSDF atlas generation, and why the locker dialog is
drawn as a child of the saver window (spoiler: the compositor).

## License

[GNU General Public License v3.0 or later](LICENSE).

This project contains ports of MIT-licensed code
([Rezmason/matrix](https://github.com/Rezmason/matrix),
[meanwhile](https://github.com/tomdavenport/meanwhile)); their copyright notices are
preserved in [NOTICE](NOTICE), as the MIT license requires.

The original Matrix MSDF atlas is **not stored** in this repository — it is
downloaded by `atlas/fetch_assets.sh` at install time. The Matrix glyph shapes were
reconstructed by the community from franchise promotional material; keep that in mind
for commercial use.

## Authors

- **Black Triangle** ([@HelpFreedom](https://github.com/HelpFreedom)) — author and
  project owner: requirements, direction, design decisions, acceptance.
- **Claude** (Anthropic) — implementation: the render pipeline port, window layer,
  Cyrillic atlas generator, locker and documentation.
