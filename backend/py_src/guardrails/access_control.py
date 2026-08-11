"""Access control and session validation."""

import time
from py_src.utils.errors import GuardrailError


class AccessControl:
    """Enforces user ownership and session validity."""

    SESSION_TIMEOUT_HOURS = 24

    @staticmethod
    def user_owns_resource(user_id, resource_owner_id):
        """
        Check if a user owns a resource.

        Args:
            user_id: The user making the request
            resource_owner_id: The user who owns the resource

        Returns:
            Boolean
        """
        if not user_id or not resource_owner_id:
            return False
        return user_id == resource_owner_id

    @staticmethod
    def validate_session(session):
        """
        Validate a session object.

        Args:
            session: Dict with user_id, created_at, etc.

        Returns:
            Dict with 'valid' bool and 'reason' string (if invalid)
        """
        if not isinstance(session, dict):
            return {"valid": False, "reason": "Session must be a dict"}

        user_id = session.get("user_id")
        created_at = session.get("created_at")

        if not user_id:
            return {"valid": False, "reason": "user_id required"}

        if not created_at:
            return {"valid": False, "reason": "created_at required"}

        # Check if session is expired
        now = time.time()
        age_hours = (now - created_at) / 3600
        if age_hours > AccessControl.SESSION_TIMEOUT_HOURS:
            return {"valid": False, "reason": "Session expired"}

        return {"valid": True}

    @staticmethod
    def check_permission(user_id, resource_owner_id, permission_type):
        """
        Check if a user has permission to act on a resource.

        This system has no roles or shared/admin access -- the only access
        rule that actually exists anywhere else in the codebase is data
        ownership (a user's sessions, history, and profile belong only to
        them). So that's the whole rule here: ownership grants full
        permission (read/write alike); anyone else is denied. There's no
        ACL database to build for a system with exactly one access rule.

        Args:
            user_id: The user requesting access
            resource_owner_id: The user who owns the resource being accessed
            permission_type: 'read', 'write', etc. (informational --
                ownership grants both under this model)

        Returns:
            True if permitted

        Raises:
            GuardrailError: If either ID is missing, or user does not own the resource
        """
        if not user_id or not resource_owner_id:
            raise GuardrailError(
                "Permission check requires both user_id and resource_owner_id",
                "AccessControl"
            )

        if not AccessControl.user_owns_resource(user_id, resource_owner_id):
            raise GuardrailError(
                f"User does not have {permission_type} permission for this resource",
                "AccessControl"
            )

        return True
