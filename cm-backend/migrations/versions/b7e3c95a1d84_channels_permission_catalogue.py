"""channels_permission_catalogue

Revision ID: b7e3c95a1d84
Revises: a1c4e7f09d2b
Create Date: 2026-08-12

Add CHANNELS to the permission catalogue so a TENANT ADMIN can be granted the right to configure
their own sending channels, and a Sevyn8 operator the right to see whether one is configured.

WHY THIS EXISTS AT ALL. Axon cannot proceed to tenant channel onboarding because of three
absences in Customer Master, not in Axon. This closes the first: ``resource_enum`` held 12 values
and none meant channels, messaging or notifications, so "configure a sending channel" was not
expressible as a permission tuple. ``ADMIN.TENANTS.CONFIGURE.TENANT`` does not exist either, and
every TENANTS.CONFIGURE row is GLOBAL, so a tenant admin could view their own tenant and
configure nothing about it.

THE RESOURCE LIVES UNDER THE ADMIN MODULE, NOT UNDER A NEW AXON MODULE. Every tenant running
Synapse will eventually want channels, so per-tenant module entitlement buys little now, and the
DIS precedent (``a1c4e7f09d2b``) shows that a module costs an enum value plus a lookups row plus
a launcher tile nobody asked for. It can be promoted to its own module later; the reverse is
harder.

============================================================================================
THIS MIGRATION CARRIES CATALOGUE DATA, AND THAT IS A DEPARTURE WORTH STATING
============================================================================================
``core.permissions`` rows are otherwise created by ``scripts/seed_dev_data``, which loads
``data/ithina_dev_seed_data.xlsx``. THAT MECHANISM CANNOT DO THIS JOB, for four reasons found by
reading it rather than assumed:

  1. It is NOT IDEMPOTENT. ``loaders/_base.insert_and_register`` issues a plain
     ``INSERT ... RETURNING id`` with no upsert, so a re-run collides with
     ``uq_permissions_tuple`` and aborts.
  2. Its only re-run path is ``--reset``, which TRUNCATEs tenants, users, roles, stores, org
     nodes and both audit tables.
  3. Its guard refuses only ``environment == "production"``; staging is ``"staging"``.
  4. The workbook holds 37 permission rows with a module value while staging holds 38, so it
     does not reproduce staging and nothing in this repository accounts for the difference.

SO THE WORKBOOK IS NOW BEHIND BY THREE ROWS, DELIBERATELY AND ON THE RECORD. Reconciling it is
separate work, and so is fixing the ``--reset`` hazard, which wants its own argument about what
the guard should be. Neither is done here.

============================================================================================
ADD VALUE AND ITS TRANSACTION RULE
============================================================================================
``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block that later uses the new value,
and Alembic wraps each migration in a transaction. The idiom is an autocommit block so the ALTER
commits independently, exactly as ``a1c4e7f09d2b`` did for ``module_code_enum`` and
``d3f7a1c92b64`` for ``tenant_region_enum``.

THE INSERTS BELOW DO USE THE NEW VALUE, so they are in the outer transaction and depend on the
autocommit block above having committed. That is the whole reason the ALTER cannot simply sit
inline.

APPENDED, NOT POSITIONED. No BEFORE/AFTER clause, so 'CHANNELS' lands at the end of the type.
That is load-bearing rather than incidental: Postgres orders an enum column by declaration order,
the permission list endpoints sort on it, and
``tests/integration/test_rbac_router.py::_permission_sort_tuple`` recomputes that ordering from
``PermissionResource``'s member positions. The Python member is appended to match.

FORWARD-ONLY, per the project's irreversible-enum convention (``d3f7a1c92b64``, ``90cd038ae618``,
``cec8fae734e0``, ``a1c4e7f09d2b``): removing an enum value needs the rename-recreate-cast dance.

============================================================================================
THE GRANTS, AND WHO DELIBERATELY DOES NOT GET THEM
============================================================================================
  OWNER              both TENANT rows. The tenant admin role, audience TENANT, is_system true.
                     It already holds the VIEW/CONFIGURE pair for ORG_NODES, ROLES, STORES and
                     USERS, so this is the established shape rather than a new kind of grant.
                     is_system matters: a permission granted to OWNER reaches tenant admins
                     without each tenant granting it themselves.
  COMPLIANCE_OFFICER VIEW.TENANT only. A sending channel carries consent and sender-registration
                     obligations, and an auditor who cannot see that the channel exists cannot
                     audit its use. NOT CONFIGURE: it is a pure-observer role and holds no
                     CONFIGURE anywhere in the catalogue.
  SUPER_ADMIN        VIEW.GLOBAL. Sevyn8 operators see CONNECTION STATE ONLY and never the
                     credential, which is the tenant's; whether a channel is configured is
                     operational because it explains why a delivery was blocked.

  FINANCE_ADMIN      NOTHING, argued rather than overlooked. A channel has a cost dimension
                     eventually, since WhatsApp and SMS bill per message, but that is a fact
                     about delivery VOLUME and would live in Axon's ledger, not in a channel's
                     connection state. Granting on an anticipated future surface is how grants
                     nobody can later justify get created.

THE AUDIENCE/SCOPE TRIGGER IS SATISFIED BY CONSTRUCTION.
``tg_role_permissions_audience_scope_coherence`` (``5e22b2ca13cc``) rejects a TENANT-audience
role holding a GLOBAL-scope permission. OWNER and COMPLIANCE_OFFICER are TENANT audience and
receive only TENANT-scope rows; SUPER_ADMIN is PLATFORM and receives the GLOBAL one. Nothing here
tests the trigger's edge, and nothing here needs to.

NO ROUTE IS GATED ON THESE YET, AND NO SURFACE RENDERS THEM. Axon has no connection-state table
and the DLT and WABA facts are unknown, so a page would configure nothing. The catalogue is where
a role's shape is expressed; the first route that reads these arrives with the surface.

IDEMPOTENT THROUGHOUT. ``ADD VALUE IF NOT EXISTS`` plus ``ON CONFLICT DO NOTHING`` on both
inserts, so a re-run against a database that already has them is a no-op rather than a
constraint violation.

UNQUALIFIED TABLE NAMES, per ``a1c4e7f09d2b``. ``migrations/env.py`` sets ``search_path`` on the
migration connection so unqualified statements land in the configured schema (D-15).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c95a1d84"
down_revision: Union[str, Sequence[str], None] = "a1c4e7f09d2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The three catalogue rows. `code` is a real NOT NULL column with its own unique constraint, not
# a derived value, and the dotted form is the convention every existing row follows.
_PERMISSIONS = (
    (
        "CHANNELS",
        "VIEW",
        "TENANT",
        "ADMIN.CHANNELS.VIEW.TENANT",
        "View this tenant's sending channels",
    ),
    (
        "CHANNELS",
        "CONFIGURE",
        "TENANT",
        "ADMIN.CHANNELS.CONFIGURE.TENANT",
        "Connect and configure sending channels",
    ),
    (
        "CHANNELS",
        "VIEW",
        "GLOBAL",
        "ADMIN.CHANNELS.VIEW.GLOBAL",
        "View channel connection state platform-wide",
    ),
)

# (role code, permission code). See the header for why each, and why FINANCE_ADMIN is absent.
_GRANTS = (
    ("OWNER", "ADMIN.CHANNELS.VIEW.TENANT"),
    ("OWNER", "ADMIN.CHANNELS.CONFIGURE.TENANT"),
    ("COMPLIANCE_OFFICER", "ADMIN.CHANNELS.VIEW.TENANT"),
    ("SUPER_ADMIN", "ADMIN.CHANNELS.VIEW.GLOBAL"),
)


def upgrade() -> None:
    """Extend resource_enum (autocommit), then seed the rows and their grants."""
    # 1. Extend the enum in its own transaction, because the inserts below USE the new value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE resource_enum ADD VALUE IF NOT EXISTS 'CHANNELS'")

    # 2. The catalogue rows. `id` is left to the DEFAULT uuidv7(), per D-21, the same way the
    #    seed loader does it: the loader strips the Excel's v4 ids so the database mints v7.
    #    BOUND PARAMETERS, NOT INTERPOLATION, and it is not ceremony: one description carries an
    #    apostrophe ("this tenant's sending channels"), which inside a single-quoted SQL literal
    #    ends the string and leaves the rest as a syntax error. The first draft of this migration
    #    interpolated and would have failed on that row. Binding also means the next description
    #    somebody adds cannot reintroduce it.
    for resource, action, scope, code, description in _PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (module, resource, action, scope, code, description)
                VALUES (
                    CAST('ADMIN' AS module_code_enum),
                    CAST(:resource AS resource_enum),
                    CAST(:action AS action_enum),
                    CAST(:scope AS permission_scope_enum),
                    :code,
                    :description
                )
                ON CONFLICT (module, resource, action, scope) DO NOTHING
                """
            ).bindparams(
                resource=resource, action=action, scope=scope, code=code, description=description
            )
        )

    # 3. The grants, resolved by CODE rather than by id. Ids are uuidv7 minted at insert time and
    #    differ per environment, so a literal id here would be correct in exactly one database.
    #
    #    THE SELECT IS THE JOIN AND ALSO THE GUARD: if either the role or the permission is
    #    missing the INSERT writes zero rows rather than failing, which is what makes a re-run
    #    against a partially-seeded database safe. A role that does not exist is not this
    #    migration's to create.
    #
    #    THAT TOLERANCE HAS A COST WORTH NAMING: a typo in a role code here writes nothing and
    #    raises nothing, so the grant is silently absent. The check is
    #    tests/integration/test_permission_enum_parity.py for the enum half, and for the grants
    #    it is the read-back in the step's manual verification:
    #      SELECT p.code, r.code FROM permissions p
    #        JOIN role_permissions rp ON rp.permission_id = p.id
    #        JOIN roles r ON r.id = rp.role_id
    #       WHERE p.resource = 'CHANNELS' ORDER BY 1, 2;   -- expect exactly 4 rows
    for role_code, permission_code in _GRANTS:
        op.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id
                  FROM roles r
                  CROSS JOIN permissions p
                 WHERE r.code = :role_code
                   AND p.code = :permission_code
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            ).bindparams(role_code=role_code, permission_code=permission_code)
        )


def downgrade() -> None:
    """Irreversible: removing an enum value needs rename-recreate-cast."""
    raise NotImplementedError(
        "Removing 'CHANNELS' from resource_enum is not supported. Dropping an enum value "
        "requires the rename-recreate-cast dance (see 90cd038ae618), and the three permission "
        "rows plus their grants would have to be deleted first. Restore from backup if a "
        "rollback is genuinely needed."
    )
