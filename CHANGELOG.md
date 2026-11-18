# Changelog

Work so far on WFS Studio. Versions 0.2.0 through 0.4.0 were built locally on top of tag `v0.1` and saved together in the 0.4.0 commit. 0.5.0 is the current release. The public repository is [p4h88hnz4w-byte/wfs-studio](https://github.com/p4h88hnz4w-byte/wfs-studio).

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
