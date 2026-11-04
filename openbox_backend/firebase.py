from pathlib import Path
import logging

import firebase_admin
from firebase_admin import credentials, firestore

from django.conf import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

FIREBASE_CREDENTIALS_PATH = (
    BASE_DIR / "firebase" / "service-account.json"
)


def initialize_firebase():
    if not firebase_admin._apps:
        if not FIREBASE_CREDENTIALS_PATH.exists():
            return None

        import os
        import django
        if not settings.configured:
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'openbox_backend.settings')
            django.setup()

        try:
            cred = credentials.Certificate(
                FIREBASE_CREDENTIALS_PATH
            )

            options = {}

            if getattr(settings, "FIREBASE_STORAGE_BUCKET", None):
                options["storageBucket"] = settings.FIREBASE_STORAGE_BUCKET

            return firebase_admin.initialize_app(
                cred,
                options,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Firebase: {e}")
            return None


def get_firestore_client():
    initialize_firebase()
    if not firebase_admin._apps:
        return None
    try:
        return firestore.client()
    except Exception as e:
        logger.warning(f"Failed to get Firestore client: {e}")
        return None
