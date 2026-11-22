#!/bin/sh
# dev build: compile the bot (and optional tools) inside golang:1.26.1-bookworm
export MSYS_NO_PATHCONV=1
WS=$(cygpath -w "$(cd "$(dirname "$0")/.." && pwd)")
docker run --rm -v "$WS:/src" -v apexgo-cache:/root/.cache -w /src \
  -e CGO_ENABLED=0 -e GOOS=linux -e GOARCH=amd64 -e GOTOOLCHAIN=local -e GOFLAGS=-mod=mod \
  golang:1.26.1-bookworm sh -c "go vet ./... && go build -trimpath -ldflags='-s -w' -o bin/mechbot ./cmd/mechbot $*"
