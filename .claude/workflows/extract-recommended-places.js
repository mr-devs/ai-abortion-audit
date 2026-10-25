export const meta = {
  name: 'extract-recommended-places',
  description: 'Extract the places and resources each audit response recommends, one Sonnet agent per batch',
  whenToUse: 'After code/cleaning/prepare_llm_coding.py --task places has written the input batches',
  phases: [
    { title: 'Inventory', detail: 'read the manifest and list the batches' },
    { title: 'Extract', detail: 'one agent per batch: code, write, self-check', model: 'sonnet' },
  ],
}

// Args (all optional):
//   manifest:  path to the manifest, relative to the repository root
//   batch_ids: only code these batches (e.g. ["batch_003"]) - for reruns
//   overwrite: recode batches whose output already passes the check
const MANIFEST = (args && args.manifest) || 'data/interim/llm_coding/places/pilot-4cities/manifest.json'
const ONLY = (args && args.batch_ids) || null
const OVERWRITE = Boolean(args && args.overwrite)
const CHECK = `uv run python code/cleaning/check_coding_batch.py --manifest ${MANIFEST}`

const INVENTORY_SCHEMA = {
  type: 'object',
  required: ['task', 'codebook_path', 'schema_path', 'batches'],
  properties: {
    task: { type: 'string' },
    codebook_path: { type: 'string' },
    schema_path: { type: 'string' },
    batches: {
      type: 'array',
      items: {
        type: 'object',
        required: ['batch_id', 'input_path', 'output_path', 'n_items'],
        properties: {
          batch_id: { type: 'string' },
          input_path: { type: 'string' },
          output_path: { type: 'string' },
          n_items: { type: 'integer' },
        },
      },
    },
  },
}

const RESULT_SCHEMA = {
  type: 'object',
  required: ['batch_id', 'status', 'n_items', 'n_entities', 'extractor_model', 'check_output'],
  properties: {
    batch_id: { type: 'string' },
    status: { enum: ['coded', 'skipped_existing', 'failed'] },
    n_items: { type: 'integer' },
    n_entities: { type: 'integer' },
    extractor_model: { type: 'string' },
    check_output: { type: 'string', description: 'The last output of the check script' },
  },
}

phase('Inventory')
const inventory = await agent(
  `Read the JSON file ${MANIFEST} (a coding-task manifest). Return its task, codebook_path, ` +
    `schema_path, and, for every entry in its "batches" list, the batch_id, input_path, ` +
    `output_path, and the number of item_ids (n_items). Report the values exactly as written; ` +
    `do not change any file.`,
  { label: 'inventory', phase: 'Inventory', schema: INVENTORY_SCHEMA, effort: 'low' },
)
if (!inventory || inventory.task !== 'places') {
  throw new Error(`${MANIFEST} is not a places manifest`)
}
const batches = inventory.batches.filter((b) => !ONLY || ONLY.includes(b.batch_id))
log(`${batches.length} of ${inventory.batches.length} batches to code`)

function extractPrompt(b) {
  return `You are a research assistant extracting structured data from AI chatbot responses for a
scientific audit. Work only from the files named here; do not search the web or open links.

1. Read the codebook ${inventory.codebook_path} in full, then the JSON Schema
   ${inventory.schema_path}. Follow them exactly; they define every field.
2. ${OVERWRITE
    ? 'Ignore any existing output file; you will overwrite it.'
    : `If ${b.output_path} already exists, run \`${CHECK} --batch-id ${b.batch_id}\`. If it prints
   OK, stop and return status "skipped_existing" without changing the file.`}
3. Read the input batch ${b.input_path}. It is JSONL: one response per line, with item_id,
   query_city, query_state_abbr, message (the question asked), and text (the response).
   It has ${b.n_items} responses.
4. Code every response by the codebook. Record what the response says, never what you
   believe is true. Copy verbatim fields character for character from the text.
5. Write ONE JSON object to ${b.output_path} with:
   - batch_id: "${b.batch_id}"
   - extractor_model: your exact model ID, as stated in your system prompt
   - extracted_on: today's UTC date (run \`date -u +%F\`)
   - items: one item per input response, in input order
6. Run \`${CHECK} --batch-id ${b.batch_id}\`. If it reports problems, fix each one by
   re-reading the response and editing the output, then run it again, until it prints OK
   (at most 5 rounds). Never change the copied input fields to pass the check, and never
   invent text: if a verbatim span cannot be found, copy a shorter span that does appear,
   or use null where the codebook allows it.
7. Return status "coded" if the check printed OK, otherwise "failed", with the number of
   items and entities you wrote and the check script's last output.`
}

phase('Extract')
const results = await pipeline(batches, (b) =>
  agent(extractPrompt(b), {
    label: `extract:${b.batch_id}`,
    phase: 'Extract',
    schema: RESULT_SCHEMA,
    model: 'sonnet',
  }),
)

// A batch that failed its check, or whose agent died (null), is rerun by
// passing failed_batch_ids back as args.batch_ids.
const done = results.filter(Boolean)
const failed = batches
  .map((b) => b.batch_id)
  .filter((id) => !done.some((r) => r.batch_id === id && r.status !== 'failed'))
log(`${batches.length - failed.length} batches passed; ${failed.length} failed or did not finish`)
return { manifest: MANIFEST, results: done, failed_batch_ids: failed }
