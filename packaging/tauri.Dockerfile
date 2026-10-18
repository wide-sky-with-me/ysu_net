FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git pkg-config patchelf \
    libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
    librsvg2-dev libssl-dev libxdo-dev \
    xvfb dbus-x11 xauth imagemagick fonts-noto-cjk webkit2gtk-driver \
    python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

ARG USER_ID=1000
ARG GROUP_ID=1000
RUN groupadd --gid "$GROUP_ID" builder \
    && useradd --uid "$USER_ID" --gid "$GROUP_ID" --create-home builder
WORKDIR /workspace
USER builder
