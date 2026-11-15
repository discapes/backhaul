FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates procps python3 nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash agent
WORKDIR /home/agent
