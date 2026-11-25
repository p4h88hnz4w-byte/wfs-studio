# WFS Studio

WFS Studio is a desktop program for your own Wii U backups. It is inspired by [Wii Backup Manager](https://wiibackupmanager.co.uk/), and it is for Mac and Linux. (Sorry PC, Places Traffic Cone on head, your just not part of the group anymore) It is a Python window around the official [wfs-tools](https://github.com/koolkdev/wfs-tools) v1.2.3 wfs-extract, plus a copier for extracted titles and saves. Its intended for Copying a Wii U hard drive into a backup, or into folders [Cemu](https://cemu.info/) can open.

`CHANGELOG.md` is the record of what has been built.

## Run

```bash
cd wfs-studio
source .venv/bin/activate
python -m wfs_studio
```

The first time, create the virtualenv as in Setup below.

## Titles tab

1. Choose the extracted dump, a `usr/title` folder, or one title folder.
2. Scan. Names come from `longname_*` in `meta/meta.xml`. A game, its update, and its DLC that share the same low title id appear on one row. The Kind column lists the parts that are present, and the size is their total. Checking that row selects every part. A demo or a system title stays on its own row. Each row shows the base title's `meta/iconTex.tga` beside the name. The Region column reads the title's region bits: USA is NTSC-U, EUR is PAL (Europe, and Australian consoles, which use the EUR region), and JPN is NTSC-J. USA+EUR means the title is allowed on both. The folder layout is the same for each, and the title id keeps those copies apart. In a code such as `WUP-P-APKE`, the `P` is the package type. The region letter is the `E` in `APKE`. Sizes are measured a few titles at a time and remembered in `cache/title-sizes.json`. Recount sizes measures them again.
3. Download GameTDB, or choose a `wiiutdb.zip` you already have. The zip stays compressed in `cache/wiiutdb.zip`. The app reads `wiiutdb.xml` from inside it. A plain `cache/wiiutdb.txt` is used only when no zip is available. A product code such as `WUP-P-APKE` matches GameTDB id `APKE01`. Banner zip reads `<id>.png` from a cover archive you already have. Without one, disc pictures are saved under `cache/covers/` after a download. If there is no banner and no disc, the pane shows `meta/iconTex.tga` from that title. A disc that arrives later replaces the icon.
4. Check the titles, or use Select all (the button, or Edit → Select all). Select all checks every title, including rows hidden by the filter. Check visible checks only the rows on screen. Checking every title asks where to write an archive: a zip on a Mac, and 7z or a bzip2 tar on Linux. The archive is written after the copy and sits outside the destination folder. A partial selection copies only the checked titles.

Game data copy is on by default. Each title is written to `Title Name [00050000-lowid]/`, and `usr/save` is not included. A grouped row still writes one folder per part, so the update and the DLC stay out of the base game's folder. The window then checks that the destination file count and byte total match the source. Turn the option off to keep the path relative to the scanned folder, for example `usr/title/00050000/101DF400/...`. Files that already exist at the destination with the same size are skipped. A different size is replaced.

The copy shows a progress bar and the path currently being written. Stopping deletes the unfinished temporary file (`.wfs-studio-partial`) and leaves completed files where they are.

## Saves tab

Backs up saves onto this computer in the layout used by [SaveMii](https://github.com/w3irDv/savemii). It does not edit save files, and it does not write into the dump.

1. The source is the folder chosen on the Titles tab. That can be the dump, `usr`, `usr/save`, or one high id such as `usr/save/00050000`.
2. Scan saves. `usr/save/system` is skipped.
3. Check the saves, or press Select all. Edit → Select all does the same thing while this tab is in front. Choosing every save asks where to write an archive: a zip on a Mac, and 7z or a bzip2 tar on Linux.
4. Choose a backup folder and start the backup. The archive is written after the SaveMii folders.

Each save is written to `Title Name [00050000-lowid]/0/` with the profile folders, `common` when the game has it, `savemii_saveinfo.xml`, and `savemiiMeta.json`. The next backup of that title uses slot `1`, then the next free slot through `255`. Check the USB box when the dump came from a USB drive so the metadata says `USB` instead of `NAND`.

To restore on a Wii U, copy that folder to `sd:/wiiu/backups` and use SaveMii there.

## Extract tab

Catalog titles reads `/usr/title` and writes `meta/meta.xml` and `iconTex.tga` into the output folder. Point the Titles tab at that folder to browse the list. It reads an image. An extracted title folder is already decrypted, and this pass does not open it. Start extract runs official `wfs-extract` and writes the dump path you enter. The input stays as it is. Edit → Select all, while this tab is in front, selects the whole log.

The catalog tool is built with `scripts/build-catalog.sh` (or `make catalog`). That script checks out `wfslib` and does not clone vcpkg. On a Mac the build needs Homebrew `cmake`, `boost`, and `cryptopp`. On Linux, GCC 14 is required. On Arch the other build packages are `cmake`, `boost`, and `crypto++`. The built program is `native/wfs-catalog/build/wfs-catalog`.

| Type | Keys | Typical input |
| --- | --- | --- |
| `mlc` | `otp.bin` | MLC backup image |
| `usb` | `otp.bin` and `seeprom.bin` | Wii U USB device or image |
| `plain` | none | A filesystem already decrypted by `wfs-reencryptor` |

Dump path defaults to `/` for a full extract. Recovery mode (`--dump-usr-dir`) only accepts paths inside `/usr`. Catalog titles always reads `/usr/title`, including when recovery mode is on. The extract command includes `--verbose`, which prints `Dumping /path` when each file starts. That line has no byte total, so the progress on this tab is a file count. A catalog prints the same line for `meta.xml` and `iconTex.tga`, then `Titles:` and the count.

SLC and SLCCMPT images are not WFS. This tool cannot open `slc.bin` or `slccmpt.bin`.

## Safety

- Copying and save backup read the source and write only inside the destination you pick. The dump is not changed.
- Extract reads the input image or device and writes only inside the output folder.
- Catalog titles reads `/usr/title` and writes `meta/meta.xml` and `iconTex.tga` inside that same output folder.
- The destination cannot be the source, and it cannot sit inside the source.
- Stopping a copy deletes the unfinished temporary file (`.wfs-studio-partial`) and leaves completed files where they are.
- Ctrl+C in the terminal closes the window and saves the folders you picked. A running copy or extract is stopped. Press it again to stop the process immediately.
- `otp.bin` and `seeprom.bin` are used only as local paths passed to `wfs-extract` and the catalog tool. They stay on your computer.
- `wfs-file-injector` and `wfs-reencryptor` are in the official zip. This program does not run them. Both can change a WFS image.
- SLC and SLCCMPT dumps are not WFS images. `wfs-extract` cannot open `slc.bin` or `slccmpt.bin`.

`cache/settings.json` stores the folders you pick, including key-file paths. It stays in `cache/` on your computer.

## Menu music

The window loops 8bit Bossa by Joth, CC0. The ending plays through, and a 0.3 second join at the start of the track carries the loop back to the opening. File → Menu music turns it off, and that choice is remembered. Closing the window does not wait on the player.

On Linux, File → Audio backend chooses PulseAudio or PipeWire. PulseAudio is the default. The choice is used the next time the window opens. If a PipeWire choice never opens the window, start that one run with `QT_AUDIO_BACKEND=PulseAudio`. The terminal can still print FFmpeg's file banner when the track starts. That line is not a failure.

Menu music is not supported on WSL. The installer still sets `QT_AUDIO_BACKEND=PulseAudio` for that launch, so Qt does not open the distro PipeWire backend, and File → Audio backend stays on that value.

## Crash log

An unexpected error appends a traceback to `cache/wfs-studio.log`. About WFS Studio shows the full path. The same folder holds settings. It is not the shell's working directory: a launch from the Dock or Start Menu has no useful current directory, and a `.app` bundle cannot keep files inside itself.

| How you run it | Log |
| --- | --- |
| This checkout | `cache/wfs-studio.log` in the project |
| Frozen macOS app | `~/Library/Application Support/WFS Studio/cache/wfs-studio.log` |
| Frozen Linux app | `~/.local/share/wfs-studio/cache/wfs-studio.log`, or `$XDG_DATA_HOME/wfs-studio/cache/wfs-studio.log` |
| Frozen Windows app | `%APPDATA%\WFS Studio\cache\wfs-studio.log` |

`WFS_STUDIO_DATA` overrides that folder. The log starts with the version and the system. It keeps about 512 KB, and the previous copy is `wfs-studio.log.1`. It stays on your computer.

## What you need

Each person supplies their own console data. This repository does not include a Wii U drive image, games, `otp.bin`, or `seeprom.bin`.

- Python 3.10 or newer. On this Mac the system Python is 3.9, and Homebrew Python 3.12 works.
- The official `wfs-extract` build for your system. The app downloads v1.2.3 and checks its SHA-256. Those binaries stay in `vendor/` on your machine.
- Your own Wii U backup: an extracted dump with `usr/title/<high-id>/<low-id>/meta/meta.xml`, or an MLC/USB image from your console.
- Your own `otp.bin` for an encrypted MLC or USB image. A USB image also needs your own `seeprom.bin`. The app passes those paths only to `wfs-extract` and the catalog tool on the computer where you run it.

A full USB or MLC extract can be hundreds of gigabytes. Pick a destination with enough free space.

Reading a raw USB device may require an administrator shell. The window shows the exact command so you can run it yourself with the privileges you choose. The app does not request them.

## Setup

Linux can use the installer. It asks for a working directory, an alias, and bash or zsh. The shell you choose is the file it updates: `~/.bashrc` or `~/.zshrc`. The alias starts in that working directory.

```bash
git clone --recurse-submodules https://github.com/p4h88hnz4w-byte/wfs-studio.git
cd wfs-studio
bash install-linux.sh
```

An empty working directory is a shallow clone of this repo plus the `wfs-tools` submodule. `vcpkg` is not downloaded. Git is required only for that clone. Python 3.10 or newer has to be on `PATH` as `python3`. On Debian or Ubuntu that is often `sudo apt install python3 python3-venv python3-pip git`. On Fedora or RHEL it is `sudo dnf install python3 python3-pip git`. On Arch it is `sudo pacman -S python python-pip git`. The script does not use root. Run it again to change the directory, the alias, or the shell file. The rest of that shell file stays.

### Linux dependencies

`requirements.txt` installs PySide6 into the virtualenv. These system libraries are not in that file. The installer checks the library names and, for whatever is missing, prints one `sudo apt install`, `sudo dnf install`, or `sudo pacman -S --needed` line. It does not run that command.

| Library | Debian and Ubuntu | Fedora and RHEL | Arch |
| --- | --- | --- | --- |
| `libxcb-cursor.so.0` | `libxcb-cursor0` | `xcb-util-cursor` | `xcb-util-cursor` |
| `libxkbcommon.so.0` | `libxkbcommon0` | `libxkbcommon` | `libxkbcommon` |
| `libxkbcommon-x11.so.0` | `libxkbcommon-x11-0` | `libxkbcommon-x11` | `libxkbcommon-x11` |
| `libEGL.so.1` | `libegl1` | `libglvnd-egl` | `libglvnd` |
| `libGL.so.1` | `libgl1` | `libglvnd-glx` | `libglvnd` |
| `libfontconfig.so.1` | `libfontconfig1` | `fontconfig` | `fontconfig` |
| `libpulse.so.0` | `libpulse0` | `pulseaudio-libs` | `libpulse` |

`libxcb-cursor.so.0` is linked by Qt's xcb plugin. Without it, an X11 session does not open, and Qt says the library is required from 6.5.0. A Wayland session does not load that library. The installer still asks for it so the X11 path can start. Ubuntu 24.04 can still be missing `libxcb-cursor0` and `python3-venv` on a desktop.

The installer reads the distro before it asks where to install. Omarchy reports itself as `omarchy` and uses the Arch packages. 32-bit x86 is refused. The Linux `wfs-extract` build used here is the x86_64 one. On Ubuntu 24.04 and on Omarchy 4.5.0 the window opened through Wayland with the PulseAudio default, and it closed with the window. Omarchy was Python 3.14 with PySide 6.12.

### Windows, through WSL

On Windows, the window is still this Linux program, running inside WSL2. There is no Windows build.

Supported: Ubuntu 22.04 or newer, Debian 12 or newer, Fedora 39 or newer, and Arch, on WSL2 with WSLg. WSLg is the Windows 11 desktop integration. WSL1 cannot open the window. The distro has to be x86_64, because the official `wfs-extract` build used here is the Linux x86_64 one. 32-bit x86 is refused.

Install Ubuntu or Debian from the Microsoft Store, open that distro, and run:

```bash
git clone --depth 1 https://github.com/p4h88hnz4w-byte/wfs-studio.git
cd wfs-studio
git submodule update --init --depth 1 third_party/wfs-tools
bash install-linux.sh
```

Choose a working directory inside the Linux filesystem, such as the home directory. A path under `/mnt` is a Windows drive, and the virtualenv does not belong there. The installer stops if it sees one.

The installer reads the distro before it asks where to install. Menu music is not supported on WSL. The alias still sets `QT_AUDIO_BACKEND=PulseAudio`, so Qt does not open the distro's PipeWire backend, and `QT_QPA_PLATFORM=xcb`, which is the display path WSLg provides. A missing Windows audio socket does not stop the install.

If the window's libraries are missing, the installer prints one `sudo apt install`, `sudo dnf install`, or `sudo pacman -S --needed` line and stops. It does not run that command.

A checkout on a Mac, or a Linux machine where you want the developer tools, can still be built by hand:

```bash
git clone --recurse-submodules https://github.com/p4h88hnz4w-byte/wfs-studio.git
cd wfs-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
python -m wfs_studio.binaries
python -m wfs_studio
```

`requirements.txt` is the Python package the window needs: PySide6. The Linux system libraries in the table above are separate, and pip does not install them. `requirements-dev.txt` adds pytest and PyInstaller. The same Python lists are the `project.dependencies` and optional extras in `pyproject.toml`.

`third_party/wfs-tools` is a git submodule pinned to upstream tag `v1.2.3` (commit `f5c652e`). Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after a normal clone. The nested `wfslib` and `vcpkg` submodules are not required to run the GUI.

This virtualenv is how the program is developed on a Mac. It is not what other people should have to build. Finished downloads will be on the [Releases](https://github.com/p4h88hnz4w-byte/wfs-studio/releases) page: the source zip and tar.gz for the tag, an Apple Silicon `.dmg` and a zip of the `.app`, and an x86_64 Linux AppImage. `make help` lists the recipe. No binary has been built yet.

## Tests

```bash
pytest
```

## Layout

```
install-linux.sh    Linux installer for apt, dnf, and pacman, including WSL2
scripts/build-catalog.sh  Builds the catalog tool. It does not download vcpkg.
native/wfs-catalog/   Catalog tool. It writes title metadata from an image.
src/wfs_studio/     Python package and GUI
tests/              Unit tests, using synthetic titles and saves
CHANGELOG.md        What has been built
requirements.txt    Python package for the window, PySide6
requirements-dev.txt  Test and pack extras
third_party/wfs-tools/   Upstream source at v1.2.3
packaging/licenses/ Qt and app license text copied into a frozen build
Makefile            Builds dist/ and can upload a GitHub Release
vendor/             Official binaries after download, on your machine
cache/              GameTDB list, disc images, settings, and wfs-studio.log, on your machine
dist/               Built .app, .zip, and .dmg, on your machine
```

## License

WFS Studio’s own source is MIT. See `LICENSE`.

Other material stays under its own terms and is not relicensed by this MIT grant:

- `third_party/wfs-tools` is MIT, copyright koolkdev. That `LICENSE` file stays with the source. The tools are built on koolkdev’s [wfslib](https://github.com/koolkdev/wfslib). This repository does not copy that library into its own tree. `wfslib` stays the nested submodule, checked out when the catalog tool is built. A full extract runs the official release zip. Catalog titles links `wfslib` and writes `meta/meta.xml` and `iconTex.tga`.
- The official wfs-tools release zips are downloaded when you run the app and kept in `vendor/` on your machine.
- The [GameTDB](https://www.gametdb.com/) title list and artwork are downloaded when you click Download GameTDB and kept in `cache/` on your machine. They remain GameTDB’s database. GameTDB does not host game dumps.
- Save backups follow the folder layout of [SaveMii](https://github.com/w3irDv/savemii). SaveMii’s source is not part of this program.
- Menu music is [8bit Bossa](https://opengameart.org/content/bossa-nova) by Joth, dedicated to the public domain under CC0. The app ships an Opus encode of that track, with the loop join at the start of the file. The original MP3 is not included.
- PySide6 is the window toolkit. It is Qt, available under the LGPL. A source checkout installs it with pip. A frozen build keeps those Qt libraries replaceable and copies `packaging/licenses/` into the app. WFS Studio’s own source stays MIT.
- NAND images, extracted titles, `otp.bin`, and `seeprom.bin` stay on the console owner’s computer. The app only receives the paths you choose.
