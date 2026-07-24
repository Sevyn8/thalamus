"""slice3_documents_verification

Revision ID: b755e9d4081c
Revises: e5a2c8b13d40
Create Date: 2026-07-24

Client onboarding module, Slice 3 (documents): extend ``tenant_documents``
with verification state and upload metadata.

Adds six columns to the existing ``tenant_documents`` table (created at
``e5a2c8b13d40``):

  * ``verification_status`` TEXT NOT NULL DEFAULT 'PENDING_REVIEW'
        Validated app-side against the new ``document_verification_status``
        ``lookups`` list (PENDING_REVIEW / VERIFIED / REJECTED). No new PG
        enum, mirroring the Slice-1/2 coded-column convention (flag 4b).
  * ``verified_by_user_id`` UUID NULL   -> FK platform_users (Pattern (a))
  * ``verified_at``         TIMESTAMPTZ NULL
  * ``rejection_reason``    TEXT NULL
  * ``file_size_bytes``     BIGINT NULL
  * ``uploaded_by_user_id`` UUID NULL   -> FK platform_users (Pattern (a))

One CHECK enforces the verification state machine:
  * VERIFIED or REJECTED require verified_by_user_id AND verified_at NOT NULL.
  * REJECTED additionally requires rejection_reason NOT NULL.
Pre-existing rows (all PENDING_REVIEW via the DEFAULT) satisfy it.

Seeds the ``document_verification_status`` lookups vocabulary.

Unqualified identifiers throughout, per the migration convention
(``env.py`` sets ``search_path`` inside the alembic transaction).

Downgrade removes the seed rows, drops the CHECK, and drops the six
columns (reverse order). No CASCADE.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b755e9d4081c"
down_revision: Union[str, Sequence[str], None] = "e5a2c8b13d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the six columns. verification_status is NOT NULL with a
    #    server default so pre-existing rows land in PENDING_REVIEW.
    op.execute(
        """
        ALTER TABLE tenant_documents
            ADD COLUMN verification_status TEXT NOT NULL
                DEFAULT 'PENDING_REVIEW',
            ADD COLUMN verified_by_user_id UUID NULL,
            ADD COLUMN verified_at         TIMESTAMPTZ NULL,
            ADD COLUMN rejection_reason    TEXT NULL,
            ADD COLUMN file_size_bytes     BIGINT NULL,
            ADD COLUMN uploaded_by_user_id UUID NULL
        """
    )

    # 2. Pattern (a) audit-actor FKs to platform_users (mirrors the
    #    existing created_by / updated_by FKs on this table).
    op.execute(
        """
        ALTER TABLE tenant_documents
            ADD CONSTRAINT fk_tenant_documents_verified_by
                FOREIGN KEY (verified_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            ADD CONSTRAINT fk_tenant_documents_uploaded_by
                FOREIGN KEY (uploaded_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT
        """
    )

    # 3. Verification state-machine CHECK.
    op.execute(
        """
        ALTER TABLE tenant_documents
            ADD CONSTRAINT ck_tenant_documents_verification_consistency
                CHECK (
                    (
                        verification_status NOT IN ('VERIFIED', 'REJECTED')
                        OR (verified_by_user_id IS NOT NULL
                            AND verified_at IS NOT NULL)
                    )
                    AND (
                        verification_status <> 'REJECTED'
                        OR rejection_reason IS NOT NULL
                    )
                )
        """
    )

    # 4. Seed the document_verification_status lookups vocabulary.
    op.execute(
        """
        INSERT INTO lookups (list_name, code, display_name, display_order, is_active)
        VALUES
            ('document_verification_status', 'PENDING_REVIEW', 'Pending review', 1, TRUE),
            ('document_verification_status', 'VERIFIED',       'Verified',       2, TRUE),
            ('document_verification_status', 'REJECTED',       'Rejected',       3, TRUE)
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM lookups "
        "WHERE list_name = 'document_verification_status'"
    )
    op.execute(
        "ALTER TABLE tenant_documents "
        "DROP CONSTRAINT ck_tenant_documents_verification_consistency"
    )
    op.execute(
        """
        ALTER TABLE tenant_documents
            DROP CONSTRAINT fk_tenant_documents_uploaded_by,
            DROP CONSTRAINT fk_tenant_documents_verified_by
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_documents
            DROP COLUMN uploaded_by_user_id,
            DROP COLUMN file_size_bytes,
            DROP COLUMN rejection_reason,
            DROP COLUMN verified_at,
            DROP COLUMN verified_by_user_id,
            DROP COLUMN verification_status
        """
    )
