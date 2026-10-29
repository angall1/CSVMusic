#!/bin/sh
# Run the headless CLI as PUID:PGID so downloaded files are not owned by root.
set -e

if [ "$(id -u)" = "0" ]; then
	mkdir -p "$HOME"
	chown "$PUID:$PGID" "$HOME"
	exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python -m csvmusic.download_csv "$@"
fi

# Already started as a non-root user (e.g. `user:` in compose)
exec python -m csvmusic.download_csv "$@"
