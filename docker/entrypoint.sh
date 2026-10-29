#!/bin/sh
# Run the headless CLI as PUID:PGID so downloaded files are not owned by root.
set -e

if [ "$(id -u)" = "0" ]; then
	mkdir -p "$HOME"
	chown "$PUID:$PGID" "$HOME"
	# Docker creates missing bind-mount folders as root; hand an empty one over.
	if [ -d /out ] && [ "$(stat -c %u /out)" = "0" ] && [ -z "$(ls -A /out)" ]; then
		chown "$PUID:$PGID" /out
	fi
	if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups test -w /out; then
		echo "csvmusic: /out is not writable by PUID=$PUID PGID=$PGID." >&2
		echo "Set PUID/PGID to the owner of your music folder, or chown it to $PUID:$PGID." >&2
		exit 1
	fi
	exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python -m csvmusic.download_csv "$@"
fi

# Already started as a non-root user (e.g. `user:` in compose)
exec python -m csvmusic.download_csv "$@"
