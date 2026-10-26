#!/usr/bin/env bash
# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

# End-to-end test: COSMOS Core + this plugin against a running fprime-test container.
#
#   fprime-test/e2e.sh PLUGIN.gem HEADERS PROCEDURE SUITE
#
#   PLUGIN.gem  the built plugin (rake build VERSION=...)
#   HEADERS     the plugin's fprime_headers variable: SPACE_PACKET or SPACE_PACKET_ONLY
#   PROCEDURE   e.g. FPRIME/procedures/tlm_test.py
#   SUITE       e.g. TlmSuite
#
# The fprime-test container must already be listening on host port 50000. COSMOS comes from
# OpenC3/cosmos-project, cloned into COSMOS_DIR if missing. That checkout is disposable: every run
# deletes its stack and volumes (docker compose down -v) so the plugin is always a fresh install, and
# overwrites its compose.override.yaml. COSMOS listens on COSMOS_PORT (default 2900); set another port
# to run beside an existing COSMOS. SUITE_TIMEOUT (default 900 s) caps the suite. Exits non-zero
# unless the suite ran at least one test and none failed.

set -euo pipefail

GEM=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
HEADERS=$2
PROCEDURE=$3
SUITE=$4
COSMOS_DIR=${COSMOS_DIR:-$PWD/cosmos-project}
COSMOS_PORT=${COSMOS_PORT:-2900}
API=http://localhost:$COSMOS_PORT/openc3-api
export OPENC3_API_PASSWORD=${OPENC3_API_PASSWORD:-fprime-e2e-password}
OUT=${OUT:-$PWD/e2e-results}
mkdir -p "$OUT"

if [ ! -d "$COSMOS_DIR" ]; then
  git clone --depth 1 https://github.com/OpenC3/cosmos-project "$COSMOS_DIR"
fi
cd "$COSMOS_DIR"
{
  echo "services:"
  echo "  openc3-cosmos-init:"
  echo "    environment:"
  echo "      - OPENC3_DEMO=false"
  if [ "$COSMOS_PORT" != 2900 ]; then
    # Beside another COSMOS, publish only the API: the other host ports would collide
    echo "  openc3-operator:"
    echo "    ports: !reset []"
    echo "  openc3-traefik:"
    echo "    ports: !override"
    echo "      - \"127.0.0.1:$COSMOS_PORT:2900\""
  fi
} > compose.override.yaml

# openc3.sh cli uses -it, which needs a terminal; CI has none. These are the IDs openc3.sh
# exports for a rootful Docker; --user=root makes them moot for the CLI container itself.
export OPENC3_USER_ID=${OPENC3_USER_ID:-$(id -u)} OPENC3_GROUP_ID=${OPENC3_GROUP_ID:-$(id -g)}
cli() {
  docker compose run --rm -T --user=root -v "$(dirname "$GEM"):/openc3/local:z" -w /openc3/local \
    -e OPENC3_API_PASSWORD --no-deps openc3-cosmos-cmd-tlm-api ruby /openc3/bin/openc3cli "$@"
}

wait_for() {
  local description=$1 seconds=$2
  shift 2
  local end=$((SECONDS + seconds))
  until "$@" > /dev/null 2>&1; do
    if [ $SECONDS -ge $end ]; then
      echo "Timed out after ${seconds}s waiting for $description" >&2
      return 1
    fi
    sleep 5
  done
  echo "$description: ready"
}

# Same-version plugin loads are skipped, variables included, so never reuse a previous run's stack.
# COSMOS also saves installed plugins (with their variables) under plugins/, a host folder that
# down -v keeps and init reinstalls from, so clear that too.
docker compose down -v
git clean -fdxq -- plugins
./openc3.sh run
wait_for "COSMOS API" 600 curl -sf "$API/ping"
# Plugins (and the script runner) are only usable once openc3-cosmos-init has finished
# shellcheck disable=SC2016 # expanded by sh -c on each poll
wait_for "COSMOS init" 600 sh -c '[ "$(docker inspect -f "{{.State.Status}}" "$(docker compose ps -aq openc3-cosmos-init)")" = exited ]'

# A fresh Core install has no password: the first set needs no old password
TOKEN=$(curl -sf -X POST "$API/auth/set" -H 'Content-Type: application/json' \
  -d "{\"password\": \"$OPENC3_API_PASSWORD\"}")

echo "{\"fprime_hostname\": \"host.docker.internal\", \"fprime_headers\": \"$HEADERS\"}" \
  > "$(dirname "$GEM")/e2e-variables.json"
cli load "$(basename "$GEM")" --variables e2e-variables.json

interface_state() {
  curl -sf "$API/api" -H "Authorization: $TOKEN" -H 'Content-Type: application/json-rpc' \
    -d '{"jsonrpc": "2.0", "method": "get_interface", "params": ["FPRIME_INT"], "keyword_params": {"scope": "DEFAULT"}, "id": 1}' \
    | grep -q '"state":"CONNECTED"'
}
wait_for "FPRIME_INT connected" 300 interface_state

# The text report keeps each failure's traceback (CTRF drops them); its summary ends with
# "Total Tests: N", "Pass: N", "Skip: N" and "Fail: N" lines. --wait caps a hung suite (it
# detaches and exits non-zero); the stack is thrown away next run anyway.
cli script run "$PROCEDURE" --suite "$SUITE" --wait "${SUITE_TIMEOUT:-900}" | tee "$OUT/script-output.txt"
python3 - "$OUT/script-output.txt" <<'EOF'
import re, sys
report = open(sys.argv[1]).read()
counts = {name: int(value) for name, value in re.findall(r"^(Total Tests|Pass|Skip|Fail): (\d+)$", report, re.M)}
print(f"Suite summary: {counts}")
sys.exit(0 if counts.get("Total Tests") and counts.get("Fail") == 0 else 1)
EOF
