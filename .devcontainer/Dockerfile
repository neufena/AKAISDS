FROM mcr.microsoft.com/devcontainers/base:trixie

# build-essential/patchelf: Nuitka standalone on Linux. The libs after that are what Qt needs to start, for the tests and pyside6-deploy's dependency scan.
# The Windows build is not done here (Nuitka can't cross-compile): see BUILDING.md.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential patchelf ccache git curl wget ca-certificates unzip zip file \
        xvfb xauth \
        qt6-qpa-plugins libegl1 libgl1 libfontconfig1 libnss3 libasound2t64 libpulse0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
        libxcb-shm0 libxcb-sync1 libxcb-xkb1 libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxi6 libxtst6 \
        libportaudio2 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# uv, pinned to a release; it installs the Python in .python-version itself
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-managed
