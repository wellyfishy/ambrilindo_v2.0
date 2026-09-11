import os
import sys
from django.apps import AppConfig


class BackendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend'

    def ready(self):
        # Hindari start worker ganda saat development reload atau management commands
        is_manage_command = any(arg in sys.argv for arg in ['makemigrations', 'migrate', 'check', 'test', 'shell'])
        if not is_manage_command:
            if os.environ.get('RUN_MAIN') == 'true' or 'runserver' not in sys.argv:
                try:
                    from .utils import start_sync_queue_worker
                    start_sync_queue_worker()
                except Exception:
                    pass

