# Toolkit Package

Core package modules containing reusable utility functions, data models, and metrics for the project.

## Contents

- [`__init__.py`](__init__.py): Package initialization file that imports all submodules
- [`loading.py`](loading.py): Finds complete taxman runs through their `manifest.json` files, loads their responses as response models (one per message and repeat, keeping the final row when a later collect re-sent a failure), parses study/location from audit names, and reads Gemini's `resolved_urls.jsonl` files
- [`response_models/`](response_models/): Per-provider data models (Anthropic, OpenAI, Gemini) that extract text, citations, tool calls, token usage, and stop info from taxman response records
- [`resources.py`](resources.py): Keyword lexicon of abortion-access resources (AbortionFinder, NAF hotline, Plan C, crisis pregnancy centers, and others) and a function that finds which ones a response names; patterns are JavaScript-compatible so the explorer highlights the same matches
- [`utils.py`](utils.py): Utility functions including logging setup, domain extraction, parsing the city a pilot-4cities message names, JSONL file loading, and the timestamped filenames that download scripts use to save files and find earlier downloads
- [`metrics.py`](metrics.py): Convenience metric functions for data analysis
- [`data_models.py`](data_models.py): Data models for API response processing
