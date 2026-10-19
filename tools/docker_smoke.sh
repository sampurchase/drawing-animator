#!/usr/bin/env bash
# Builds the image, starts it with a throwaway volume, uploads a sample drawing and makes a quick preview.
# Run from the project folder:  bash tools/docker_smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
IMG=drawing-dance-smoke
NAME=drawing-dance-smoke
PORT=18080
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME-data" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker build -t "$IMG" .
docker run -d --name "$NAME" -p "$PORT:8080" -v "$NAME-data:/data" "$IMG" >/dev/null
for i in $(seq 1 30); do
  curl -fs "http://localhost:$PORT/api/health" >/dev/null && break
  sleep 1
  [ "$i" = 30 ] && { echo "FAIL: app did not start"; docker logs "$NAME"; exit 1; }
done
echo "ok: health check answers"
docker exec "$NAME" id -u | grep -qv '^0$' && echo "ok: running as a normal user"
curl -fs -X POST -F "file=@samples/fake_photo.jpg" -F "name=Smoke" "http://localhost:$PORT/api/drawings" > /tmp/smoke_drawing.json
ID=$(python3 -c "import json; print(json.load(open('/tmp/smoke_drawing.json'))['id'])")
echo "ok: drawing uploaded ($ID)"
RID=$(curl -fs -X POST -H 'Content-Type: application/json' \
  -d "{\"drawings\":[\"$ID\"],\"quality\":\"preview\",\"seconds\":4}" "http://localhost:$PORT/api/renders" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
for i in $(seq 1 120); do
  S=$(curl -fs "http://localhost:$PORT/api/renders/$RID" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$S" = done ] && break
  [ "$S" = failed ] && { echo "FAIL: render failed"; docker logs "$NAME"; exit 1; }
  sleep 1
done
[ "$S" = done ] || { echo "FAIL: render timed out"; exit 1; }
curl -fs -o /dev/null -H 'Range: bytes=0-99' -w '%{http_code}\n' "http://localhost:$PORT/files/renders/$RID/video.mp4" | grep -q 206
echo "ok: preview rendered and plays in pieces"
echo "ALL GOOD"
