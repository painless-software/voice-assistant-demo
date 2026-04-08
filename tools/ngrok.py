# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "python-dotenv>=1.2.2",
# ]
# ///
"""Start an ngrok tunnel, persist the public URL in .env, then run the server."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

from dotenv import set_key


NGROK_LOG = "/tmp/ngrok.log"
ENV_PATH = ".env"


def _wait_for_url(timeout: int = 20) -> str:
    for _ in range(timeout):
        try:
            data = json.loads(urlopen("http://localhost:4040/api/tunnels").read())
            url = data["tunnels"][0]["public_url"]
            if url.startswith("https://"):
                return url
        except Exception:
            pass
        time.sleep(1)
    return ""


def main() -> None:
    port = os.environ.get("PORT", "8080")

    if not shutil.which("ngrok"):
        sys.exit("ERROR: ngrok not found. Install it from https://ngrok.com/download")

    # Kill any previous ngrok on this port
    subprocess.run(["pkill", "-f", f"ngrok http {port}"], capture_output=True)
    time.sleep(1)

    print(f"Starting ngrok on port {port}...")
    log = open(NGROK_LOG, "w")
    ngrok = subprocess.Popen(
        ["ngrok", "http", port, "--log=stdout"],
        stdout=log,
        stderr=log,
    )

    public_url = _wait_for_url()
    if not public_url:
        ngrok.kill()
        sys.exit(f"ERROR: Could not determine ngrok public URL. Check {NGROK_LOG}")

    print(f"ngrok public URL: {public_url}")
    set_key(ENV_PATH, "PUBLIC_URL", public_url)

    host = public_url.removeprefix("https://")
    print(f"\n  Webhook URL:    {public_url}/voice")
    print(f"  WebSocket URL:  wss://{host}/ws/media-stream\n")

    # Forward termination signals to ngrok, then exit cleanly
    def _cleanup(*_: object) -> None:
        ngrok.kill()
        log.close()
        print("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        env = {**os.environ, "PUBLIC_URL": public_url}
        subprocess.run(
            ["uv", "run", "python", "-m", "voice_assistant"],
            env=env,
            check=True,
        )
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
