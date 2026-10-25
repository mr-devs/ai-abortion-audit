"""
Purpose:
    Let a human coder code the sampled items of a codebook coding task blind,
    in the terminal, writing each finished item to disk at once so coding can
    stop and restart at any time.

Notes:
    Blind coding:
    - The coder sees only what the agents saw: for places, the query and
      the response text; for domains, the domain and the pages readers were
      shown. The agents' codes are never shown. Agreement between coders and
      agents is computed afterwards.
    - Prompts follow the task's JSON Schema and codebook (the same files the
      agents follow): the allowed values come from the schema, and each
      field's definition is printed from the codebook. Read the codebook in
      full before the first session.
    - Every answer is checked as it is entered: values must fit the schema,
      and spans marked "verbatim" (and the evidence quote) must appear in the
      response text, ignoring curly quotes, markdown emphasis, and spacing;
      copy them from the text shown. When an item is done, the same item
      checks the agents pass (toolkit.llm_coding.check_item) run; the coder
      can redo the item or save it with the problems recorded.

    Commands (at any prompt):
    - ":t" shows the response text (or domain details) again.
    - ":h" shows the current field's definition again.
    - ":r" restarts the current item.
    - ":q" quits; the current item is not saved. Finished items are kept.
    - For a field that allows it, Enter (or "-") leaves it empty (null).

    Saving and restarting:
    - Each finished item is appended to the coder's file and flushed to disk
      immediately. On restart the script skips the items already in the
      file and continues with the next one, in the sample's order.
    - To fix a saved item, run with --recode <item_id>; the new coding is
      appended, and the latest record of an item is the one that counts.
    - The codebook and schema must match the hashes in the task manifest,
      so coders and agents use the same instructions.

Input:
    - data/interim/human_coding/<task>/<study>/sample.json, from
      code/cleaning/sample_for_human_coding.py.
    - The task manifest and input batches in data/interim/llm_coding/, and
      the codebook and schema in code/cleaning/codebooks/.
    - --task (required): "places" or "domains".
    - --coder (required): the coder's initials, 2-4 lowercase letters.
    - --study (optional): default "pilot-4cities".
    - --recode (optional): an item_id to code again.

    Usage (from anywhere):
        uv run python code/data_collection/human_code.py --task places --coder md

Output:
    - data/raw/human_coding/<task>/<study>/<coder>.jsonl: one JSON record
      per coded item, appended as each item is finished, with keys:
        - item_id (str), coder (str).
        - coded_at (str): UTC time the item was saved, ISO 8601.
        - seconds (float): time spent on the item.
        - codebook_sha256 (str): the codebook's hash.
        - check_problems (list of str): problems the final check found that
          the coder chose to save anyway; empty if none.
        - item (dict): the coding, in exactly the form of an item in the
          agents' coded batches (see the task's schema).

Author: Matthew DeVerna
"""

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from toolkit.llm_coding import (
    ECHO_FIELDS,
    PLACE_ENTITY_VERBATIM,
    PLACE_ITEM_VERBATIM,
    check_item,
    format_problem,
    load_schema,
    normalize_for_match,
)

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
REPO_ROOT = Path("../..")
SAMPLE_DIR = REPO_ROOT / "data/interim/human_coding"
OUTPUT_DIR = REPO_ROOT / "data/raw/human_coding"
CODER_PATTERN = re.compile(r"^[a-z]{2,4}$")
TEXT_WIDTH = 100

# Codebook bullets: a field ("- `name` (type): definition", possibly several
# names) and, indented under it, one allowed value ("  - `value`: meaning").
FIELD_PATTERN = re.compile(r"^- ((?:`\w+`(?:, )?)+)(?: \([^)]*\))?:\s*(.*)$")
VALUE_PATTERN = re.compile(r"^  - `(\w+)`: (.*)$")
NAME_PATTERN = re.compile(r"`(\w+)`")


class Restart(Exception):
    """Raised when the coder asks to restart the current item."""


class Quit(Exception):
    """Raised when the coder asks to quit."""


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attributes ``task``, ``coder``, ``study``, and ``recode``.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("--task", required=True, choices=("places", "domains"))
    parser.add_argument("--coder", required=True)
    parser.add_argument("--study", default="pilot-4cities")
    parser.add_argument("--recode", default=None)
    args = parser.parse_args()
    if not CODER_PATTERN.match(args.coder):
        parser.error("--coder must be 2-4 lowercase letters (your initials)")
    return args


