"""Entry-point: python -m voice_assistant"""

import logging

import uvicorn

from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main() -> None:
    uvicorn.run(
        "voice_assistant.app:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
