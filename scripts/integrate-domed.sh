#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dome=${1:-"$root/../DomeD"}
patch="$root/integration/domed-music-floor.patch"
if git -C "$dome" apply --reverse --check "$patch" 2>/dev/null; then
    echo 'DomeD music floor integration is already applied.'
else
    git -C "$dome" apply --check "$patch"
    git -C "$dome" apply "$patch"
fi
cargo test --manifest-path "$dome/Cargo.toml" --lib music_floor
cargo check --manifest-path "$dome/Cargo.toml" --features xr --bin dome-xr
