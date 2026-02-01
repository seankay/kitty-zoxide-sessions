#!/usr/bin/env sh
set -eu

REPO_URL=${REPO_URL:-"https://raw.githubusercontent.com/seankay/kitty-zoxide-sessions/main"}
PREFIX=${PREFIX:-"$HOME/.local"}
BINDIR=${BINDIR:-"$PREFIX/bin"}

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
    return
  fi

  echo "install.sh: requires curl or wget" >&2
  exit 1
}

install_file() {
  src_url=$1
  dest_path=$2
  mode=$3

  tmp_file=$(mktemp)
  fetch "$src_url" > "$tmp_file"
  chmod "$mode" "$tmp_file"
  mv "$tmp_file" "$dest_path"
}

mkdir -p "$BINDIR"

install_file "$REPO_URL/kitty-zoxide-sessions.py" "$BINDIR/kitty-zoxide-sessions.py" 755
install_file "$REPO_URL/default.kitty-session" "$BINDIR/default.kitty-session" 644

echo "Installed to $BINDIR/kitty-zoxide-sessions.py"
echo "Add $BINDIR to your PATH if needed."
