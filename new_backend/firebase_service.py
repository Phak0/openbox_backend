from firebase_admin import firestore

from openbox_backend.firebase import get_firestore_client


def _serialize_document(document):
    return {
        "document_id": document.id,
        "filename": document.original_filename,
        "file_name": document.file.name if document.file else None,
        "storage_path": document.storage_path or None,
        "page_count": document.page_count,
        "copies": document.copies,
        "printed_pages": document.page_count * document.copies,
        "print_settings": document.print_settings or {},
        "amount": str(document.amount),
    }


def _serialize_box(task):
    if not task.box:
        return None

    return {
        "id": task.box.id,
        "name": task.box.name,
    }


def _serialize_cubby(task):
    if not task.cubby:
        return None

    return {
        "id": task.cubby.id,
        "code": task.cubby.code,
        "type": task.cubby.cubby_type,
        "status": task.cubby.status,
    }


def _build_task_payload(task):
    documents = [
        _serialize_document(document)
        for document in task.documents.all().order_by("created_at")
    ]

    return {
        # Task identity
        "task_id": task.id,
        "task_type": task.task_type,

        # Task lifecycle
        "status": task.status,
        "box_status": task.box_status,

        # Access
        "access_code": task.access_code or None,

        # Physical destination
        "box_id": task.box_id,
        "box": _serialize_box(task),

        # Cubby
        "cubby_id": task.cubby_id,
        "cubby": _serialize_cubby(task),

        # Payment / task cost
        "amount": str(task.amount),

        # Storage information
        "storage_until": task.storage_until,

        # Task-specific execution settings
        "task_data": task.task_data or {},

        # Documents to process
        "documents": documents,

        # Lifecycle timestamps
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def create_task_in_firestore(task):
    """
    Create the complete task packet that the physical box
    uses to execute the task.
    """

    db = get_firestore_client()

    task_ref = (
        db.collection("tasks")
        .document(str(task.id))
    )

    task_ref.set(_build_task_payload(task))


def update_task_in_firestore(task):
    """
    Synchronize the task packet in Firestore.

    Used when task information other than just box_status
    changes, such as box assignment, cubby assignment,
    access code, storage expiry, etc.
    """

    db = get_firestore_client()

    task_ref = (
        db.collection("tasks")
        .document(str(task.id))
    )

    task_ref.set(
        _build_task_payload(task),
        merge=True,
    )


def update_task_status_in_firestore(task):
    """
    Update the task lifecycle/status information in Firestore.
    """

    db = get_firestore_client()

    task_ref = (
        db.collection("tasks")
        .document(str(task.id))
    )

    task_ref.set(
        {
            "status": task.status,
            "box_status": task.box_status,
            "completed_at": task.completed_at,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


def update_box_status_in_firestore(task):
    """
    Update the physical box status in Firestore.
    """

    db = get_firestore_client()

    task_ref = (
        db.collection("tasks")
        .document(str(task.id))
    )

    task_ref.set(
        {
            "box_status": task.box_status,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


def update_task_assignment_in_firestore(task):
    """
    Update Firestore after a task is assigned to a physical
    box and/or cubby.

    This is particularly important for Instant Print because
    the task starts without a box and is assigned when the
    access code is used at a physical box.
    """

    db = get_firestore_client()

    task_ref = (
        db.collection("tasks")
        .document(str(task.id))
    )

    task_ref.set(
        {
            "box_id": task.box_id,
            "box": _serialize_box(task),
            "cubby_id": task.cubby_id,
            "cubby": _serialize_cubby(task),
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )