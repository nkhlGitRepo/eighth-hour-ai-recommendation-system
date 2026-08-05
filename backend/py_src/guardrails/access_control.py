"""Access control and session validation."""

import time


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
    def check_permission(user_id, resource_id, permission_type):
        """
        Check if user has a specific permission.

        Args:
            user_id: User ID
            resource_id: Resource ID
            permission_type: 'read', 'write', etc.

        Raises:
            GuardrailError: If permission is denied or not implemented

        Note:
            Currently always raises—ACL database not yet implemented.
            In production, query actual ACL database.
        """
        from py_src.utils.errors import GuardrailError
        raise GuardrailError(
            f"Permission check not yet implemented for {permission_type}",
            "AccessControl"
        )
