#!/bin/bash
# Reset the api service's data by scope.
# Usage:
#   docker compose exec api bash /app/reset.sh
#   cd api && bash reset.sh structured
#   cd api && bash reset.sh all --yes

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCOPE="${1:-all}"
shift || true

python3 "$SCRIPT_DIR/scripts/reset_data.py" --scope "$SCOPE" "$@"

echo "If the service is already running, restart it to refresh in-memory state:"
echo "  docker compose restart api"
