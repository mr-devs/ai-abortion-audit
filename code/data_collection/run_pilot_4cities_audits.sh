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
#       taxman/messages/pilot-4cities-queries.txt once (repeats: 1). That file
#       is written by write_4cities_messages.py.
#     - After the audits, resolve_gemini_urls.py resolves the Google redirect
#       URLs cited in the pilot-4cities Gemini run. It skips responses already
#       resolved, so re-running is safe.
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
#     - data/logs/resolve_gemini_urls/<yyyy-mm-dd>.log: the resolver's log.
#
# Author: Matthew DeVerna

# Run from the project root (two levels up), where taxman.yaml lives.
cd "$(dirname "$0")/../.." || exit 1

echo ""
echo "--- Starting pilot-4cities audits ---"
echo ""

for provider in anthropic gemini openai; do
    taxman collect "pilot-4cities-${provider}" &
    echo "Started pilot-4cities-${provider} ..."
done
wait
echo "--- Finished pilot-4cities audits ---"
echo ""

echo "--- Resolving Gemini citation links ---"
uv run python code/data_collection/resolve_gemini_urls.py --audit-prefix pilot-4cities-
echo "--- Finished resolving Gemini citation links ---"
echo ""
