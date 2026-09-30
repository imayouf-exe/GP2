## Alembic Migrations

Use Alembic to evolve DB schema instead of adding ad-hoc `CREATE TABLE` logic in route startup.

### Setup

```bash
pip install -r requirements.txt
```

### Run migrations

```bash
alembic upgrade head
```

### Create a new migration

```bash
alembic revision -m "describe change"
```

Then edit the generated file under `migrations/versions/` with `op.execute(...)` or `op.create_table(...)`.
