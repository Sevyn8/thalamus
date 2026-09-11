"""Transport clients. ``identity.py`` deliberately does not exist: identity
arrives resolved on ``ingress.ready`` and existence is enforced by the
composite FK; no Identity Service client exists yet.
"""

from __future__ import annotations
