# Release recipe. Built files go to dist/ and stay out of git.
# GitHub Releases is where they are published. The source zip and tar.gz
# are the archives GitHub attaches to the tag. This file uploads only the
# programs built below.

VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
APP_NAME := WFS Studio
DIST := dist
APP := $(DIST)/$(APP_NAME).app
STEM := WFS-Studio-$(VERSION)-macos-arm64
PYINSTALLER := .venv/bin/pyinstaller

.PHONY: help app zip dmg appimage release clean

help:
	@printf '%s\n' \
		'WFS Studio $(VERSION)' \
		'' \
		'  make app        Apple Silicon .app in dist/ (this Mac)' \
		'  make zip        zip of that .app' \
		'  make dmg        disk image of that .app' \
		'  make appimage   Linux x86_64 AppImage (glibc 2.28 container)' \
		'  make release    upload dist/WFS-Studio-$(VERSION)-* to GitHub Releases' \
		'  make clean      delete dist/ and build/' \
		'' \
		'GitHub adds the source zip and tar.gz when the release is created.' \
		'Nothing in dist/ is committed.'

app:
	@uname -s | grep -qx Darwin || { echo 'make app builds the Apple Silicon app on this Mac.'; exit 1; }
	@uname -m | grep -qx arm64 || { echo 'This Mac builds the arm64 app. An Intel .app needs an Intel Mac.'; exit 1; }
	@test -x $(PYINSTALLER) || { echo 'Install the pack tools first: .venv/bin/pip install -e ".[pack]"'; exit 1; }
	$(PYINSTALLER) --noconfirm --clean --windowed \
		--name "$(APP_NAME)" \
		--osx-bundle-identifier io.github.p4h88hnz4w-byte.wfs-studio \
		--paths src \
		--collect-all PySide6 \
		--collect-all shiboken6 \
		--distpath $(DIST) \
		--workpath build/pyinstaller \
		--specpath build \
		--add-data "src/wfs_studio/assets/menu.opus:." \
		src/wfs_studio/__main__.py
	mkdir -p "$(APP)/Contents/Resources/licenses"
	cp LICENSE "$(APP)/Contents/Resources/licenses/LICENSE"
	cp third_party/wfs-tools/LICENSE "$(APP)/Contents/Resources/licenses/wfs-tools-LICENSE"
	cp packaging/licenses/* "$(APP)/Contents/Resources/licenses/"
	/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $(VERSION)" "$(APP)/Contents/Info.plist"
	/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $(VERSION)" "$(APP)/Contents/Info.plist"
	codesign --force --deep --sign - "$(APP)"

zip: app
	ditto -c -k --keepParent "$(APP)" "$(DIST)/$(STEM).zip"

dmg: app
	hdiutil create -volname "$(APP_NAME)" -srcfolder "$(APP)" -ov -format UDZO "$(DIST)/$(STEM).dmg"

appimage:
	@echo 'The Linux download is an x86_64 AppImage built in a glibc 2.28 container.'
	@echo 'Build it there, name it dist/WFS-Studio-$(VERSION)-linux-x86_64.AppImage, then run make release.'
	@exit 1

release:
	@git diff --quiet && git diff --cached --quiet || { echo 'Commit the tree before make release.'; exit 1; }
	@set -e; \
	files=$$(find $(DIST) -maxdepth 1 -type f -name 'WFS-Studio-$(VERSION)-*' | sort); \
	if [ -z "$$files" ]; then \
		echo 'Nothing to upload. Run make zip or make dmg first.'; \
		exit 1; \
	fi; \
	if gh release view 'v$(VERSION)' --repo p4h88hnz4w-byte/wfs-studio >/dev/null 2>&1; then \
		echo 'Release v$(VERSION) already exists. Not replacing it.'; \
		exit 1; \
	fi; \
	{ \
		echo 'WFS Studio $(VERSION)'; \
		echo; \
		echo 'Source code for this tag is the zip and the tar.gz that GitHub attaches to the release.'; \
		echo; \
		echo 'Apple Silicon: $(STEM).dmg and $(STEM).zip. Both contain $(APP_NAME).app.'; \
		echo 'Linux x86_64: WFS-Studio-$(VERSION)-linux-x86_64.AppImage, when this release includes one.'; \
		echo; \
		echo 'Settings, GameTDB files, and the downloaded wfs-extract stay in Application Support on a Mac and in ~/.local/share/wfs-studio on Linux.'; \
	} > $(DIST)/RELEASE_NOTES.md; \
	gh release create 'v$(VERSION)' $$files \
		--repo p4h88hnz4w-byte/wfs-studio \
		--title 'WFS Studio $(VERSION)' \
		--notes-file $(DIST)/RELEASE_NOTES.md

clean:
	rm -rf $(DIST) build
