"""Use double precision for epoch lease deadlines on MySQL.

MySQL FLOAT defaults to 32-bit precision and rounds epoch seconds by minutes.
SQLite already uses 64-bit floats; PostgreSQL Float defaults to double precision.
"""

from alembic import op
from sqlalchemy import Float

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "sqlite":
        for table in ("conversations", "discovery_locks"):
            op.alter_column(
                table,
                "lease_until",
                type_=Float(53),
                existing_type=Float(),
                existing_nullable=False,
            )


def downgrade():
    raise RuntimeError("Lease precision must not be downgraded")
