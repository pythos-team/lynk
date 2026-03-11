```markdown
# Templates

Lynkio provides a minimal, built‑in template renderer for simple HTML pages. It supports variable substitution using `{{ variable }}` syntax.

## Basic Usage

Place your templates in a directory (default is `./templates`). Example template `templates/hello.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
</head>
<body>
    <h1>Hello, {{ name }}!</h1>
</body>
</html>
```

Render it in a handler:

```python
from lynkio import render_template

@app.get("/hello/<name>")
async def hello(req, name):
    html = render_template("hello.html", context={
        "title": "Greetings",
        "name": name
    })
    return html
```

## Context Variables

The context dictionary can contain nested dictionaries. Use dot notation to access nested values:

## Template:

```html
<p>User: {{ user.name }} ({{ user.email }})</p>
```

## Handler:

```python
render_template("profile.html", context={
    "user": {"name": "Alice", "email": "alice@example.com"}
})
```

Custom Template Directory

Specify a different template directory:

```python
html = render_template("index.html", context={}, template_dir="/var/www/templates")
```

## Limitations

· No loops, conditionals, or filters – it's pure variable substitution.

· Intended for simple pages; for complex needs, consider integrating a full template engine like Jinja2 or wait for lataest lynkio update.
