# WFS Studio

WFS Studio is a desktop program for your own Wii U backups. Version 0.4.0. It is a PySide6 window around the official [wfs-tools](https://github.com/koolkdev/wfs-tools) v1.2.3 `wfs-extract`, plus a copier for extracted titles and saves.

`CHANGELOG.md` is the record of what has been built. `FUTURE.md` is what is still ahead. The short version:

| | |
| --- | --- |
| Done | List titles from `meta/meta.xml`. Read a GameTDB `wiiutdb.zip`. Copy a title into its own named folder and check the size. Back up `usr/save` in SaveMii's folder layout. Run `wfs-extract` on your own MLC or USB image. |
| Not this program | Editing the bytes inside a save. `wfs-file-injector` and `wfs-reencryptor`. |
| Next, when we pick it up | A title icon from the dump itself when GameTDB has no banner. A byte bar on the Extract tab. A remote, once there is a GitHub account to push to. |

## Run

```bash
cd ~/Documents/Git/wfs-studio
source .venv/bin/activate
python -m wfs_studio
```

The first time, create the virtualenv as in Setup below.

## Titles tab

1. Choose the extracted dump, a `usr/title` folder, or one title folder.
2. Scan. Names come from `longname_*` in `meta/meta.xml`. Sizes are measured a few titles at a time and remembered in `cache/title-sizes.json`. Recount sizes measures them again.
3. Download GameTDB, or choose a `wiiutdb.zip` you already have. The zip stays compressed in `cache/wiiutdb.zip`. The app reads `wiiutdb.xml` from inside it. A plain `cache/wiiutdb.txt` is used only when no zip is available. A product code such as `WUP-P-APKE` matches GameTDB id `APKE01`. Banner zip reads `<id>.png` from a cover archive you already have. Without one, disc pictures are saved under `cache/covers/` after a download. GameTDB's files are not bundled here.
4. Check the titles to copy and choose a destination.

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
- `otp.bin` and `seeprom.bin` are used only as local paths passed to `wfs-extract`. They are not uploaded, and the gitignore refuses those filenames.
- `wfs-file-injector` and `wfs-reencryptor` are in the official zip. This program does not run them. Both can change a WFS image.
- SLC and SLCCMPT dumps are not WFS images. `wfs-extract` cannot open `slc.bin` or `slccmpt.bin`.

`cache/settings.json` stores the folders you pick, including key-file paths. That folder is gitignored. Do not publish it.

## What you need

Each person supplies their own console data. This repository does not include a Wii U drive image, games, `otp.bin`, or `seeprom.bin`.

- Python 3.10 or newer. On this Mac the system Python is 3.9, and Homebrew Python 3.12 works.
- The official `wfs-extract` build for your system. The app downloads v1.2.3 and checks its SHA-256. Those binaries stay in gitignored `vendor/`.
- Your own Wii U backup: an extracted dump with `usr/title/<high-id>/<low-id>/meta/meta.xml`, or an MLC/USB image from your console.
- Your own `otp.bin` for an encrypted MLC or USB image. A USB image also needs your own `seeprom.bin`. The app passes those paths only to `wfs-extract` on the computer where you run it.

A full USB or MLC extract can be hundreds of gigabytes. Pick a destination with enough free space.

Reading a raw USB device may require an administrator shell. The window shows the exact command so you can run it yourself with the privileges you choose. The app does not request them.

## Setup

```bash
cd ~/Documents/Git/wfs-studio
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m wfs_studio.binaries
python -m wfs_studio
```

`third_party/wfs-tools` is a git submodule pinned to upstream tag `v1.2.3` (commit `f5c652e`). Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after a normal clone. The nested `wfslib` and `vcpkg` submodules are not required to run the GUI.

## Tests

```bash
pytest
```

## Layout

```
src/wfs_studio/     Python package and GUI
tests/              Unit tests, using synthetic titles and saves
CHANGELOG.md        What has been built
FUTURE.md           What is still ahead
third_party/wfs-tools/   Upstream source at v1.2.3
vendor/             Official binaries after download (gitignored)
cache/              GameTDB list, disc images, settings (gitignored)
```

## License

WFS Studio’s own source is MIT. See `LICENSE`.

Other material stays under its own terms and is not relicensed by this MIT grant:

- `third_party/wfs-tools` is MIT, copyright koolkdev. Keep that `LICENSE` file with the source.
- The official wfs-tools release zips are downloaded at runtime into `vendor/`. They are not committed.
- The GameTDB title list and artwork are fetched when you click Download GameTDB, then stored only in gitignored `cache/`. They are GameTDB’s database, not part of this source tree. GameTDB does not host game dumps.
- NAND images, extracted titles, `otp.bin`, and `seeprom.bin` come from the user’s own console. `.gitignore` refuses those filenames. Do not add them to the repo.
