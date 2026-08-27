# CSVMusic on Linux

Extract the release archive, open a terminal in the extracted `CSVMusic` folder, and run:

```bash
chmod +x CSVMusic yt-dlp
./CSVMusic
```

## Qt reports that the `xcb` platform plugin could not be initialized

CSVMusic uses Qt's graphical desktop integration. On Ubuntu 24.04, Zorin OS 18, and related Debian-based distributions, install the XCB cursor runtime and retry:

```bash
sudo apt update
sudo apt install libxcb-cursor0
```

If Qt lists another missing shared library, inspect the packaged XCB plugin with:

```bash
ldd _internal/PySide6/Qt/plugins/platforms/libqxcb.so | grep "not found"
```

The exact `_internal` path can vary between releases. If the command cannot find the plugin, locate it with:

```bash
find . -name libqxcb.so -print
```

When reporting a startup problem, include the terminal output plus:

```bash
uname -m
cat /etc/os-release
```
