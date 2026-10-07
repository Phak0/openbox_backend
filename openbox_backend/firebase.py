from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

from django.conf import settings


BASE_DIR = Path(__file__).resolve().parent.parent

FIREBASE_CREDENTIALS_PATH = (
    BASE_DIR / "firebase" / "service-account.json"
)


def initialize_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(
            FIREBASE_CREDENTIALS_PATH
        )

        options = {}

        if getattr(settings, "FIREBASE_STORAGE_BUCKET", None):
            options["storageBucket"] = settings.FIREBASE_STORAGE_BUCKET

        firebase_admin.initialize_app(
            cred,
            options,
        )


def get_firestore_client():
    initialize_firebase()
    return firestore.client()