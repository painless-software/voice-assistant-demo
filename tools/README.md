# Tools

Standalone CLI helpers for local development and account management.
These scripts are **not** part of the `voice_assistant` package and are
excluded from the Docker production image.

## Scripts

| Script | Purpose | Invocation |
|--------|---------|------------|
| `twilio_helper.py` | Provision and manage Twilio phone numbers, check account balance | `just twilio-list`, `just twilio-buy`, `just balance` |
| `ngrok.py` | Start an ngrok tunnel, persist the public URL in `.env`, then run the server | `just dev` |

## Dependencies

- **twilio_helper.py** requires `twilio` and `python-dotenv` (provided
  automatically by `uvx --with` in the justfile recipes).
- **ngrok.py** requires the [ngrok](https://ngrok.com/download) binary on
  your `PATH` and the project's own dependencies (run via `uv run`).
