FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY voice_assistant/ voice_assistant/

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["python", "-m", "voice_assistant"]
