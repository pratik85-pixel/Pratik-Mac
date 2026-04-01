"""merge heads after yesterday summary

Revision ID: 38b1eccbdf47
Revises: 9c1f7f3a2d1b, b647821611c4
Create Date: 2026-04-01 12:59:59.055748+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38b1eccbdf47'
down_revision: Union[str, None] = ('9c1f7f3a2d1b', 'b647821611c4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
