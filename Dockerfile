# syntax=docker/dockerfile:1
# Headless CSVMusic: runs the Qt-free CLI (python -m csvmusic.download_csv).
# Multi-arch: every base image below is published for linux/amd64 and linux/arm64.
ARG PYTHON_VERSION=3.12
ARG DENO_VERSION=2.9.4

FROM denoland/deno:bin-${DENO_VERSION} AS deno

FROM python:${PYTHON_VERSION}-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ffmpeg ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JavaScript runtime for YouTube; csvmusic finds deno on PATH.
COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app
COPY pyproject.toml README.md MANIFEST.in ./
COPY licenses ./licenses
COPY csvmusic ./csvmusic

# Install the runtime dependencies from pyproject.toml minus PySide6 (GUI only),
# then the package itself without pulling its dependency list.
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; print('\n'.join(d for d in deps if not d.lower().startswith('pyside6')))" > /tmp/requirements.txt \
	&& pip install --no-cache-dir -r /tmp/requirements.txt \
	&& pip install --no-cache-dir --no-deps . \
	&& rm -rf /tmp/requirements.txt /app/build

COPY docker/entrypoint.sh /usr/local/bin/csvmusic-entrypoint
RUN chmod 0755 /usr/local/bin/csvmusic-entrypoint && mkdir -p /in /out /config

# HOME holds csvmusic's log (~/.local/share/csvmusic/app.log) and yt-dlp's cache.
ENV HOME=/config \
	PUID=1000 \
	PGID=1000 \
	PYTHONUNBUFFERED=1

WORKDIR /out
ENTRYPOINT ["csvmusic-entrypoint"]
CMD ["--help"]
