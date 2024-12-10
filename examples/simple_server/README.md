# Writing a FastHTML Markdown Server

In this tutorial, we will write a simple markdown server using [`fasthtml`](https://github.com/AnswerDotAI/fasthtml).

The server will run from a directory and serve the filesystem hierarchy as well as any markdown files in the directory.

## What is FastHTML?

`fasthtml` is a brand new Python web framework based on HTMX that lets you write these fun little web apps in a single file. It's a lot like Flask, but with a focus on simplicity and speed. It's perfect for small projects, prototypes, and hackathons.

## Prerequisites

- Python 3.11 with `morphcloud` installed
- Docker

## Writing the app

```python
import os
from fasthtml.common import *

hdrs = (MarkdownJS(), HighlightJS(langs=['python', 'javascript', 'html', 'css']))

app = FastHTML(hdrs=hdrs)


current_dir = os.getcwd()

@app.route('/{path}')
def index(path: str):
    path = path or ""

    # check if path is a file
    if os.path.isfile(f"{current_dir}/{path}"):
        if path.endswith(".md"):
            with open(f"{current_dir}/{path}", "r") as f:
                return Div(f.read(), cls="marked")
        return f"Hello from file {current_dir}/{path}"

    return (
        Ul(
            *[
                Li(
                    A(
                        f"{file}",
                        href=f"{path}/{file}", text=file)
                )
                for file in os.listdir(f"{current_dir}/{path}")
                if file.endswith(".md") or os.path.isdir(f"{current_dir}/{path}/{file}") and not file.startswith(".") and not file.startswith("__")
            ]
        )
    )

serve(port=8000)
```

## Writing the Dockerfile

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN uv venv
RUN uv pip install python-fasthtml

COPY . .

ENTRYPOINT ["uv", "run", "app.py"]
```

## Deploying the app

```bash
docker build -t markdown-server .
morphcloud instance crun --image markdown-server --expose-port web:8000
```
