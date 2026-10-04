#!/usr/bin/env bash
#
# Purpose:
#     Run every pilot audit with taxman, one location group at a time.
#
# Notes:
#     - Audits are grouped by location: base (no location in the queries), then
#       houston-tx, then portland-or. Within a group, the three providers run in
#       parallel; `wait` holds the next group until all three finish. This way
#       no provider ever has more than one of these audits running against it.
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
#     - data/raw/audits/<audit>/<run_id>/: responses.jsonl and manifest.json.
#     - data/logs/taxman/<audit>/<run_id>.log: each run's log.
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
