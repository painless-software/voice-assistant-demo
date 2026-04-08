# Tools

Standalone CLI helpers for local development and account management.
These scripts are **not** part of the `voice_assistant` package and are
excluded from the Docker production image.

## Scripts

| Script | Purpose | Invocation |
|--------|---------|------------|
| `twilio_ops.py` | Provision and manage Twilio phone numbers, check account balance | `just twilio-list`, `just twilio-buy`, `just balance` |
| `ngrok.py` | Start an ngrok tunnel, persist the public URL in `.env`, then run the server | `just dev` |

## Dependencies

Each script declares its own dependencies via [inline script metadata],
so `uv run tools/<script>.py` installs them automatically.

**ngrok.py** additionally requires the [ngrok](https://ngrok.com/download)
binary on your `PATH`. NixOS users can run `nix develop` to get it installed.

[inline script metadata]: https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies
