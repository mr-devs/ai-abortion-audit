# Toolkit

This directory contains the local project module with shared utility functions and project-specific code used across multiple scripts.
This promotes code reuse and maintains consistency across the project.

## Contents

- `pyproject.toml`: Modern Python packaging configuration (PEP 517/518 compliant)
- `setup.py`: Legacy setup script (retained for backwards compatibility)
- `toolkit/`: Package directory containing reusable modules for the project

## Installation

The package is an editable dependency of the project (a uv workspace member, declared in the root [`pyproject.toml`](../../pyproject.toml)), so `uv sync` from the project root installs it.
Edits to the package take effect without reinstalling.
