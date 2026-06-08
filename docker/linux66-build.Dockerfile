FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bc \
    bison \
    build-essential \
    ca-certificates \
    cpio \
    device-tree-compiler \
    flex \
    gcc-arm-linux-gnueabihf \
    git \
    libc6-dev-armhf-cross \
    libssl-dev \
    make \
    python3 \
    rsync \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*