def parse_codebook(path):
    """
    Read each field's definition and its values' meanings from a codebook.

    Parameters
    ----------
    path : pathlib.Path
        The codebook (markdown).

    Returns
    -------
    dict
        {field: {"definition": str, "values": {value: meaning}}}.
    """
    fields, current = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        field = FIELD_PATTERN.match(line)
        value = VALUE_PATTERN.match(line)
        if field:
            current = NAME_PATTERN.findall(field.group(1))
            for name in current:
                fields[name] = {"definition": field.group(2), "values": {}}
        elif value and current:
            for name in current:
                fields[name]["values"][value.group(1)] = value.group(2)
        elif not line.startswith("  "):
            current = []
    return fields


class Prompter:
    """
    Asks for one field at a time, checking each answer against the schema.

    Parameters
    ----------
    schema : dict
        The task's JSON Schema.
    codebook : dict
        Field definitions from ``parse_codebook``.
    show_source : callable
        Prints the item's source material (for the ":t" command).
    """

    def __init__(self, schema, codebook, show_source):
        self.defs = schema["$defs"]
        self.codebook = codebook
        self.show_source = show_source

    def resolve(self, prop):
        """Return a property schema with a top-level $ref followed."""
        ref = prop.get("$ref")
        return self.defs[ref.split("/")[-1]] if ref else prop

    def read(self, prompt, field):
        """Read one line, handling the commands."""
        while True:
            try:
                answer = input(prompt).strip()
            except EOFError:
                raise Quit
            if answer == ":q":
                raise Quit
            if answer == ":r":
                raise Restart
            if answer == ":t":
                self.show_source()
            elif answer == ":h":
                self.explain(field)
            else:
                return answer

    def explain(self, field):
        """Print a field's definition from the codebook."""
        entry = self.codebook.get(field)
        if entry:
            print(
                textwrap.fill(
                    f"{field}: {entry['definition']}",
                    TEXT_WIDTH,
                    subsequent_indent="  ",
                )
            )

    def valid(self, prop, value):
        """Return the schema's complaint about a value, or None."""
        schema = {**self.resolve(prop), "$defs": self.defs}
        errors = list(Draft202012Validator(schema).iter_errors(value))
        return errors[0].message if errors else None

    def ask(self, field, prop, verbatim_text=None, default=None):
        """
        Ask for one field's value until the answer is valid.

        Parameters
        ----------
        field : str
            The field name.
        prop : dict
            Its schema.
        verbatim_text : str, optional
            If given, a string answer must appear in this text.
        default : optional
            The value Enter gives for a required string (shown in brackets).

        Returns
        -------
        object
            The value.
        """
        prop = self.resolve(prop)
        print()
        self.explain(field)
        types = prop.get("type", [])
        types = types if isinstance(types, list) else [types]
        nullable = "null" in types

        if "enum" in prop:
            options = prop["enum"]
            meanings = self.codebook.get(field, {}).get("values", {})
            for i, option in enumerate(options, start=1):
                meaning = meanings.get(option, "")
                print(
                    textwrap.fill(
                        f"  {i}. {option}" + (f": {meaning}" if meaning else ""),
                        TEXT_WIDTH,
                        subsequent_indent="       ",
                    )
                )
            while True:
                answer = self.read(f"{field} [1-{len(options)}]: ", field)
                if answer.isdigit() and 1 <= int(answer) <= len(options):
                    return options[int(answer) - 1]
                if answer in options:
                    return answer
                print("  Enter one of the numbers above.")

        if "boolean" in types:
            while True:
                answer = self.read(f"{field} [y/n]: ", field).lower()
                if answer in ("y", "n"):
                    return answer == "y"
                print("  Enter y or n.")

        if "array" in types:
            values = []
            print("  Enter one per line; an empty line ends the list.")
            while True:
                answer = self.read(f"{field} #{len(values) + 1}: ", field)
                if not answer:
                    problem = self.valid(prop, values)
                    if problem is None:
                        return values
                    print(f"  {problem}")
                    continue
                if verbatim_text is not None and not self.found(answer, verbatim_text):
                    continue
                values.append(answer)

        while True:
            hint = (
                f" [{default}]"
                if default is not None
                else (" [Enter = empty]" if nullable else "")
            )
            answer = self.read(f"{field}{hint}: ", field)
            if answer in ("", "-"):
                if default is not None and answer == "":
                    value = default
                elif nullable:
                    return None
                else:
                    print("  This field is required.")
                    continue
            elif "integer" in types:
                if not answer.isdigit():
                    print("  Enter a whole number.")
                    continue
                value = int(answer)
            else:
                value = answer
            problem = self.valid(prop, value)
            if problem:
                print(f"  {problem}")
                continue
            if (
                isinstance(value, str)
                and verbatim_text is not None
                and not self.found(value, verbatim_text)
            ):
                continue
            return value

    @staticmethod
    def found(value, text):
        """Return whether a span appears in the text, telling the coder if not."""
        if normalize_for_match(value) in normalize_for_match(text):
            return True
        print(
            '  Not found in the response text. Copy it exactly (":t" shows the text).'
        )
        return False


