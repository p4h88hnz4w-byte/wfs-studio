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

- Python 3.10 or newer. On this Mac the system Python is 3.9, and Homebrew Python 3.12 works.
- The official `wfs-extract` build for your system. The app downloads v1.2.3 and checks its SHA-256.
- For an encrypted image: `otp.bin`. USB images also need `seeprom.bin`.
- For the Titles tab: an already extracted dump that contains `usr/title/<high-id>/<low-id>/meta/meta.xml`.

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
3. Download the GameTDB list when you want the database name and disc image. The file is `https://www.gametdb.com/wiiutdb.txt?LANG=EN`. A product code such as `WUP-P-APKE` matches GameTDB id `APKE01`.
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

WFS Studio is MIT, see `LICENSE`. `wfs-tools` remains under its own MIT license, copyright koolkdev.
