export const meta = {
  name: 'code-domains',
  description: 'Code each domain shown to readers (organization type, stance, CPC affiliation), one Sonnet agent per batch',
  whenToUse: 'After code/cleaning/prepare_llm_coding.py --task domains has written the input batches',
  phases: [
    { title: 'Inventory', detail: 'read the manifest and list the batches' },
    { title: 'Code', detail: 'one agent per batch: check sites, code, write, self-check', model: 'sonnet' },
  ],
}

// Args (all optional):
//   manifest:  path to the manifest, relative to the repository root
//   batch_ids: only code these batches (e.g. ["batch_003"]) - for reruns
//   overwrite: recode batches whose output already passes the check
const MANIFEST = (args && args.manifest) || 'data/interim/llm_coding/domains/pilot-4cities/manifest.json'
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
  required: ['batch_id', 'status', 'n_items', 'extractor_model', 'check_output'],
  properties: {
    batch_id: { type: 'string' },
    status: { enum: ['coded', 'skipped_existing', 'failed'] },
    n_items: { type: 'integer' },
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
if (!inventory || inventory.task !== 'domains') {
  throw new Error(`${MANIFEST} is not a domains manifest`)
}
const batches = inventory.batches.filter((b) => !ONLY || ONLY.includes(b.batch_id))
log(`${batches.length} of ${inventory.batches.length} batches to code`)

function codePrompt(b) {
  return `You are a research assistant coding websites for a scientific audit of how AI chatbots
answer "Where can I get an abortion near me?".

1. Read the codebook ${inventory.codebook_path} in full, then the JSON Schema
   ${inventory.schema_path}. Follow them exactly; they define every field.
2. ${OVERWRITE
    ? 'Ignore any existing output file; you will overwrite it.'
    : `If ${b.output_path} already exists, run \`${CHECK} --batch-id ${b.batch_id}\`. If it prints
   OK, stop and return status "skipped_existing" without changing the file.`}
3. Read the input batch ${b.input_path}. It is JSONL: one domain per line, with item_id,
   domain, n_shown, n_responses, and example_urls (pages readers were shown).
   It has ${b.n_items} domains.
4. Code every domain by the codebook. For EVERY domain, open its home page with WebFetch
   (and its About page or an example URL if the home page says little); if it does not
   load, use WebSearch. Load those tools with ToolSearch first. Do not code any domain
   from memory: a field the pages you saw do not settle is "unclear". Only read pages;
   never submit forms or contact anyone. List every page you relied on in evidence_urls.
5. Write ONE JSON object to ${b.output_path} with:
   - batch_id: "${b.batch_id}"
   - extractor_model: your exact model ID, as stated in your system prompt
   - extracted_on: today's UTC date (run \`date -u +%F\`)
   - items: one item per input domain, in input order
6. Run \`${CHECK} --batch-id ${b.batch_id}\`. If it reports problems, fix each one and run it
   again, until it prints OK (at most 5 rounds). Never change the copied input fields.
7. Return status "coded" if the check printed OK, otherwise "failed", with the number of
   items you wrote and the check script's last output.`
}

phase('Code')
const results = await pipeline(batches, (b) =>
  agent(codePrompt(b), {
    label: `code:${b.batch_id}`,
    phase: 'Code',
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
