"""slice1_onboarding_tables_and_lookups

Revision ID: e5a2c8b13d40
Revises: d3f7a1c92b64
Create Date: 2026-07-23

Client onboarding module, Slice 1 (migration 2 of 2).

Creates the six onboarding tables and seeds the lookup vocabularies.

Tables (all tenant-scoped, mirroring the ``tenants`` conventions and
the ``tenant_module_access`` precedent at ``cd2a02e452ae``):
  * ``tenant_legal_profile``      (1:1)
  * ``tenant_tax_registrations``  (1:N; multi-state GSTIN supported)
  * ``tenant_billing_profile``    (1:1)
  * ``tenant_contacts``           (1:N)
  * ``tenant_documents``          (1:N; GCS object refs only, no upload)
  * ``tenant_onboarding``         (1:1; wizard state)

Each table: ``uuidv7()`` PK, Pattern (a) nullable audit-actor FKs to
``platform_users`` (mirrors ``tenants`` per D-13), ``created_at`` /
``updated_at`` defaults, an ``ix_<t>_tenant_id`` index, a
``tg_<t>_set_updated_at`` BEFORE-UPDATE trigger reusing the shared
``set_updated_at_timestamp()`` utility, and RLS ENABLE + FORCE + the
D-29 unconditional-OR ``<t>_tenant_isolation`` policy.

Coded columns (``entity_type``, ``registration_type``,
``document_type``, ``contact_type``, ``payment_terms``, ``currency``)
are TEXT validated app-side against the seeded ``lookups`` rows (flag 4,
option b); no new PG enums.

Unqualified identifiers throughout, per the migration convention
(``env.py`` sets ``search_path`` inside the alembic transaction).

Downgrade reverses creation (seed delete, then per-table policy -> RLS
disable -> trigger -> index -> table). No CASCADE.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e5a2c8b13d40"
down_revision: Union[str, Sequence[str], None] = "d3f7a1c92b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Uniform per-table objects (index / trigger / RLS / policy) are applied
# in a loop; the CREATE TABLE bodies differ and are explicit below.
_TABLES: tuple[str, ...] = (
    "tenant_legal_profile",
    "tenant_tax_registrations",
    "tenant_billing_profile",
    "tenant_contacts",
    "tenant_documents",
    "tenant_onboarding",
)

# New lookup list_names this migration owns (for downgrade cleanup).
_SEED_LIST_NAMES: tuple[str, ...] = (
    "entity_type",
    "tax_registration_type",
    "document_type",
    "contact_type",
    "payment_terms",
    "currency",
)


def upgrade() -> None:
    # ---- 1. Tables (explicit DDL each) -------------------------------

    op.execute(
        """
        CREATE TABLE tenant_legal_profile (
            id                   UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id            UUID        NOT NULL,
            legal_entity_name    TEXT        NOT NULL,
            entity_type          TEXT        NOT NULL,
            registration_number  TEXT        NULL,
            incorporation_date   DATE        NULL,
            registered_address   TEXT        NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id   UUID        NULL,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id   UUID        NULL,
            CONSTRAINT pk_tenant_legal_profile PRIMARY KEY (id),
            CONSTRAINT uq_tenant_legal_profile_tenant UNIQUE (tenant_id),
            CONSTRAINT fk_tenant_legal_profile_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_legal_profile_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_legal_profile_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_legal_profile_name_length
                CHECK (length(legal_entity_name) BETWEEN 1 AND 200),
            CONSTRAINT ck_tenant_legal_profile_entity_type_not_empty
                CHECK (length(btrim(entity_type)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_tax_registrations (
            id                   UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id            UUID        NOT NULL,
            registration_type    TEXT        NOT NULL,
            registration_number  TEXT        NOT NULL,
            jurisdiction         TEXT        NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id   UUID        NULL,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id   UUID        NULL,
            CONSTRAINT pk_tenant_tax_registrations PRIMARY KEY (id),
            CONSTRAINT uq_tenant_tax_registrations_tenant_type_number
                UNIQUE (tenant_id, registration_type, registration_number),
            CONSTRAINT fk_tenant_tax_registrations_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_tax_registrations_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_tax_registrations_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_tax_registrations_number_length
                CHECK (
                    (registration_type = 'PAN'   AND char_length(registration_number) = 10)
                    OR (registration_type = 'GSTIN' AND char_length(registration_number) = 15)
                    OR (registration_type NOT IN ('PAN', 'GSTIN'))
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_billing_profile (
            id                    UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id             UUID        NOT NULL,
            payment_terms         TEXT        NULL,
            currency              TEXT        NULL,
            billing_email         TEXT        NULL,
            billing_contact_name  TEXT        NULL,
            billing_address       TEXT        NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id    UUID        NULL,
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id    UUID        NULL,
            CONSTRAINT pk_tenant_billing_profile PRIMARY KEY (id),
            CONSTRAINT uq_tenant_billing_profile_tenant UNIQUE (tenant_id),
            CONSTRAINT fk_tenant_billing_profile_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_billing_profile_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_billing_profile_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_billing_profile_email_lowercase
                CHECK (billing_email IS NULL OR billing_email = lower(billing_email)),
            CONSTRAINT ck_tenant_billing_profile_email_format
                CHECK (
                    billing_email IS NULL
                    OR billing_email ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_contacts (
            id                   UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id            UUID        NOT NULL,
            contact_type         TEXT        NOT NULL,
            name                 TEXT        NOT NULL,
            email                TEXT        NULL,
            phone                TEXT        NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id   UUID        NULL,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id   UUID        NULL,
            CONSTRAINT pk_tenant_contacts PRIMARY KEY (id),
            CONSTRAINT fk_tenant_contacts_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_contacts_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_contacts_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_contacts_name_length
                CHECK (length(name) BETWEEN 1 AND 200),
            CONSTRAINT ck_tenant_contacts_email_lowercase
                CHECK (email IS NULL OR email = lower(email)),
            CONSTRAINT ck_tenant_contacts_email_format
                CHECK (
                    email IS NULL
                    OR email ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_documents (
            id                   UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id            UUID        NOT NULL,
            document_type        TEXT        NOT NULL,
            gcs_object_uri       TEXT        NOT NULL,
            file_name            TEXT        NULL,
            content_type         TEXT        NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id   UUID        NULL,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id   UUID        NULL,
            CONSTRAINT pk_tenant_documents PRIMARY KEY (id),
            CONSTRAINT fk_tenant_documents_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_documents_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_documents_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_documents_uri_not_empty
                CHECK (length(btrim(gcs_object_uri)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_onboarding (
            id                    UUID        NOT NULL DEFAULT uuidv7(),
            tenant_id             UUID        NOT NULL,
            current_step          TEXT        NULL,
            section_status        JSONB       NOT NULL DEFAULT '{}'::jsonb,
            completed_at          TIMESTAMPTZ NULL,
            completed_by_user_id  UUID        NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_user_id    UUID        NULL,
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id    UUID        NULL,
            CONSTRAINT pk_tenant_onboarding PRIMARY KEY (id),
            CONSTRAINT uq_tenant_onboarding_tenant UNIQUE (tenant_id),
            CONSTRAINT fk_tenant_onboarding_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_onboarding_completed_by
                FOREIGN KEY (completed_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_onboarding_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT fk_tenant_onboarding_updated_by
                FOREIGN KEY (updated_by_user_id) REFERENCES platform_users (id)
                ON DELETE RESTRICT ON UPDATE RESTRICT,
            CONSTRAINT ck_tenant_onboarding_completed_pair
                CHECK (
                    (completed_at IS NULL AND completed_by_user_id IS NULL)
                    OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL)
                )
        )
        """
    )

    # ---- 2. Uniform per-table index / trigger / RLS / policy ---------
    for t in _TABLES:
        op.execute(f"CREATE INDEX ix_{t}_tenant_id ON {t} (tenant_id)")
        op.execute(
            f"CREATE TRIGGER tg_{t}_set_updated_at "
            f"BEFORE UPDATE ON {t} FOR EACH ROW "
            f"EXECUTE FUNCTION set_updated_at_timestamp()"
        )
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {t}_tenant_isolation ON {t}
                FOR ALL
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
                    OR current_setting('app.user_type', TRUE) = 'PLATFORM'
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
                    OR current_setting('app.user_type', TRUE) = 'PLATFORM'
                )
            """
        )

    # ---- 3. Lookups seed ---------------------------------------------
    # tenant_region gains INDIA (the enum value was added in migration
    # d3f7a1c92b64; this is the display row). US/EU already seeded at
    # display_order 1/2 (Step 3.6), so INDIA is 3.
    op.execute(
        """
        INSERT INTO lookups (list_name, code, display_name, display_order, is_active)
        VALUES
            ('tenant_region', 'INDIA', 'India', 3, TRUE),

            ('entity_type', 'PRIVATE_LIMITED',      'Private Limited',      1, TRUE),
            ('entity_type', 'PUBLIC_LIMITED',       'Public Limited',       2, TRUE),
            ('entity_type', 'LLP',                  'Limited Liability Partnership', 3, TRUE),
            ('entity_type', 'OPC',                  'One Person Company',   4, TRUE),
            ('entity_type', 'PARTNERSHIP',          'Partnership',          5, TRUE),
            ('entity_type', 'SOLE_PROPRIETORSHIP',  'Sole Proprietorship',  6, TRUE),
            ('entity_type', 'CORPORATION',          'Corporation',          7, TRUE),

            ('tax_registration_type', 'PAN',   'PAN',   1, TRUE),
            ('tax_registration_type', 'TAN',   'TAN',   2, TRUE),
            ('tax_registration_type', 'GSTIN', 'GSTIN', 3, TRUE),
            ('tax_registration_type', 'VAT',   'VAT',   4, TRUE),
            ('tax_registration_type', 'EIN',   'EIN',   5, TRUE),

            ('document_type', 'CERTIFICATE_OF_INCORPORATION', 'Certificate of Incorporation', 1, TRUE),
            ('document_type', 'PAN_CARD',                     'PAN Card',                     2, TRUE),
            ('document_type', 'GST_CERTIFICATE',              'GST Registration Certificate', 3, TRUE),
            ('document_type', 'TAX_CERTIFICATE',              'Tax Certificate',              4, TRUE),
            ('document_type', 'ADDRESS_PROOF',                'Address Proof',                5, TRUE),
            ('document_type', 'BANK_PROOF',                   'Bank Proof',                   6, TRUE),
            ('document_type', 'SIGNED_AGREEMENT',             'Signed Agreement (MSA/DPA)',   7, TRUE),
            ('document_type', 'OTHER',                        'Other',                        8, TRUE),

            ('contact_type', 'PRIMARY',   'Primary',   1, TRUE),
            ('contact_type', 'BILLING',   'Billing',   2, TRUE),
            ('contact_type', 'TECHNICAL', 'Technical', 3, TRUE),
            ('contact_type', 'LEGAL',     'Legal',     4, TRUE),

            ('payment_terms', 'ADVANCE',        'Advance Payment', 1, TRUE),
            ('payment_terms', 'DUE_ON_RECEIPT', 'Due on Receipt', 2, TRUE),
            ('payment_terms', 'NET_15',         'Net 15',         3, TRUE),
            ('payment_terms', 'NET_30',         'Net 30',         4, TRUE),
            ('payment_terms', 'NET_45',         'Net 45',         5, TRUE),
            ('payment_terms', 'NET_60',         'Net 60',         6, TRUE),

            ('currency', 'INR', 'Indian Rupee', 1, TRUE),
            ('currency', 'USD', 'US Dollar',    2, TRUE),
            ('currency', 'EUR', 'Euro',         3, TRUE)
        """
    )


def downgrade() -> None:
    # 1. Remove seed rows (INDIA only from tenant_region; whole lists for
    #    the vocabularies this migration introduced).
    op.execute(
        "DELETE FROM lookups WHERE list_name = 'tenant_region' AND code = 'INDIA'"
    )
    names = ", ".join(f"'{n}'" for n in _SEED_LIST_NAMES)
    op.execute(f"DELETE FROM lookups WHERE list_name IN ({names})")

    # 2. Drop per-table objects then tables, reverse order. No CASCADE.
    for t in reversed(_TABLES):
        op.execute(f"DROP POLICY {t}_tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP TRIGGER tg_{t}_set_updated_at ON {t}")
        op.execute(f"DROP INDEX ix_{t}_tenant_id")
        op.execute(f"DROP TABLE {t}")
