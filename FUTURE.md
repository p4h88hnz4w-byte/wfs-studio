# Where this is going

What is already built is listed in `CHANGELOG.md`. This file is the work that is still ahead, and the plan for shipping an app. No frozen app has been built. The source is at [p4h88hnz4w-byte/wfs-studio](https://github.com/p4h88hnz4w-byte/wfs-studio).

## Not this program

Save editing. WFS Studio copies a save folder so you have a backup on the PC. Changing bytes inside a save, once a game's format is known, belongs in another tool.

`wfs-file-injector` and `wfs-reencryptor`. Both can change a WFS image. The injector replaces one existing file and can corrupt the image. It is not a save manager. It stays unwired unless there is a separate request to write one file back into a backed-up image.

## Possible next steps

- A byte progress bar on the Extract tab. Stock `wfs-extract --verbose` prints `Dumping /path` before each file and has no size. That needs a small fork of the official tool. The official binary stays the default until a fork is tested.
- The source repository is published. GameTDB files, dumps, and console keys stay out of git.

## Release

People who use this should not create a Python virtualenv. The `.venv` in this checkout is a development environment on this Mac (Homebrew Python 3.12, Apple Silicon). It is gitignored. It does not run on Linux, and it is not the file we publish.

Ship one frozen app per machine type. The first two are the ones that match the machines we can actually support with the official `wfs-extract` builds already checksummed in `binaries.py`.

| Artifact | Built on | Who can run it |
| --- | --- | --- |
| macOS `.app`, arm64 | This Mac | Apple Silicon |
| Linux AppImage, x86_64 | A container whose glibc is 2.28 | Most current desktop x86_64 distros. See below. |
| macOS `.app`, x86_64 | An Intel Mac, later | Intel Macs. Official `wfs-extract` already has a `macos-x64` zip. This Mac's Homebrew Python is arm64 only, so it cannot produce that app. |
| Windows | Later | Official `wfs-extract` already has a `windows-x64` zip. |

### Linux, and what "most distros" can mean

The official extract tool publishes `linux-x86-64` and nothing else. There is no aarch64 build, no 32-bit build, and no musl build. A Raspberry Pi, an ARM server, and Alpine cannot run the extract step until upstream ships a binary for them. The Linux app we publish is x86_64.

PySide6's x86_64 wheels are `manylinux_2_28`. That means glibc 2.28 or newer. In practice that is Ubuntu 20.04 and later, Debian 10 and later, RHEL 8 and later, current Fedora, and the Linux Mint and Pop!_OS releases based on those. It does not include Ubuntu 18.04, Debian 9, or other systems that stopped at an older glibc.

The build machine decides the glibc floor. An AppImage built on a new Ubuntu links that newer glibc and then fails on Debian 10 with `GLIBC_2.xx not found`, even though the Qt wheel itself only needs 2.28. Build the AppImage inside a glibc 2.28 container (AlmaLinux 8 or a manylinux_2_28 image), not on this Mac and not on the newest distro.

AppImage is one file to download and run. Flatpak and Snap confine the filesystem and raw devices. This program opens a folder the user picks and sometimes a USB device, so those stores are a poor fit. Some distros still need FUSE to mount an AppImage. The notes that ship with the file should say how to run it extracted when FUSE is missing.

The aarch64 PySide6 wheels moved up to a much newer glibc. That does not change this plan. We still have no ARM `wfs-extract` to put next to them.

### What the frozen app has to change in the code

`locations.data_dir` is the split. A source checkout still writes `cache/` and `vendor/` next to the project. A frozen build writes them under Application Support on macOS and `~/.local/share/wfs-studio` on Linux. `WFS_STUDIO_DATA` overrides either place. `WFS_STUDIO_HOME` still chooses the checkout root used in development. The next packaging step is to build the Apple Silicon `.app` with that data directory, and to put the matching `wfs-extract` beside the app.

Still to do when the app is frozen:
- `wfs-extract` for that platform shipped beside the app, with koolkdev's MIT `LICENSE`, still checked by the SHA-256 in `binaries.py`. The download can stay as a fallback when the bundled binary is absent.
- Qt kept as shared libraries inside the bundle, not compiled into the executable. PySide6 is LGPL. The app must include Qt's license and must document how to replace those libraries. A one-file blob that hides the Qt libraries is the wrong shape.

### What does not go in the blob

- The GameTDB zip, a cover pack, or disc art. The user still downloads those from the app, into the user data directory.
- A dump, a game, `otp.bin`, or `seeprom.bin`.
- `HANDOFF.md`, `cache/`, or `.venv`.
- `wfs-file-injector` and `wfs-reencryptor` as features. The official zip contains them. The app still does not run them.

No `.app` and no AppImage have been produced. The data-directory split is in place, and the Apple Silicon `.app` is the next build.

## Still out of scope

- Shipping a GameTDB snapshot, a cover pack, a dump, `otp.bin`, or `seeprom.bin`.
- Opening SLC or SLCCMPT. `wfs-extract` cannot read them.
