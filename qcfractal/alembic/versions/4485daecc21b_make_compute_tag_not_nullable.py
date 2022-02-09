"""make compute tag not nullable

Revision ID: 4485daecc21b
Revises: 435c1f35227d
Create Date: 2022-02-09 13:19:12.191737

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4485daecc21b"
down_revision = "435c1f35227d"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    op.execute(sa.text("UPDATE service_queue SET tag = '*' WHERE tag IS NULL"))
    op.execute(sa.text("UPDATE task_queue SET tag = '*' WHERE tag IS NULL"))

    op.alter_column("service_queue", "tag", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column("task_queue", "tag", existing_type=sa.VARCHAR(), nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("task_queue", "tag", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("service_queue", "tag", existing_type=sa.VARCHAR(), nullable=True)
    # ### end Alembic commands ###
