"""Compatibility seam: work and schedule mutations never change lifecycle state.

Only the authenticated manual status transition checks current lifecycle gates
and records a status decision. Legacy callers remain harmless during rollout.
"""

def advance_project_status(db, project):
    return None


def regress_project_status(db, project):
    return None
