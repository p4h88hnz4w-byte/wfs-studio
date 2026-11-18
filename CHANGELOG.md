# Changelog

Work so far on WFS Studio. Versions 0.2.0 through 0.4.0 were built locally on top of tag `v0.1` and saved together in the 0.4.0 commit. The public repository is [p4h88hnz4w-byte/wfs-studio](https://github.com/p4h88hnz4w-byte/wfs-studio).

## 0.6.5

The version sits in the top-right corner of the window.

- The label reads the package version, so each later build shows its own number.

## 0.6.4

Save scan accepts the folder you actually picked.

- The Titles source can be the dump, `usr/save`, `usr/save/00050000`, or one title folder. `usr/save/system` is still skipped.
- The extract form connects the image-type buttons after the `otp.bin` field exists, so opening the window does not crash on that field.

## 0.6.3

A crash writes a traceback to the user data folder.

- The file is `cache/wfs-studio.log`. A checkout keeps it in the project. A frozen app uses Application Support on macOS, `~/.local/share/wfs-studio` on Linux, and `%APPDATA%\WFS Studio` on Windows. `WFS_STUDIO_DATA` overrides that folder.
- The log records the version and system at startup, an uncaught Python error, and a native fault. About WFS Studio shows the path. The file stays on your computer.

## 0.6.2

Downloads will be attached to a [GitHub Release](https://github.com/p4h88hnz4w-byte/wfs-studio/releases). The git tree stays source.

- GitHub attaches the source zip and tar.gz to the release tag. The built program is uploaded beside them.
- Apple Silicon is a `.dmg` and a zip of `WFS Studio.app`. Linux is an x86_64 AppImage. `Makefile` builds the Mac files into `dist/`, and `make release` uploads them when they exist.
- No binary has been built or uploaded.

## 0.6.1

The window follows the Wii U menu: white surfaces, soft gray panels, and the logo blue `#009AC7`.

- The desk is a soft gray. Pages, fields, and the title list are white. Inactive tabs use that same soft gray.
- The blue is reserved for the selected tab and its underline, the main buttons, the progress bar, and focus. A selected row is a pale blue wash so the title icon stays readable.
- Body text is a dark gray. The window is not a blue page. No `.app` or AppImage has been built.

## 0.6.0

A first step toward the Wii Backup Manager list, and toward an app that can be frozen.

- The title list shows `meta/iconTex.tga` beside each name. The large picture in the detail pane is unchanged: a GameTDB banner or disc when one exists, and the same icon when it does not.
- The copy button is labeled Transfer.
- A source checkout still keeps `cache/` and `vendor/` in the project directory. A frozen build will keep them in Application Support on a Mac and in `~/.local/share/wfs-studio` on Linux. `WFS_STUDIO_DATA` overrides that folder. No `.app` or AppImage has been built.

## 0.5.0

The title's own icon when GameTDB has no picture.

- The detail pane still prefers a banner from a cover zip, then a cached or downloaded GameTDB disc.
- When none of those exist, or the disc lookup is still running, the pane shows `meta/iconTex.tga` from the dumped title.
- A disc that arrives later replaces that icon. A known miss keeps the icon.
- The TGA is the uncompressed 128×128 image Wii U titles store. It is decoded in the app and shown as a PNG. No icon file is added to the repo.

## 0.4.0

Save backup, in SaveMii's layout. This program copies saves. It does not edit them.

- New Saves tab. Scan reads `usr/save/<high-id>/<low-id>/` from the dump chosen on the Titles tab.
- A checked save is copied to `Title Name [00050000-lowid]/<slot>/` with the profile folders, `common` when present, `savemii_saveinfo.xml`, and `savemiiMeta.json`.
- The folder name follows SaveMii: forbidden and non-ASCII characters become `_`, and the id is lowercase hex.
- The first backup of a title uses slot `0`. The next backup uses the next free slot, through `255`.
- `usr/save/system` is skipped.
- The metadata records `NAND` unless you mark the dump as USB. The serial is SaveMii's unknown value, `_WIIU_`.
- The dump is only read. The backup's file count and byte total are checked against the source.

## 0.3.0

Game data copy.

- Titles tab option, on by default: each checked title is written to its own folder, named from GameTDB plus the title id.
- `usr/save` is not part of that copy.
- When the copy finishes, the destination file count and byte total are checked against the source.
- Turn the option off to keep the older copy, which preserves the path relative to the source.

## 0.2.0

GameTDB zip, instead of only the plain text list.

- Download GameTDB stores `cache/wiiutdb.zip` and reads `wiiutdb.xml` from inside it with `zipfile` and `ElementTree`. The archive is not unpacked.
- Open zip loads a `wiiutdb.zip` you already have.
- The selected title can show the English name, region, developer, publisher, date, and genre.
- `cache/wiiutdb.txt` is still used when no zip is available.
- Banner zip looks up `<id>.png` inside a cover archive you point at. Without one, disc images are still downloaded one at a time into `cache/covers/`.

## 0.1.1

Kept in the same commit as 0.4.0. These landed after tag `v0.1` and before the zip reader.

- Title sizes are measured a few at a time and remembered in `cache/title-sizes.json`. A later scan reuses a size when `meta/meta.xml` is unchanged. Recount sizes measures again.
- Disc images for one title are requested together, so a missing image waits on the slowest reply instead of each region in turn.
- `.gitignore` keeps `HANDOFF.md` and `*.workflow.json` out of a future publish.

## 0.1.0

Tag `v0.1`. First local release.

- PySide6 window. Titles tab scans `meta/meta.xml`, looks up the plain GameTDB list, and copies checked title folders with a byte progress bar.
- Extract tab runs official `wfs-extract` v1.2.3. The binary is downloaded into gitignored `vendor/` and checked by SHA-256.
- `wfs-file-injector` and `wfs-reencryptor` are not run.
- SLC and SLCCMPT are refused. They are not WFS.
- MIT license for this program. `third_party/wfs-tools` stays under koolkdev's MIT license.
