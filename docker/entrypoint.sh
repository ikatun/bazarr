#!/bin/sh
set -eu
case "${1:-serve}" in
  serve)
    if [ "$#" -gt 0 ]; then shift; fi
    exec python /app/bazarr.py --config "${BAZARR_CONFIG_DIR:-/config}" --port 6767 --no-update "$@"
    ;;
  scan-ambiguity)
    shift
    # Separate metadata worker: no access to media and no subtitle downloads.
    while :; do
      if [ -f "${BAZARR_CONFIG_DIR:-/config}/db/bazarr.db" ]; then
        python /app/tests/scan_ambiguity.py --limit 25 "$@" || echo 'Ambiguity refresh failed; retrying next batch' >&2
      fi
      sleep 300
    done
    ;;
  *) exec "$@" ;;
esac
