from .cubby_service import CubbyService
from .task_service import TaskService

class LifecycleService:

    @staticmethod
    def run():

        reservation_count = (
            CubbyService.release_expired_reservations()
        )

        expired_task_count = (
            TaskService.expire_storage_tasks()
        )

        return {
            "expired_reservations": reservation_count,
            "expired_tasks": expired_task_count,
        }