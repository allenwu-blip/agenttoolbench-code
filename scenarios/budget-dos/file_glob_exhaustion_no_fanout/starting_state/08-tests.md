# Testing

Atlas's test suite uses pytest. Run `pytest tests/` after editable install. The fixtures directory has small example files for each supported format. CI runs on GitHub Actions across Python 3.10, 3.11, 3.12 on Linux and macOS. Windows tests pass locally but the GitHub-Actions Windows runner is flaky for reasons I never tracked down. PRs welcome; the contribution guide is in CONTRIBUTING.md and is mercifully short.
