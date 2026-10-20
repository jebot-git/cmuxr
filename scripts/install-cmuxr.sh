#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
prefix=${1:-/usr/local}
./configure "prefix=$prefix"
make -j"$(getconf _NPROCESSORS_ONLN)"
make install-plugins install-data "DESTDIR=${DESTDIR:-}"
destination="${DESTDIR:-}$prefix"
install -d "$destination/bin" "$destination/share/cmuxr/cmuxr_gui" "$destination/share/cmuxr/licenses" "$destination/share/applications" "$destination/share/man/man1"
install -m755 cmus "$destination/bin/cmuxr-core"
install -m755 cmuxr "$destination/bin/cmuxr"
install -m644 cmuxr_gui/*.py "$destination/share/cmuxr/cmuxr_gui/"
install -m644 COPYING "$destination/share/cmuxr/licenses/COPYING.cmus"
install -m644 integration/org.domed.cmuxr.desktop "$destination/share/applications/"
install -m644 docs/man/cmuxr.1 "$destination/share/man/man1/"
if [ "${CMUXR_WITH_XR:-0}" = 1 ]; then
    dome=${CMUXR_DOMED_SOURCE:-../DomeD}
    ./scripts/integrate-domed.sh "$dome"
    cargo build --manifest-path "$dome/Cargo.toml" --release --features xr --bin dome-xr
    install -m755 "$dome/target/release/dome-xr" "$destination/bin/cmuxr-floor-renderer"
    # DomeD's own Start XR action must use the same integrated floor renderer.
    install -m755 "$dome/target/release/dome-xr" "$destination/bin/dome-xr"
    install -m755 cmuxr-floor "$destination/bin/cmuxr-floor"
    install -m644 integration/LICENSE.DomeD "$destination/share/cmuxr/licenses/"
    install -m644 integration/org.domed.cmuxr-floor.desktop "$destination/share/applications/"
    install -m644 docs/man/cmuxr-floor.1 "$destination/share/man/man1/"
fi
if [ -z "${DESTDIR:-}" ] && command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$destination/share/applications"
fi
