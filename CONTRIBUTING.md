# Contributing to ASTK Studio

Thank you for helping improve ASTK Studio. Bug reports, documentation fixes,
reproducible test cases, and focused pull requests are welcome.

## Before opening an issue

- Check whether the problem belongs to ASTK Studio or the ASTK command-line tool.
- Remove private, controlled-access, or personally identifiable data.
- Include the operating system, deployment method, browser, and relevant logs.
- For analysis failures, include a minimal `samples.csv` and the generated
  `plan.json` when they can be shared safely.

Security issues should be reported using the process in `SECURITY.md`, not in a
public issue.

## Development setup

ASTK Studio's web server uses the Python standard library:

```bash
python3 backend/server.py
```

Run the automated checks before submitting a pull request:

```bash
python3 -m unittest discover -s tests -v
node --check app.js
python3 scripts/build_pages.py
```

Real ASTK execution requires Linux and the ASTK runtime. Frontend and API changes
can be tested in demo mode without ASTK installed.

## Pull requests

- Keep changes focused and document user-visible behavior.
- Add or update tests for parsing, validation, job lifecycle, and security logic.
- Do not commit uploaded datasets, generated job directories, references, or
  secrets.
- Preserve the distinction between the static GitHub Pages demo and the
  self-hosted analysis service.

By contributing, you agree that your contribution is licensed under the
BSD-3-Clause license used by this project.