def code_place(record, prompter, schema):
    """
    Code one response for the places task.

    Parameters
    ----------
    record : dict
        The input record (query and response text).
    prompter : Prompter
        The prompter.
    schema : dict
        The places schema.

    Returns
    -------
    dict
        One coded item.
    """
    item_props = schema["$defs"]["item"]["properties"]
    entity_props = schema["$defs"]["entity"]["properties"]
    text = record["text"]
    item = {field: record[field] for field in ECHO_FIELDS["places"]}

    for field in schema["$defs"]["item"]["required"]:
        if field in item or field == "entities":
            continue
        if field == "follow_up_request_verbatim" and not item["asks_follow_up"]:
            item[field] = None
        elif (
            field == "state_law_quote_verbatim"
            and item["state_law_claim"] == "not_stated"
        ):
            item[field] = None
        else:
            verbatim = text if field in PLACE_ITEM_VERBATIM else None
            item[field] = prompter.ask(field, item_props[field], verbatim_text=verbatim)
        if field == "mentions_financial_help":
            # Entities come before the closing notes field.
            item["entities"] = code_entities(text, prompter, schema, entity_props)
    return {field: item[field] for field in schema["$defs"]["item"]["required"]}


def code_entities(text, prompter, schema, entity_props):
    """
    Code every entity in a response, in order of first appearance.

    Parameters
    ----------
    text : str
        The response text.
    prompter : Prompter
        The prompter.
    schema : dict
        The places schema.
    entity_props : dict
        The entity property schemas.

    Returns
    -------
    list of dict
        The entities.
    """
    entities = []
    address_parts = ("street", "city", "state_abbr", "zip")
    while True:
        print(f"\n--- Entities so far: {len(entities)}")
        for e in entities:
            print(
                f"  {e['entity_index']}. {e['name_verbatim']} ({e['role']}, {e['entity_type']})"
            )
        more = prompter.ask("add_entity", {"type": "boolean"})
        if not more:
            return entities
        entity = {"entity_index": len(entities) + 1}
        for field in schema["$defs"]["entity"]["required"]:
            if field in entity:
                continue
            if field == "list_position" and entity["role"] != "primary":
                entity[field] = None
            elif field == "address_parts_from_context" and not any(
                entity[p] for p in address_parts
            ):
                entity[field] = False
            elif field == "evidence_quote":
                entity[field] = prompter.ask(
                    field,
                    entity_props[field],
                    verbatim_text=text,
                    default=entity["name_verbatim"],
                )
            else:
                verbatim = (
                    text
                    if field in PLACE_ENTITY_VERBATIM or field == "phones_verbatim"
                    else None
                )
                entity[field] = prompter.ask(
                    field, entity_props[field], verbatim_text=verbatim
                )
        entities.append(entity)


def code_domain(record, prompter, schema):
    """
    Code one domain.

    Parameters
    ----------
    record : dict
        The input record (domain and example URLs).
    prompter : Prompter
        The prompter.
    schema : dict
        The domains schema.

    Returns
    -------
    dict
        One coded item.
    """
    props = schema["$defs"]["item"]["properties"]
    item = {field: record[field] for field in ECHO_FIELDS["domains"]}
    for field in schema["$defs"]["item"]["required"]:
        if field not in item:
            item[field] = prompter.ask(field, props[field])
    return item


def show_place(record, position, total):
    """Print a response for coding, with numbered lines."""
    print("\n" + "=" * TEXT_WIDTH)
    print(f"Item {position} of {total}: {record['item_id']}")
    print(f"Query: {record['message']}")
    print("-" * TEXT_WIDTH)
    lines = []
    for paragraph in record["text"].splitlines():
        lines += textwrap.wrap(paragraph, TEXT_WIDTH - 6) or [""]
    for number, line in enumerate(lines, start=1):
        print(f"{number:>4}  {line}")
    print("=" * TEXT_WIDTH)


