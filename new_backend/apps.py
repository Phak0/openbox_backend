from django.apps import AppConfig
import os

class NewBackendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'new_backend'

    def ready(self):
        # Starts scheduler once. 'RUN_MAIN' check prevents two robots from starting.
        if os.environ.get('RUN_MAIN') == 'true':
            from . import scheduler
            scheduler.start_automation()