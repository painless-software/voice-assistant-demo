# Agent Instructions

- For Python development assume `uv` to be installed. Assume Python versions to be installed and maintained via `uv python install`.
- Prefer `uv add` to install depedenciens and `uv run` to run the code with all dependencies over maintaining a `.venv` folder and installing dependencies with `uv pip` (and `requirements.txt`).
- Write unit tests in Pytest. Prefer pytest-style function-based tests with plain assert (over test classes). Favor Pytest's parametrize to cover different test values (over similar duplicate tests).
- Write BDD tests with Behave for functional and integration tests.
- Assume `just` to be installed (via `uv tool install rust-just`) for running linting and tests.
