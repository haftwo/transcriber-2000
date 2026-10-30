#!/bin/bash
# Double-click in Finder to build the Audio Transcriber - 2000 image for Unraid (x86)
# and push it to Docker Hub. Needs Docker Desktop running.
cd "$(dirname "$0")"
pause() { echo; read -n1 -s -p "Press any key to close this window"; echo; }
trap 'echo; echo "Something went wrong (see above)."; pause; exit 1' ERR
set -e

echo "== Audio Transcriber - 2000: build and push to Docker Hub =="
if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop isn't running. Start it, wait for it to say 'running', then double-click this again."
  pause; exit 1
fi

GUESS=$(docker info 2>/dev/null | awk '/Username:/{print $2}')
if [ -n "$GUESS" ]; then
  DH=$GUESS
  echo "Docker Hub user: $DH"
else
  DH=${DOCKERHUB_USER:-haftwo}   # matches unraid-template.xml; override with DOCKERHUB_USER
  echo "Docker Hub user: $DH"
fi
if [ -z "$DH" ]; then echo "A Docker Hub username is needed."; pause; exit 1; fi

echo; echo "Signing in to Docker Hub (reuses Docker Desktop's sign-in if you have one)..."
docker login

IMAGE="$DH/transcriber-2000:latest"
echo; echo "Building $IMAGE for linux/amd64 and pushing (first run takes a few minutes)..."
docker buildx build --platform linux/amd64 -t "$IMAGE" --push .

echo
echo "Done! On Unraid > Docker > Add Container, use:"
echo "  Repository:  $IMAGE"
echo "  Port:        8080 -> 8080"
echo "  Path:        /data -> /mnt/user/appdata/transcriber-2000   (required: keeps your settings across updates)"
echo "  Variable:    WHISPER_URL = http://<unraid-ip>:9000"
pause
