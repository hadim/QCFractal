"""task_queue base_result not null and check lowercase

Revision ID: 88182596f844
Revises: 79604526d271
Create Date: 2021-05-05 09:30:04.702155

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func, column


# revision identifiers, used by Alembic.
revision = "88182596f844"
down_revision = "79604526d271"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("task_queue", "base_result_id", existing_type=sa.INTEGER(), nullable=False)
    op.create_check_constraint("ck_result_program_lower", "result", column("program") == func.lower(column("program")))
    op.create_check_constraint("ck_result_driver_lower", "result", column("driver") == func.lower(column("driver")))
    op.create_check_constraint("ck_result_method_lower", "result", column("method") == func.lower(column("method")))
    op.create_check_constraint("ck_result_basis_lower", "result", column("basis") == func.lower(column("basis")))
    op.create_check_constraint(
        "ck_optimization_procedure_program_lower",
        "optimization_procedure",
        column("program") == func.lower(column("program")),
    )
    op.create_check_constraint(
        "ck_grid_optimization_procedure_program_lower",
        "grid_optimization_procedure",
        column("program") == func.lower(column("program")),
    )
    op.create_check_constraint(
        "ck_torsiondrive_procedure_program_lower",
        "torsiondrive_procedure",
        column("program") == func.lower(column("program")),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("task_queue", "base_result_id", existing_type=sa.INTEGER(), nullable=True)
    op.drop_constraint("ck_result_program_lower", "result")
    op.drop_constraint("ck_result_driver_lower", "result")
    op.drop_constraint("ck_result_method_lower", "result")
    op.drop_constraint("ck_result_basis_lower", "result")
    op.drop_constraint("ck_optimization_procedure_program_lower", "optimization_procedure")
    op.drop_constraint("ck_grid_optimization_procedure_program_lower", "grid_optimization_procedure")
    op.drop_constraint("ck_torsiondrive_procedure_program_lower", "torsiondrive_procedure")
    # ### end Alembic commands ###
