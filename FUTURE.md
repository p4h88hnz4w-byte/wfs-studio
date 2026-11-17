# Where this is going

What is already built is listed in `CHANGELOG.md`. This file is only the work that is still ahead. None of it is started.

## Not this program

Save editing. WFS Studio copies a save folder so you have a backup on the PC. Changing bytes inside a save, once a game's format is known, belongs in another tool.

`wfs-file-injector` and `wfs-reencryptor`. Both can change a WFS image. The injector replaces one existing file and can corrupt the image. It is not a save manager. It stays unwired unless there is a separate request to write one file back into a backed-up image.

## Possible next steps

- Show the title's own `meta/iconTex.tga` when a GameTDB banner is missing. The zip reader and the banner zip are already in place. This image is not read today.
- A byte progress bar on the Extract tab. Stock `wfs-extract --verbose` prints `Dumping /path` before each file and has no size. That needs a small fork of the official tool. The official binary stays the default until a fork is tested.
- Publishing. The tree is local only. A public or private remote waits until there is a GitHub account to push to. GameTDB files, dumps, and console keys stay out of git.

## Still out of scope

- Shipping a GameTDB snapshot, a cover pack, a dump, `otp.bin`, or `seeprom.bin`.
- Opening SLC or SLCCMPT. `wfs-extract` cannot read them.
