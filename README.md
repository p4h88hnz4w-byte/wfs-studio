# WFS Studio

WFS Studio is a desktop program for your own Wii U backups. Version 0.6.3. It is a PySide6 window around the official [wfs-tools](https://github.com/koolkdev/wfs-tools) v1.2.3 `wfs-extract`, plus a copier for extracted titles and saves. The window is white, soft gray, and the Wii U blue.

`CHANGELOG.md` is the record of what has been built. The short version:

| | |
| --- | --- |
| Done | List titles from `meta/meta.xml`. Read a GameTDB `wiiutdb.zip`. Show the title's own icon when GameTDB has no picture. Copy a title into its own named folder and check the size. Back up `usr/save` in SaveMii's folder layout. Run `wfs-extract` on your own MLC or USB image. Write a crash traceback to `cache/wfs-studio.log`. |
| Not this program | Editing the bytes inside a save. `wfs-file-injector` and `wfs-reencryptor`. |
| Next, when we pick it up | GameTDB pictures in the title list, closer to Wii Backup Manager. Then `make app` on this Mac, and the Linux AppImage. Downloads go on the GitHub Releases page. |

## Run

```bash
cd wfs-studio
source .venv/bin/activate
python -m wfs_studio
```

The first time, create the virtualenv as in Setup below.

## Titles tab

1. Choose the extracted dump, a `usr/title` folder, or one title folder.
2. Scan. Names come from `longname_*` in `meta/meta.xml`. Each row shows that title's `meta/iconTex.tga` beside the name. Sizes are measured a few titles at a time and remembered in `cache/title-sizes.json`. Recount sizes measures them again.
3. Download GameTDB, or choose a `wiiutdb.zip` you already have. The zip stays compressed in `cache/wiiutdb.zip`. The app reads `wiiutdb.xml` from inside it. A plain `cache/wiiutdb.txt` is used only when no zip is available. A product code such as `WUP-P-APKE` matches GameTDB id `APKE01`. Banner zip reads `<id>.png` from a cover archive you already have. Without one, disc pictures are saved under `cache/covers/` after a download. If there is no banner and no disc, the pane shows `meta/iconTex.tga` from that title. A disc that arrives later replaces the icon.
4. Check the titles, choose a destination, and press Transfer.

Game data copy is on by default. Each title is written to `Title Name [00050000-lowid]/`, and `usr/save` is not included. The window then checks that the destination file count and byte total match the source. Turn the option off to keep the path relative to the scanned folder, for example `usr/title/00050000/101DF400/...`. Files that already exist at the destination with the same size are skipped. A different size is replaced.

The copy shows a progress bar and the path currently being written. Stopping deletes the unfinished temporary file (`.wfs-studio-partial`) and leaves completed files where they are.

## Saves tab

Backs up saves onto this computer in the layout used by [SaveMii](https://github.com/w3irDv/savemii). It does not edit save files, and it does not write into the dump.

1. The source is the same dump as the Titles tab. It must contain `usr/save`.
2. Scan saves. `usr/save/system` is skipped.
3. Check the saves, choose a backup folder, and start the backup.

Each save is written to `Title Name [00050000-lowid]/0/` with the profile folders, `common` when the game has it, `savemii_saveinfo.xml`, and `savemiiMeta.json`. The next backup of that title uses slot `1`, then the next free slot through `255`. Check the USB box when the dump came from a USB drive so the metadata says `USB` instead of `NAND`.

To restore on a Wii U, copy that folder to `sd:/wiiu/backups` and use SaveMii there.

## Extract tab

Runs official `wfs-extract`. It reads an image or device and writes into the output folder. The input is not modified.

| Type | Keys | Typical input |
| --- | --- | --- |
| `mlc` | `otp.bin` | MLC backup image |
| `usb` | `otp.bin` and `seeprom.bin` | Wii U USB device or image |
| `plain` | none | A filesystem already decrypted by `wfs-reencryptor` |

Dump path defaults to `/`. Recovery mode (`--dump-usr-dir`) only accepts paths inside `/usr`. The command includes `--verbose`, which prints `Dumping /path` when each file starts. That line has no byte total, so the progress on this tab is a file count.

SLC and SLCCMPT images are not WFS. This tool cannot open `slc.bin` or `slccmpt.bin`.

## Safety

- Copying and save backup read the source and write only inside the destination you pick. The dump is not changed.
- Extract reads the input image or device and writes only inside the output folder.
- The destination cannot be the source, and it cannot sit inside the source.
- Stopping a copy deletes the unfinished temporary file (`.wfs-studio-partial`) and leaves completed files where they are.
- `otp.bin` and `seeprom.bin` are used only as local paths passed to `wfs-extract`. They stay on your computer.
- `wfs-file-injector` and `wfs-reencryptor` are in the official zip. This program does not run them. Both can change a WFS image.
- SLC and SLCCMPT dumps are not WFS images. `wfs-extract` cannot open `slc.bin` or `slccmpt.bin`.

`cache/settings.json` stores the folders you pick, including key-file paths. It stays in `cache/` on your computer.

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
- Your own `otp.bin` for an encrypted MLC or USB image. A USB image also needs your own `seeprom.bin`. The app passes those paths only to `wfs-extract` on the computer where you run it.

A full USB or MLC extract can be hundreds of gigabytes. Pick a destination with enough free space.

Reading a raw USB device may require an administrator shell. The window shows the exact command so you can run it yourself with the privileges you choose. The app does not request them.

## Setup

```bash
git clone --recurse-submodules https://github.com/p4h88hnz4w-byte/wfs-studio.git
cd wfs-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m wfs_studio.binaries
python -m wfs_studio
```

`third_party/wfs-tools` is a git submodule pinned to upstream tag `v1.2.3` (commit `f5c652e`). Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after a normal clone. The nested `wfslib` and `vcpkg` submodules are not required to run the GUI.

This virtualenv is how the program is developed on a Mac. It is not what other people should have to build. Finished downloads will be on the [Releases](https://github.com/p4h88hnz4w-byte/wfs-studio/releases) page: the source zip and tar.gz for the tag, an Apple Silicon `.dmg` and a zip of the `.app`, and an x86_64 Linux AppImage. `make help` lists the recipe. No binary has been built yet.

## Tests

```bash
pytest
```

## Layout

```
src/wfs_studio/     Python package and GUI
tests/              Unit tests, using synthetic titles and saves
CHANGELOG.md        What has been built
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

- `third_party/wfs-tools` is MIT, copyright koolkdev. That `LICENSE` file stays with the source.
- The official wfs-tools release zips are downloaded when you run the app and kept in `vendor/` on your machine.
- The GameTDB title list and artwork are downloaded when you click Download GameTDB and kept in `cache/` on your machine. They are GameTDB’s database. GameTDB does not host game dumps.
- NAND images, extracted titles, `otp.bin`, and `seeprom.bin` stay on the console owner’s computer. The app only receives the paths you choose.
