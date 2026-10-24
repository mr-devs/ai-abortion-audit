#!/usr/bin/env bash
#
# Purpose:
#     Run the three pilot-4cities audits with taxman, then resolve the Gemini
#     citation links, so all data collection for this pilot happens at once.
#
# Notes:
#     - The three providers (one audit each) run in parallel; `wait` holds the
#       script until all three finish.
#     - Each audit sends every message in
#       taxman/messages/pilot-4cities-queries.txt once (repeats: 1).
#     - Each collect's console output (log path, ok/error counts, any error
#       message) goes to its own file under data/logs/run_pilot_4cities_audits/
#       and is printed once all three finish. Three progress bars in one
#       terminal would overwrite each other, and taxman leaves the bar out when
#       its output is not a terminal. To watch a run's progress, follow its
#       taxman log (`tail -f data/logs/taxman/<audit>/<run_id>.log`).
#     - Re-running this script is safe: taxman 0.2.0 finishes each audit's
#       latest run, sending only the responses that are missing or failed, and
#       sends nothing for an audit whose run is complete. resolve_gemini_urls.py
#       likewise skips responses already resolved.
#     - taxman handles everything else: each run writes its own responses,
#       manifest, and log.
#
# Input:
#     - taxman/audits/pilot-4cities-<provider>.yaml: the three audit files.
#     - The API keys named in each audit's `api_key_env` must be set.
#
#     Usage (from anywhere):
#         bash code/data_collection/run_pilot_4cities_audits.sh
#
# Output:
#     - data/raw/audits/<audit>/<run_id>/: responses.jsonl and manifest.json;
#       the Gemini run directory also gets resolved_urls.jsonl.
#     - data/logs/taxman/<audit>/<run_id>.log: each run's log.
#     - data/logs/run_pilot_4cities_audits/<yyyymmddThhmmss>-<audit>.txt: each
#       collect's console output.
#     - data/logs/resolve_gemini_urls/<yyyy-mm-dd>.log: the resolver's log.
#
# Author: Matthew DeVerna

# Run from the project root (two levels up), where taxman.yaml lives.
cd "$(dirname "$0")/../.." || exit 1

CONSOLE_DIR="data/logs/run_pilot_4cities_audits"
STARTED="$(date +%Y%m%dT%H%M%S)"
mkdir -p "${CONSOLE_DIR}"

echo ""
echo "--- Starting pilot-4cities audits ---"
echo ""

for provider in anthropic gemini openai; do
    audit="pilot-4cities-${provider}"
    uv run taxman collect "${audit}" > "${CONSOLE_DIR}/${STARTED}-${audit}.txt" 2>&1 &
    echo "Started ${audit} ..."
done
wait
echo ""

for provider in anthropic gemini openai; do
    audit="pilot-4cities-${provider}"
    echo "=== ${audit} ==="
    cat "${CONSOLE_DIR}/${STARTED}-${audit}.txt"
    echo ""
done
echo "--- Finished pilot-4cities audits ---"
echo ""

echo "--- Resolving Gemini citation links ---"
uv run python code/data_collection/resolve_gemini_urls.py --audit-prefix pilot-4cities-
echo "--- Finished resolving Gemini citation links ---"
echo ""
