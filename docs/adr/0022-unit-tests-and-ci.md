# ADR 0022: Fast unit tests that run on every push, and one project file

**Status:** Accepted · **Date:** 2026-11-03 · Builds on [0016](0016-modular-layout-one-tool-per-file.md) and
[0017](0017-how-we-evaluate.md)

## Context

The evaluation in ADR 0017 calls the real models, so it costs money, takes many minutes and needs AWS and Neo4j
access. That's right for grading Navi's answers, but too slow and too expensive to run after every code change. A
change could break a safety rule, such as the query guard or the sign-in check, and nobody would know until the next
full evaluation.

The project's set-up was also scattered: Python packages in `requirements.txt`, the API at the top of the project,
and no standard place for tests.

## Decision

I added **55 unit tests** in `tests/`, run with `pytest`. They check the code's own rules and never call a model:

| File | What it checks |
|---|---|
| `test_cypher_guard.py` | Unsafe database queries are rejected |
| `test_input_guard.py` | Pidgin detection and masking of ID and card numbers |
| `test_output_filter.py` | Internal codes are removed from replies |
| `test_memory.py` | One business per fact, no silent overwrites, no mixing between users |
| `test_auth.py` | The sign-in check |
| `test_api.py` | The API's access rules |
| `test_canonical_names.py` | The knowledge graph's standard names |

A **GitHub workflow** (`.github/workflows/tests.yml`) runs them on every push to `main` and on every pull request.
It also type-checks and builds the website.

I also moved the server into an `api/` folder and replaced `requirements.txt` with one **`pyproject.toml`**, which
holds the packages and the test settings. `pip install -e ".[dev]"` installs everything.

## Why I chose this

The unit tests take seconds and cost nothing, so they can run all the time. They need no passwords, which means GitHub
can run them without being given any secrets.

The two kinds of test do different jobs. Unit tests prove the code's rules still work. The evaluation measures how
well Navi answers. Neither can replace the other: a change to the prompt can't be checked by a unit test, because
the tests never call a model.

`pyproject.toml` is the standard Python project file, so anyone who knows Python knows where to look.

## What I considered instead

**Relying on the evaluation alone** would be too slow and costly to run on every change, and it would need AWS keys
stored on GitHub.

**Running the full evaluation on GitHub** has the same problems, and its scores vary between runs, so it would fail
for reasons that have nothing to do with the change.

**Keeping `requirements.txt`** would have worked, but the test tools and settings would have needed separate files.

## Consequences

A change that breaks a code rule is caught within minutes, for free. The limit is that passing unit tests says
nothing about how good Navi's replies are, so the evaluation still has to be run after any prompt or model change.
The commands also changed: the server now starts with `uvicorn api.server:app`.

## Where to find it

The tests are in `tests/`, with shared set-up in `tests/conftest.py`. The workflow is
`.github/workflows/tests.yml`, and the project file is `pyproject.toml`.
