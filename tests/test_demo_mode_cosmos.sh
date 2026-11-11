#!/usr/bin/env bash
# demo-mode must recover a Cosmos container that is running but never serves.
#
# Seen on the Thor 2026-11-11: after 21 days of uptime the GPU driver reported out of memory while vLLM allocated
# its KV cache, and the engine spun forever. demo-mode waited 900 s and gave up; the boot retries waited again on
# the same stuck container. Stopping and starting the container recovered it in about 90 s.
#
# Run: bash tests/test_demo_mode_cosmos.sh        (uses a fake `docker`; touches nothing real)
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/state"
# Everything above the command dispatch: the functions only.
sed -n '1,/^cmd=/p' "$HERE/deploy/thor/demo-mode" | sed '$d' > "$T/lib.sh"

cat > "$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
S="$FAKE_STATE"; echo "$*" >> "$S/calls"
case "$1" in
  inspect) name="${@: -1}"
           if [ "$name" = compose-vllm-1 ]; then [ -e "$S/running" ] && echo true || echo false; else echo false; fi ;;
  exec)    [ -e "$S/ready" ] ;;
  start)   touch "$S/running"; [ -e "$S/ready_after_start" ] && touch "$S/ready"; exit 0 ;;
  restart) echo restart >> "$S/restarts"; touch "$S/running"; [ -e "$S/ready_after_restart" ] && touch "$S/ready"; exit 0 ;;
  *)       exit 0 ;;
esac
STUB
printf '#!/usr/bin/env bash\nexit 0\n' > "$T/bin/sleep"      # deadlines are wall-clock, so the waits still end
chmod +x "$T/bin/docker" "$T/bin/sleep"

FAILED=0
scenario() {  # name, expected exit, expected restarts, state files to pre-create...
    local name=$1 want_rc=$2 want_restarts=$3; shift 3
    rm -rf "$T/state"; mkdir -p "$T/state"; for f in "$@"; do touch "$T/state/$f"; done
    ( export PATH="$T/bin:$PATH" FAKE_STATE="$T/state" VLLM_FIRST_TIMEOUT=2 VLLM_TIMEOUT=3 HOME="$T"
      . "$T/lib.sh"; ensure_vllm ) > "$T/out" 2>&1
    local rc=$? restarts=0
    [ -e "$T/state/restarts" ] && restarts=$(wc -l < "$T/state/restarts" | tr -d ' ')
    if [ "$rc" = "$want_rc" ] && [ "$restarts" = "$want_restarts" ]; then echo "  PASS  $name"
    else echo "  FAIL  $name - exit $rc (want $want_rc), restarts $restarts (want $want_restarts)"; sed 's/^/        /' "$T/out"; FAILED=$((FAILED + 1)); fi
}

scenario "already serving: nothing is restarted"                         0 0 running ready
scenario "stopped: started, serves, no restart"                          0 0 ready_after_start
scenario "running but never serving: one restart recovers it"            0 1 running ready_after_restart
scenario "stopped, started, never serves: one restart recovers it"       0 1 ready_after_restart
scenario "still not serving after the restart: fails, restarted once"    1 1 running

echo "$FAILED failed"; exit $((FAILED > 0))
