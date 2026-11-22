#!/bin/sh
# dev replay of the golden vectors against bin/mechbot run inside a container
export MSYS_NO_PATHCONV=1
WS=$(cygpath -w "$(cd "$(dirname "$0")/.." && pwd)")
IN=$(cygpath -w "$(cd "$(dirname "$0")/../../input" && pwd)")
NOMOUNT=$(python -I -c 'import json,sys; print(json.dumps(["docker","run","--rm","-i","--network","none","-v",sys.argv[1]+chr(92)+"bin:/b:ro","golang:1.26.1-bookworm","/b/mechbot"]))' "$WS")
python -I "$IN\golden_replay.py" "$IN\golden_vectors.jsonl.gz" --nomount-cmd "$NOMOUNT" "$@" -- \
  docker run --rm -i --network none -v "$WS\bin:/b:ro" -v "$IN\mechfight-kit\arena:/arena:ro" golang:1.26.1-bookworm /b/mechbot
