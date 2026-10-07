"""Shared building blocks for tests: generated credentials and common API steps.

Import what a test needs, for example::

    from support import add_member, create_project, register_user
"""

from support.api import (
    Item,
    Project,
    User,
    add_member,
    create_item,
    create_project,
    log_in,
    promote_to_superuser,
    register_user,
)
from support.credentials import new_email, new_password
from support.paths import REPO_ROOT
from support.sync import (
    InProcessRemote,
    new_change,
    newly_accepted,
    pull,
    push,
    replayed,
    results_with,
)

__all__ = [
    "InProcessRemote",
    "Item",
    "Project",
    "REPO_ROOT",
    "User",
    "add_member",
    "create_item",
    "create_project",
    "log_in",
    "new_change",
    "new_email",
    "new_password",
    "newly_accepted",
    "promote_to_superuser",
    "pull",
    "push",
    "register_user",
    "replayed",
    "results_with",
]
