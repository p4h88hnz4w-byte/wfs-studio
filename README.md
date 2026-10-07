# WFS Studio

WFS Studio is a desktop program for your own Wii U backups. It lists the titles in an extracted dump, shows the name from each `meta/meta.xml`, matches that title in the [GameTDB](https://www.gametdb.com/) Wii U list, and copies the titles you check into a folder you choose. A second tab runs the official `wfs-extract` from [wfs-tools](https://github.com/koolkdev/wfs-tools) v1.2.3.

The copy shows a progress bar and the path currently being written. `wfs-extract` prints a path when it starts each file and does not report a byte total, so the Extract tab shows that path and a running count.

## Safety

- Copying reads the source and writes only inside the destination you pick.
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

## Titles tab

1. Choose the extracted dump, a `usr/title` folder, or one title folder.
2. Scan. Names come from `longname_*` in `meta/meta.xml`.
3. Download the GameTDB list when you want the database name and disc image. The app stores that list in `cache/wiiutdb.txt`, the same idea as WiiFlow keeping `wiitdb.zip` on the SD card. A product code such as `WUP-P-APKE` matches GameTDB id `APKE01`. Disc pictures are saved under `cache/covers/` after a successful download. GameTDB’s full cover packs, including DS and other systems, are separate downloads and are not bundled here.
4. Check the titles to copy, choose a destination, and start the copy.

The destination keeps the path relative to the scanned folder, for example `usr/title/00050000/101DF400/...`. Files that already exist at the destination with the same size are skipped. A different size is replaced.

## Extract tab

| Type | Keys | Typical input |
| --- | --- | --- |
| `mlc` | `otp.bin` | MLC backup image |
| `usb` | `otp.bin` and `seeprom.bin` | Wii U USB device or image |
| `plain` | none | A filesystem already decrypted by `wfs-reencryptor` |

Dump path defaults to `/`. Recovery mode (`--dump-usr-dir`) only accepts paths inside `/usr`.

The command always includes `--verbose`, which is what produces `Dumping /path` lines.

## Tests

```bash
pytest
```

## Layout

```
src/wfs_studio/     Python package and GUI
tests/              Unit tests, using synthetic meta.xml files
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
