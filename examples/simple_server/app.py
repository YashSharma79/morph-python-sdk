import os
from fasthtml.common import *

hdrs = (
    MarkdownJS(),
    HighlightJS(langs=['python', 'javascript', 'html', 'css', 'dockerfile']),
    Style('body {font-family: Arial, sans-serif;}'),
)

app = FastHTML(hdrs=hdrs)


current_dir = os.getcwd()

@app.route('/{path}')
def index(path: str):
    path = path or ""

    if path == "favicon.ico":
        # create a dynamic favicon
        return Img(src="https://cloud.morph.so/static/logo.png")

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
