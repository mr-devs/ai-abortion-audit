#!/usr/bin/env bash
#
# Purpose:
#     Run every pilot audit with taxman, one location group at a time, then
#     resolve the Gemini citation links, so all data collection for this pilot
#     happens at once.
#
# Notes:
#     - Audits are grouped by location: base (no location in the queries), then
#       houston-tx, then portland-or. Within a group, the three providers run in
#       parallel; `wait` holds the next group until all three finish. This way
#       no provider ever has more than one of these audits running against it.
#     - After the last group, resolve_gemini_urls.py resolves the Google
#       redirect URLs cited in the Gemini runs. Its prefix, "pilot-gemini",
#       matches these three Gemini audits but not pilot-4cities-gemini. It
#       skips responses already resolved, so re-running is safe.
#     - taxman handles everything else: each run writes its own responses,
#       manifest, and log.
#
# Input:
#     - taxman/audits/pilot-<provider>[-<location>].yaml: the nine audit files.
#     - The API keys named in each audit's `api_key_env` must be set.
#
#     Usage (from anywhere):
#         bash code/data_collection/run_pilot_audits.sh
#
# Output:
#     - data/raw/audits/<audit>/<run_id>/: responses.jsonl and manifest.json;
#       Gemini run directories also get resolved_urls.jsonl.
#     - data/logs/taxman/<audit>/<run_id>.log: each run's log.
#     - data/logs/resolve_gemini_urls/<yyyy-mm-dd>.log: the resolver's log.
#
# Author: Matthew DeVerna

# Run from the project root (two levels up), where taxman.yaml lives.
cd "$(dirname "$0")/../.." || exit 1

echo ""
echo "--- Starting pilot audits ---"
echo ""

for suffix in "" "-houston-tx" "-portland-or"; do
    for provider in anthropic gemini openai; do
        taxman collect "pilot-${provider}${suffix}" &
        echo "Started pilot-${provider}${suffix} ..."
    done
    wait
    echo "--- Finished pilot audits for ${suffix:-base} ---"
    echo ""
done

echo "--- Resolving Gemini citation links ---"
uv run python code/data_collection/resolve_gemini_urls.py --audit-prefix pilot-gemini
echo "--- Finished resolving Gemini citation links ---"
echo ""
