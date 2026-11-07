#!/bin/sh
set -eu
image=$1
work=$(mktemp -d)
# Only remove this explicitly created temporary directory.
trap 'sudo rm -rf -- "$work"' EXIT
mkdir "$work/out" "$work/config" "$work/in"
chmod 0755 "$work"
sudo chown 0:0 "$work/out" "$work/config"
docker run --rm --network none -e PUID=1234 -e PGID=1234 \
	-v "$work/out:/out" -v "$work/config:/config" -v "$work/in:/in:ro" \
	"$image" --help > "$work/help.txt"
grep -q -- '--no-skipped-csv' "$work/help.txt"
# Empty root-owned mounts are handed to the download user.
test "$(stat -c %u "$work/out")" = 1234
test "$(stat -c %g "$work/out")" = 1234
test "$(stat -c %u "$work/config/.local/share/csvmusic")" = 1234
# An explicitly non-root container user also works.
docker run --rm --network none --user 1234:1234 \
	-v "$work/out:/out" -v "$work/config:/config" "$image" --help > /dev/null
docker run --rm --network none --entrypoint python "$image" -c '
import importlib.util, subprocess
from csvmusic.core.js_runtime import detect_js_runtimes
assert importlib.util.find_spec("PySide6") is None
assert any(runtime.name == "Deno" and runtime.supported for runtime in detect_js_runtimes())
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1", "-c:a", "libmp3lame", "/tmp/probe.mp3"], check=True)
'
# Do not take ownership of a populated, unrelated output folder.
sudo chown 2345:2345 "$work/out"
sudo touch "$work/out/existing"
if docker run --rm --network none -e PUID=1234 -e PGID=1234 \
	-v "$work/out:/out" -v "$work/config:/config" "$image" --help > "$work/error.txt" 2>&1; then
	echo "Expected an unwritable output folder to fail" >&2
	exit 1
fi
grep -q '/out is not writable' "$work/error.txt"
test "$(stat -c %u "$work/out")" = 2345
sudo chown 1234:1234 "$work/out"
sudo chown 2345:2345 "$work/config/.local/share/csvmusic"
if docker run --rm --network none -e PUID=1234 -e PGID=1234 \
	-v "$work/out:/out" -v "$work/config:/config" "$image" --help > "$work/config-error.txt" 2>&1; then
	echo "Expected an unwritable config folder to fail" >&2
	exit 1
fi
grep -q '/config is not writable' "$work/config-error.txt"
if docker run --rm --network none -e PUID=0 -e PGID=0 "$image" --help > "$work/id-error.txt" 2>&1; then
	echo "Expected root download IDs to fail" >&2
	exit 1
fi
grep -q 'non-root' "$work/id-error.txt"
