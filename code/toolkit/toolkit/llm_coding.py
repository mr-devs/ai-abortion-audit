"""
Batching and validation for the coding tasks that agents and human coders
do from a codebook: extracting recommended places from responses, and coding
the domains shown to readers.
"""

import json
import random
import re
from pathlib import Path

from jsonschema import Draft202012Validator

#: Characters that differ between a response and a faithful copy of it
#: without changing the words: curly quotes and markdown emphasis.
QUOTE_TRANSLATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
EMPHASIS_PATTERN = re.compile(r"[*_`]+")
WHITESPACE_PATTERN = re.compile(r"\s+")

#: Item fields copied unchanged from each task's input record; the check
#: confirms the coder did not alter them.
ECHO_FIELDS = {
    "places": ("item_id", "query_city", "query_state_abbr"),
    "domains": ("item_id", "domain"),
}

#: Place-extraction fields that must appear in the response text.
PLACE_ITEM_VERBATIM = ("follow_up_request_verbatim", "state_law_quote_verbatim")
PLACE_ENTITY_VERBATIM = (
    "name_verbatim",
    "services_verbatim",
    "address_verbatim",
    "website_verbatim",
    "distance_claim_verbatim",
    "caveat_verbatim",
    "evidence_quote",
)


def normalize_for_match(text):
    """
    Return text with formatting differences removed, for checking that a
    copied span appears in a response.

    Parameters
    ----------
    text : str
        A response, or a span copied from it.

    Returns
    -------
    str
        The text with curly quotes made straight, markdown emphasis markers
        (``*``, ``_``, backticks) removed, and runs of whitespace collapsed
        to one space.
    """
    text = text.translate(QUOTE_TRANSLATION)
    text = EMPHASIS_PATTERN.sub("", text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def write_batches(records, out_dir, batch_size, seed):
    """
    Shuffle records into batches and write one JSONL input file per batch.

    Records are shuffled with a fixed seed so each batch mixes providers and
    cities, and the same seed always gives the same batches.

    Parameters
    ----------
    records : list of dict
        One input record per item; each must have an ``item_id``.
    out_dir : pathlib.Path
        Directory for the batch files (created if needed).
    batch_size : int
        Maximum number of records per batch.
    seed : int
        Seed for the shuffle.

    Returns
    -------
    list of dict
        One entry per batch: ``batch_id``, ``input_path`` (str), and
        ``item_ids`` (list of str), in batch order.
    """
    shuffled = list(records)
    random.Random(seed).shuffle(shuffled)
    out_dir.mkdir(parents=True, exist_ok=True)
    batches = []
    for start in range(0, len(shuffled), batch_size):
        chunk = shuffled[start : start + batch_size]
        batch_id = f"batch_{start // batch_size:03d}"
        path = out_dir / f"{batch_id}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for record in chunk:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        batches.append(
            {
                "batch_id": batch_id,
                "input_path": str(path),
                "item_ids": [r["item_id"] for r in chunk],
            }
        )
    return batches


