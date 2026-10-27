#!/usr/bin/env bash
# Build and publish an immutable multi-architecture release image.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="${REGISTRY:-gitea.arrowwood.top:8773}"
IMAGE_NAME="${IMAGE_NAME:-claude/agv-pm}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
VERSION="$(node -p "require('$PROJECT_DIR/frontend/package.json').version")"
IMAGE="$REGISTRY/$IMAGE_NAME:$VERSION"

cd "$PROJECT_DIR"
[ -z "$(git status --porcelain)" ] || {
  echo "Working tree must be clean before publishing." >&2
  exit 1
}

HEAD="$(git rev-parse HEAD)"
TAG_HEAD="$(git rev-parse "v$VERSION^{}" 2>/dev/null || true)"
[ "$HEAD" = "$TAG_HEAD" ] || {
  echo "Tag v$VERSION must exist and point to HEAD before publishing." >&2
  exit 1
}

"$SCRIPT_DIR/release-check.sh"

docker buildx build \
  --platform "$PLATFORMS" \
  --build-arg "APP_VERSION=$VERSION" \
  --label "org.opencontainers.image.version=$VERSION" \
  --label "org.opencontainers.image.revision=$HEAD" \
  -f docker/Dockerfile \
  -t "$IMAGE" \
  --push .

docker buildx imagetools inspect "$IMAGE"
echo "Published immutable image: $IMAGE"