def show_domain(record, position, total):
    """Print a domain for coding."""
    print("\n" + "=" * TEXT_WIDTH)
    print(f"Item {position} of {total}: {record['item_id']}")
    print(
        f"Domain: {record['domain']}  (shown {record['n_shown']} times in {record['n_responses']} responses)"
    )
    print("Pages readers were shown:")
    for url in record["example_urls"]:
        print(f"  {url}")
    print(
        "Open the site in your browser and check who runs it before coding (see the codebook)."
    )
    print("=" * TEXT_WIDTH)


def load_inputs(manifest, item_ids):
    """
    Load the input records of the sampled items.

    Parameters
    ----------
    manifest : dict
        The task manifest.
    item_ids : list of str
        The sampled items.

    Returns
    -------
    dict
        {item_id: input record}.
    """
    wanted, records = set(item_ids), {}
    for batch in manifest["batches"]:
        if wanted.isdisjoint(batch["item_ids"]):
            continue
        with open(REPO_ROOT / batch["input_path"], encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    if record["item_id"] in wanted:
                        records[record["item_id"]] = record
    missing = wanted - set(records)
    if missing:
        sys.exit(f"Sampled items missing from the inputs: {sorted(missing)}")
    return records


def coded_items(path):
    """
    Return the item_ids already in a coder's file.

    Parameters
    ----------
    path : pathlib.Path
        The coder's JSONL file.

    Returns
    -------
    set of str
        Coded item_ids (empty if the file does not exist).
    """
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["item_id"] for line in f if line.strip()}


def save(path, record):
    """
    Append one coded item and force it to disk.

    Parameters
    ----------
    path : pathlib.Path
        The coder's JSONL file.
    record : dict
        The record to append.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def main():
    """
    Code the sampled items the coder has not yet coded.
    """
    args = parse_args()
    sample = json.loads(
        (SAMPLE_DIR / args.task / args.study / "sample.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (REPO_ROOT / sample["manifest_path"]).read_text(encoding="utf-8")
    )
    codebook_path = REPO_ROOT / manifest["codebook_path"]
    schema_path = REPO_ROOT / manifest["schema_path"]
    for key, path in [("codebook", codebook_path), ("schema", schema_path)]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[f"{key}_sha256"]:
            sys.exit(
                f"The {key} changed after the task inputs were written; ask the project lead."
            )
    schema = load_schema(schema_path)
    codebook = parse_codebook(codebook_path)
    records = load_inputs(manifest, sample["item_ids"])

    out_path = OUTPUT_DIR / args.task / args.study / f"{args.coder}.jsonl"
    if args.recode:
        if args.recode not in records:
            sys.exit(f"{args.recode} is not in the sample")
        todo = [args.recode]
    else:
        done = coded_items(out_path)
        todo = [i for i in sample["item_ids"] if i not in done]
    print(f"Codebook: {manifest['codebook_path']} (read it before your first session)")
    print(
        f"Saving to {os.path.relpath(out_path, REPO_ROOT)}; {len(todo)} items to code."
    )
    print('Commands: ":t" text again, ":h" field help, ":r" restart item, ":q" quit.')

    show = show_place if args.task == "places" else show_domain
    code = code_place if args.task == "places" else code_domain
    total = len(sample["item_ids"])
    try:
        for item_id in todo:
            record = records[item_id]
            position = sample["item_ids"].index(item_id) + 1
            prompter = Prompter(schema, codebook, lambda: show(record, position, total))
            while True:
                show(record, position, total)
                started = time.monotonic()
                try:
                    item = code(record, prompter, schema)
                except Restart:
                    print("\nRestarting this item.")
                    continue
                problems = [
                    format_problem(p)
                    for p in check_item(args.task, item, record, schema)
                ]
                if problems:
                    print("\nThe final check found:")
                    for line in problems:
                        print(f"  {line}")
                    choice = prompter.read(
                        "[r]edo the item or [s]ave anyway? ", None
                    ).lower()
                    if choice != "s":
                        continue
                save(
                    out_path,
                    {
                        "item_id": item_id,
                        "coder": args.coder,
                        "coded_at": datetime.now(timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        "seconds": round(time.monotonic() - started, 1),
                        "codebook_sha256": manifest["codebook_sha256"],
                        "check_problems": problems,
                        "item": item,
                    },
                )
                print(f"\nSaved {item_id}.")
                break
    except Quit, KeyboardInterrupt:
        print("\nStopped. Finished items are saved; run the same command to continue.")
        return
    print("\nAll sampled items are coded. Thank you!")


if __name__ == "__main__":
    main()
