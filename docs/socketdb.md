## soketDB Database Documentation

```text
soketDB is a lightweight, JSON‑based embedded database with a PostgreSQL‑inspired SQL interface. It supports production‑grade encryption, automatic cloud synchronisation, and natural language queries. This document covers all features, including the new parameterised query style ($1, $2) that eliminates SQL injection and improves performance.
```

## Lynk integration with soketdb

```text
soketDB is a built-in Lynkio module.
```
---

## Table of Contents

1. Installation
2. Quick Start
3. Core Concepts
4. Creating Tables
5. Inserting Data
6. Querying Data (SELECT)
7. Updating Data
8. Deleting Data
9. Transactions
10. Environment Variables & Encryption
11. Cloud Sync & Backups
12. Natural Language Queries
13. Command‑Line Interface (CLI)
14. Distributed Queries (Lynk Integration)
15. Performance Tips
16. Error Handling
17. API Reference

---

## Installation

soketDB is Lynkio package:

```python
from lynkio import database, env
```

Optional dependencies for cloud providers:

```json
cloud_optional_dependecies={
        "huggingface": [
            "huggingface_hub~=0.16",
        ],
        "aws": [
            "boto3~=1.26",
        ],
        "gdrive": [
            "google-api-python-client~=2.70",
            "google-auth-oauthlib~=1.0",
            "google-auth-httplib2~=0.1",
        ],
        "dropbox": [
            "dropbox~=11.36",
        ],
        "encryption": [
            "cryptography~=39.0",
        ],
        "full": [
            "huggingface_hub~=0.16",
            "boto3~=1.26",
            "google-api-python-client~=2.70",
            "google-auth-oauthlib~=1.0",
            "google-auth-httplib2~=0.1",
            "dropbox~=11.36",
            "cryptography~=39.0",
        ]
        
```
```bash
pip install lynkio[gdrive] == 1.1.6
```

---

## Quick Start

```python
from lynkio import database

# Create or connect to a project
db = database("my_app")

# Create a table (only if it doesn't exist)
db.execute("CREATE TABLE IF NOT EXISTS users (id, name, age, city)")

# Insert a row with parameters
db.execute(
    "INSERT INTO users (id, name, age, city) VALUES ($1, $2, $3, $4)",
    (1, "Alice", 30, "New York")
)

# Query with a parameterised WHERE clause
result = db.execute(
    "SELECT name, age FROM users WHERE age > $1 AND city = $2",
    (25, "New York")
)
print(result)  # [{'name': 'Alice', 'age': 30}]

# Automatic cloud sync (if configured) keeps your data in sync across instances.
```

---

## Core Concepts
```text
· Database: Each project is a folder under ./soketDB/<project_name> containing one JSON file per table.
· Tables: Schema‑less, but you can enforce columns via metadata. Tables are stored as arrays of JSON objects.
· SQL‑like syntax: Supported commands: CREATE TABLE, INSERT, SELECT, UPDATE, DELETE, ALTER TABLE, DROP TABLE.
· Parameterised Queries: Always use $1, $2, … placeholders and pass values as a tuple to execute(). This prevents injection and allows query caching.
· Transactions: Use the transaction() context manager for atomic multi‑table writes.
· Encryption: Production mode encrypts all data on disk using Fernet (symmetric encryption). The encryption key is displayed once and must be saved securely.
· Cloud Sync: Automatically synchronises tables with a primary cloud provider (HuggingFace, Google Drive, AWS S3, Dropbox). A background thread pulls changes every 60 seconds.
```

---

## Creating Tables

```python
# Simple table creation
db.execute("CREATE TABLE users (id, name, age, city)")

# Create only if not exists (safe to run multiple times)
db.execute("CREATE TABLE IF NOT EXISTS orders (order_id, user_id, total)")
```

Columns are defined by name only; data types are not enforced, but you can add your own validation.

---

## Inserting Data

Single Row

```python
db.execute(
    "INSERT INTO users (id, name, age, city) VALUES ($1, $2, $3, $4)",
    (1, "Alice", 30, "New York")
)
```

## Multiple Rows

Placeholders are consumed sequentially. Each group of placeholders represents one row.

```python
users = [
    (2, "Bob", 25, "London"),
    (3, "Charlie", 35, "Paris"),
    (4, "Diana", 28, "Tokyo")
]
# Flatten the list of tuples into a single tuple
params = tuple(item for row in users for item in row)

query = """
    INSERT INTO users (id, name, age, city)
    VALUES ($1, $2, $3, $4), ($5, $6, $7, $8), ($9, $10, $11, $12)
"""
db.execute(query, params)
```

## Duplicate Prevention

soketDB automatically skips full‑row duplicates (identical values in all columns). Duplicates are reported but not inserted.

```python
# This row already exists → skipped
db.execute(
    "INSERT INTO users (id, name, age, city) VALUES ($1, $2, $3, $4)",
    (1, "Alice", 30, "New York")
)
# Output: "✅ 0 row(s) inserted ... ⚠️ Skipped 1 duplicate(s)."
```

---

## Querying Data (SELECT)

Basic SELECT

```python
# All columns
rows = db.execute("SELECT * FROM users")
```

Parameterised WHERE

Use $n placeholders in the WHERE clause. Only AND combinations are supported (simple parser).

```python
rows = db.execute(
    "SELECT name, age FROM users WHERE age > $1 AND city = $2",
    (25, "New York")
)
```

`Operators: =, >, <.`
Values are compared as strings or numbers depending on context.

ORDER BY

```python
rows = db.execute("SELECT * FROM users ORDER BY age")
```

Multiple columns: ORDER BY age, name.

GROUP BY (simplified)

Group by first column, with a count aggregation:

