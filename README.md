# cc-research-project-template

A research project repository template, built for Claude Code.
Custom Claude code functions are included with reference files to streamline research workflows.

See the [docs/cc-docs/getting-started.md](docs/cc-docs/getting-started.md) file for an overview of the approach to how Claude Code is leveraged.

## Contents

- `.claude/`: Files related to Claude code are saved here
- `code/`: All source code including analysis scripts, data collection, cleaning, and utilities
- `data/`: Data files organized by processing stage (raw, interim, processed, external)
- `results/`: Output files generated from analysis (tables and figures)
- `lit_review/`: PDF papers and AI-generated summaries for the literature review phase
- `paper/`: LaTeX manuscript files (outline, bibliography, and main document)
- [`CLAUDE.md`](CLAUDE.md): Claude Code-specific instructions and context
- [`pyproject.toml`](pyproject.toml): Project metadata and Python dependencies (managed with [uv](https://docs.astral.sh/uv/))
- [`uv.lock`](uv.lock): Pinned versions of every dependency, for reproducing the environment
- [`.python-version`](.python-version): The Python version uv uses for this project

## Environment setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/).
Run `uv sync` to create `.venv/` and install the pinned dependencies, then run scripts with `uv run python <script.py>`.