def load_schema(path):
    """
    Load a JSON Schema file.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the schema.

    Returns
    -------
    dict
        The schema.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def problem(kind, message, item_id=None, entity_index=None):
    """
    Return one problem found in a coded batch.

    Parameters
    ----------
    kind : str
        "missing", "json", "schema", "ids", "verbatim", or "consistency"
        (see ``check_batch``).
    message : str
        What is wrong.
    item_id : str, optional
        The item the problem is in, if any.
    entity_index : int, optional
        The entity the problem is in, if any (place extraction only).

    Returns
    -------
    dict
        With keys kind, item_id, entity_index, and message.
    """
    return {"kind": kind, "item_id": item_id, "entity_index": entity_index, "message": message}


def format_problem(found):
    """
    Return a problem as one line of text.

    Parameters
    ----------
    found : dict
        A problem from ``check_batch``.

    Returns
    -------
    str
        E.g. "verbatim: r0001 entity 2: phone not found in the response: '555'".
    """
    where = " ".join(
        part
        for part in [
            found["item_id"],
            None if found["entity_index"] is None else f"entity {found['entity_index']}",
        ]
        if part
    )
    return f"{found['kind']}: {where + ': ' if where else ''}{found['message']}"


def _check_place_item(item, text):
    """
    Return the problems in one place-extraction item, other than the schema.

    Parameters
    ----------
    item : dict
        One item from a place-extraction batch.
    text : str
        The response text the item was extracted from.

    Returns
    -------
    list of dict
        Problems (see ``problem``) of kind "verbatim" or "consistency".
    """
    item_id = item["item_id"]
    problems = []
    haystack = normalize_for_match(text)

    def check_span(field, value, entity_index=None):
        if value is not None and normalize_for_match(value) not in haystack:
            problems.append(
                problem(
                    "verbatim",
                    f"{field} not found in the response: {value!r}",
                    item_id,
                    entity_index,
                )
            )

    for field in PLACE_ITEM_VERBATIM:
        check_span(field, item[field])

    entities = item["entities"]
    indexes = [e["entity_index"] for e in entities]
    if indexes != list(range(1, len(entities) + 1)):
        problems.append(
            problem("consistency", f"entity_index is not 1..{len(entities)}: {indexes}", item_id)
        )
    positions = []
    for entity in entities:
        index = entity["entity_index"]
        for field in PLACE_ENTITY_VERBATIM:
            check_span(field, entity[field], index)
        for phone in entity["phones_verbatim"]:
            check_span("phone", phone, index)
        if entity["role"] == "primary":
            if entity["list_position"] is None:
                problems.append(
                    problem("consistency", "primary entity with no list_position", item_id, index)
                )
            positions.append(entity["list_position"])
        elif entity["list_position"] is not None:
            problems.append(
                problem("consistency", "list_position on an entity that is not primary", item_id, index)
            )
    if len(positions) != len(set(positions)):
        problems.append(problem("consistency", f"repeated list_position: {positions}", item_id))
    has_place = any(e["role"] in ("primary", "alternative") for e in entities)
    if (item["answer_status"] == "places_provided") != has_place:
        problems.append(
            problem(
                "consistency",
                "answer_status places_provided must match having a primary or alternative entity",
                item_id,
            )
        )
    return problems


def check_item(task, item, record, schema=None):
    """
    Check one coded item against its input record.

    Parameters
    ----------
    task : str
        "places" or "domains".
    item : dict
        One coded item.
    record : dict
        The item's input record (with ``text`` for places).
    schema : dict, optional
        The task's JSON Schema. If given, the item is first validated against
        its item definition, and only schema problems are returned if any.

    Returns
    -------
    list of dict
        Problems (see ``problem``): "schema", "ids" (input fields altered),
        "verbatim", or "consistency".
    """
    if schema is not None:
        item_schema = {"$ref": "#/$defs/item", "$defs": schema["$defs"]}
        problems = [
            problem(
                "schema",
                f"{'/'.join(str(p) for p in e.absolute_path) or '<item>'}: {e.message}",
                item.get("item_id"),
            )
            for e in Draft202012Validator(item_schema).iter_errors(item)
        ]
        if problems:
            return problems
    problems = [
        problem("ids", f"{field} is {item[field]!r}, input has {record[field]!r}", item["item_id"])
        for field in ECHO_FIELDS[task]
        if item[field] != record[field]
    ]
    if task == "places":
        problems += _check_place_item(item, record["text"])
    return problems


def check_batch(task, input_path, output_path, schema):
    """
    Check one coded batch against its input and the task's schema.

    Parameters
    ----------
    task : str
        "places" or "domains".
    input_path : str or pathlib.Path
        The batch's JSONL input file.
    output_path : str or pathlib.Path
        The coded batch (JSON).
    schema : dict
        The task's JSON Schema.

    Returns
    -------
    list of dict
        Problems (see ``problem``), empty if the batch passes. kind is one of
        "missing" (no output file), "json", "schema", "ids" (items missing,
        extra, duplicated, or with altered input fields), "verbatim" (a
        copied span is not in the response), or "consistency". Schema
        problems are returned alone, because the other checks need a valid
        structure.
    """
    output_path = Path(output_path)
    if not output_path.exists():
        return [problem("missing", f"{output_path} does not exist")]
    try:
        batch = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [problem("json", f"{output_path} is not valid JSON: {error}")]

    problems = [
        problem("schema", f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}")
        for e in Draft202012Validator(schema).iter_errors(batch)
    ]
    if problems:
        return problems

    with open(input_path, encoding="utf-8") as f:
        inputs = {r["item_id"]: r for r in (json.loads(line) for line in f if line.strip())}
    expected_batch_id = Path(input_path).stem
    if batch["batch_id"] != expected_batch_id:
        problems.append(
            problem("ids", f"batch_id is {batch['batch_id']!r}, expected {expected_batch_id!r}")
        )

    seen = [item["item_id"] for item in batch["items"]]
    for item_id in sorted(set(inputs) - set(seen)):
        problems.append(problem("ids", "missing from the output", item_id))
    for item_id in sorted(set(seen) - set(inputs)):
        problems.append(problem("ids", "not in the batch input", item_id))
    for item_id in sorted({i for i in seen if seen.count(i) > 1}):
        problems.append(problem("ids", "appears more than once", item_id))

    for item in batch["items"]:
        record = inputs.get(item["item_id"])
        if record is not None:
            problems += check_item(task, item, record)
    return problems
