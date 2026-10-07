from .models import PrivateCubbyActivityLog


def log_cubby_activity(private_cubby, action, performed_by=None, description="", metadata=None):
    PrivateCubbyActivityLog.objects.create(
        private_cubby=private_cubby,
        performed_by=performed_by,
        action=action,
        description=description,
        metadata=metadata or {}
    )