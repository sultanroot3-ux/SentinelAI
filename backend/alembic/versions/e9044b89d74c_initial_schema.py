"""initial schema

Revision ID: e9044b89d74c
Revises: 
Create Date: 2026-07-22 23:45:12.601660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9044b89d74c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Tables are created in dependency order. unknown_faces <-> cases reference
    each other, so unknown_faces is created WITHOUT its case_id FK, and the
    constraint is added with ALTER TABLE at the end (matches use_alter=True
    on the model).
    """
    op.create_table('departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_departments_id'), 'departments', ['id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)
    op.create_index(op.f('ix_notifications_id'), 'notifications', ['id'], unique=False)
    op.create_table('settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('unknown_faces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_url', sa.String(length=255), nullable=True),
    sa.Column('camera', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_unknown_faces_id'), 'unknown_faces', ['id'], unique=False)
    op.create_index(op.f('ix_unknown_faces_timestamp'), 'unknown_faces', ['timestamp'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('employee_id', sa.String(length=50), nullable=True),
    sa.Column('access_level', sa.String(length=30), nullable=True),
    sa.Column('photo_url', sa.String(length=255), nullable=True),
    sa.Column('face_registered', sa.Boolean(), nullable=False),
    sa.Column('face_embedding', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('username', sa.String(length=80), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)
    op.create_index(op.f('ix_audit_logs_timestamp'), 'audit_logs', ['timestamp'], unique=False)
    op.create_table('recognition_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('camera', sa.String(length=80), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('snapshot_url', sa.String(length=255), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recognition_logs_id'), 'recognition_logs', ['id'], unique=False)
    op.create_index(op.f('ix_recognition_logs_timestamp'), 'recognition_logs', ['timestamp'], unique=False)
    op.create_table('cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_number', sa.String(length=30), nullable=False),
    sa.Column('unknown_face_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('assigned_to', sa.Integer(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['unknown_face_id'], ['unknown_faces.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_number')
    )
    op.create_index(op.f('ix_cases_id'), 'cases', ['id'], unique=False)
    # Deferred half of the unknown_faces <-> cases circular reference
    op.create_foreign_key(
        'fk_unknown_faces_case_id', 'unknown_faces', 'cases',
        ['case_id'], ['id'], ondelete='SET NULL',
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the deferred circular FK before its tables
    op.drop_constraint('fk_unknown_faces_case_id', 'unknown_faces', type_='foreignkey')
    op.drop_index(op.f('ix_cases_id'), table_name='cases')
    op.drop_table('cases')
    op.drop_index(op.f('ix_recognition_logs_timestamp'), table_name='recognition_logs')
    op.drop_index(op.f('ix_recognition_logs_id'), table_name='recognition_logs')
    op.drop_table('recognition_logs')
    op.drop_index(op.f('ix_audit_logs_timestamp'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_unknown_faces_timestamp'), table_name='unknown_faces')
    op.drop_index(op.f('ix_unknown_faces_id'), table_name='unknown_faces')
    op.drop_table('unknown_faces')
    op.drop_table('settings')
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_departments_id'), table_name='departments')
    op.drop_table('departments')
    # ### end Alembic commands ###