```python
rows = db.execute("SELECT city, COUNT(*) FROM users GROUP BY city")
```

LIMIT

```python
rows = db.execute("SELECT * FROM users LIMIT 5")
```

JOIN (simple INNER JOIN)

```python
rows = db.execute("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
```

The join is performed in‑memory; for large datasets consider denormalising.

---

## Updating Data

```python
db.execute(
    "UPDATE users SET age = $1, city = $2 WHERE name = $3",
    (31, "Berlin", "Alice")
)
```

The SET and WHERE clauses can contain multiple placeholders.
Only one condition in WHERE is supported (with a single placeholder).

---

## Deleting Data

```python
# Delete specific user
db.execute("DELETE FROM users WHERE name = $1", ("Charlie",))

# Delete all rows (no WHERE)
db.execute("DELETE FROM users")
```

---

## Transactions

Use the transaction() context manager to group multiple writes atomically. All changes are committed only if no exception occurs.

```python
with db.transaction():
    db.execute("INSERT INTO users ...", (5, "Eve", 22, "Rome"))
    db.execute("UPDATE users SET age = age + 1 WHERE city = $1", ("Rome",))
    # If any step fails, all writes are discarded.
```

---

## Environment Variables & Encryption

Environment Manager

The env() helper manages environment variables, optionally storing encrypted values.

```python
from lynkio import env

myenv = env(".env")            # load from .env file
api_key = myenv.get("API_KEY")
myenv.set("DB_PASSWORD", "secret", encrypt=True)   # encrypted storage
```

Production Mode (Encryption)

When production=True is passed to database(), all data is encrypted on disk using Fernet. The encryption key is shown only once – save it securely!

```python
# First run (generates key)
db = database("my_project", production=True)

# Subsequent runs: provide the key from environment
key = myenv.get("encrypted_key")
db = database("my_project", production=True, encryption_key=key)
```

Migrating an Existing Database to Production

Use the helper migrate_to_production():

```python
from lynkio import migrate_to_production
migrate_to_production("my_project")
```

This encrypts all existing tables and stores the key in .env.

---

## Cloud Sync & Backups

Configuration

Create a database_config.json file or pass a dict to database().

```json
{
    "primary_storage": "huggingface",
    "auto_sync": true,
    "huggingface_enabled": true,
    "huggingface_token": "hf_xxxx",
    "huggingface_repo_id": "username/repo",
    "backup_enabled": true
}
```

## Automatic Synchronisation

· Push: After every write (throttled to at most once per 2 seconds per table), the table is uploaded to the cloud provider.
· Pull: When the database is initialised, it downloads all tables from the cloud. A background thread pulls changes every 60 seconds, keeping local data eventually consistent.

You never need to call restore() manually; queries always read from the local cache, which is periodically refreshed.

## Manual Backup and Restore

```python
results = db.backup()               # returns dict {provider: status}
print(results)

db.restore(provider="huggingface")  # restore from a specific provider
```

---

## Natural Language Queries

The query() method translates English prompts into SQL using a rule‑based engine (no LLM required).

```python
result = db.query("Show all users older than 25 from London")
print(result)   # executes: SELECT * FROM users WHERE age > 25 AND city = 'London'
```

Supported intents: SELECT, COUNT, SUM, AVG, GROUP BY, JOIN, INSERT, UPDATE, DELETE, ALTER.

---

## Distributed Queries (Lynkio Integration)

If you use Lynkio (the companion real‑time engine), you can run queries on any registered soketDB instance across the network.

```python
# In a Lynk handler
result = await app.query_database("my_project", "SELECT * FROM users WHERE age > $1", (30,))
```

The query runs in a thread executor and returns the result asynchronously.

---

## Performance Tips

· Use parameterised queries – they are cached by the QueryOptimizer for 5 minutes.
· Batch inserts – use multiple VALUES groups instead of many single‑row inserts.
· Indexing – not built‑in; keep tables small or use in‑memory joins wisely.
· Cloud sync – the background thread may add a small delay; tune the sync interval if needed.
· Encryption – adds overhead; use only for sensitive data.

---

## Error Handling

soketdb exceptions are not specialised; most errors return a descriptive string. Check the return value of execute(): if it starts with "❌", an error occurred.

```python
result = db.execute("INVALID SQL")
if isinstance(result, str) and result.startswith("❌"):
    print("Query failed:", result)
else:
    # success
    print(result)
```

For programmatic error handling, you can catch exceptions from underlying operations (file I/O, decryption, etc.).

---

## API Reference

database(project_name, config=None, production=False, encryption_key=None, env_file=".env")

Create or connect to a database project.

· project_name: name of the project (folder under ./soketDB/)
· config: dict with cloud/backup settings (optional)
· production: enable encryption
· encryption_key: key for decryption (required if production=True and not first run)
· env_file: path to .env file

execute(query, params=None)

Execute a SQL query with optional parameters ($1, $2, …). Returns result (list of dicts for SELECT, status string otherwise).

query(natural_language)

Convert natural language to SQL and execute it.

transaction()

Context manager for atomic commits.

backup() and restore(provider=None)

Manual backup/restore.

list_tables() and table_info(table)

Introspection methods.

query_history(limit=10) and performance_stats()

Get execution logs and statistics.

get_environment()

Return the EnvironmentManager instance.

env(env_file=".env", production=False)

Helper to create an EnvironmentManager.

migrate_to_production(project_name, env_file=".env")

Encrypt an existing non‑production database.

---

## Conclusion

soketDB offers a simple yet powerful embedded database with modern features: parameterised queries, encryption, cloud sync, and natural language support. Its PostgreSQL‑style syntax makes it familiar to developers, while the automatic sync keeps multiple instances consistent without complex replication logic.

For questions or contributions, visit GitHub repository.