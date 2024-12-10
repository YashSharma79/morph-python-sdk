FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN uv venv
RUN uv pip install python-fasthtml

COPY . .

ENTRYPOINT ["uv", "run", "app.py"]
