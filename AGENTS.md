# Agent Instructions

- The `pytest` configuration is read from `pyproject.toml`.
- Call pytest without -q
- When running project scripts directly, set `PYTHONPATH=src` so imports work correctly.
- Do not change lists written on a single line into multiple lines with one element each.
- The `copenhagen` directory is a clone of the "Copenhagen" book about authentication.
- Don't do any syntactical change on code that wasn't changed semantically.
- Always try to add unit tests for any code change.
