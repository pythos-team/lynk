## Installation
```markdown

Lynkio is available on PyPI and can be installed with `pip`. Because it has no external dependencies (except for optional database logging), installation is straightforward.

## Install from PyPI

```bash
pip install lynkio == 1.1.3
```

## Verify Installation

Run a quick test to make sure everything works:

```python
from lynkio import Lynk
print(Lynk.__doc__)
```

You should see the module docstring.

## Optional Dependencies

```markdown
. cloud backups - (huggingface, dropbox, aws, google_drive) all this are buitin lynkio database backups they are all Optional to use with a specific backup you run pip install lynkio[cloud]==1.1.3

· cryptography – If you use lynkio database in production mode with encryption, you'll need to pip install cryptography manually or It will be installed automatically with lynkio if you choose production features ie (pip install lynkio[huggingface]==1.1.3).

Now that Lynk is installed, head over to the Quickstart to build your first application.

```