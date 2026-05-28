"""
DB migrations. Files named `_NNN_description.py` are discovered and applied
in numerical order by the runner. Each migration is idempotent — running it
twice is safe.

Why Python files and not raw SQL: SQLite's ALTER TABLE can't conditionally
add a column, so each migration checks the current schema state first. That
logic is easier to express in Python.

The runner records applied migrations in `migration_history` so we don't
re-apply them; idempotency is a belt-and-braces guarantee on top of that.
"""
