from apscheduler.schedulers.background import BackgroundScheduler
from new_backend.services.lifecycle_service import (
    LifecycleService
)
from django.core.management import call_command

from django.utils import timezone

from .models import Task

def run_cleanup():
    # This secretly types 'python manage.py cleanup_files' in the background
    try:
        call_command('cleanup_files')
    except Exception as e:
        print(f"Error running automated cleanup: {e}")

def start_automation():
    scheduler = BackgroundScheduler()
    # This sets the robot to check for old files at intervals 
    scheduler.add_job(run_cleanup, 'interval', hours=4)
    scheduler.start()

#//////////////////////////////////////////////
def cleanup_recent_tasks():
    now = timezone.now()

    Task.objects.filter(
        visible_until__lt=now,
        status__in=[
            Task.Status.COMPLETED,
            Task.Status.WITHDRAWN,
        ],
    ).update(visible_until=None)

scheduler = BackgroundScheduler()

scheduler.add_job(
    LifecycleService.run,
    trigger="interval",
    minutes=5
)

scheduler.start()