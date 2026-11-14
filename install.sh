#!/bin/sh
# Install the ascii-media binary on Linux or macOS.
# Usage: curl -fsSL https://raw.githubusercontent.com/anargia-pixels/ascii-media-convertor/master/install.sh | sh
# Set ASCII_MEDIA_VERSION (for example v1.0.0) to install a specific release.
# Set ASCII_MEDIA_INSTALL_DIR to change the install directory.
set -eu

REPO="anargia-pixels/ascii-media-convertor"
VERSION="${ASCII_MEDIA_VERSION:-latest}"
INSTALL_DIR="${ASCII_MEDIA_INSTALL_DIR:-$HOME/.local/bin}"

# Print an error and stop.
fail() {
    echo "error: $1" >&2
    exit 1
}

# Print the SHA-256 hash of a file.
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        shasum -a 256 "$1" | cut -d ' ' -f 1
    fi
}

# Platform detection
case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=macos ;;
    *) fail "unsupported OS $(uname -s). On Windows, use install.ps1." ;;
esac
case "$(uname -m)" in
    x86_64 | amd64) arch=x86_64 ;;
    arm64 | aarch64) arch=arm64 ;;
    *) fail "unsupported CPU $(uname -m)." ;;
esac
asset="ascii-media-$os-$arch"

if [ "$VERSION" = latest ]; then
    base="https://github.com/$REPO/releases/latest/download"
else
    base="https://github.com/$REPO/releases/download/$VERSION"
fi

# Download and verify
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $asset ($VERSION)"
curl -fSL --progress-bar "$base/$asset" -o "$tmp/$asset"
curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS"
expected="$(grep " $asset\$" "$tmp/SHA256SUMS" | cut -d ' ' -f 1)"
[ -n "$expected" ] || fail "no checksum for $asset in SHA256SUMS."
[ "$(sha256 "$tmp/$asset")" = "$expected" ] || fail "checksum mismatch for $asset."

# Install
mkdir -p "$INSTALL_DIR"
chmod +x "$tmp/$asset"
mv "$tmp/$asset" "$INSTALL_DIR/ascii-media"
echo "Installed ascii-media to $INSTALL_DIR/ascii-media"

case ":$PATH:" in
    *":$INSTALL_DIR:"*) echo "Run: ascii-media --help" ;;
    *) echo "Add $INSTALL_DIR to your PATH, then run: ascii-media --help" ;;
esac
