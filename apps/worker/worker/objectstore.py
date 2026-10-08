"""Object store for the worker: a re-export of taxresearch_storage plus a settings wrapper.

The implementation lives in packages/storage so that the API can share it. Import from here or
from taxresearch_storage; both name the same classes.
"""

from typing import Any

from taxresearch_storage import (
    LocalFolderObjectStore,
    ObjectStore,
    S3ObjectStore,
    _validate_key,
    raw_key,
    sniff_mime,
)
from taxresearch_storage import make_object_store as _make_object_store

__all__ = [
    "LocalFolderObjectStore",
    "ObjectStore",
    "S3ObjectStore",
    "_validate_key",
    "make_object_store",
    "raw_key",
    "sniff_mime",
]


def make_object_store(settings: Any) -> ObjectStore:  # noqa: ANN401 - any object with the fields
    """Build the store named by the worker settings (object_store, local_store_path, s3_*).

    Raises:
        ValueError: If the object_store type is unknown.
    """
    return _make_object_store(
        settings.object_store,
        local_path=settings.local_store_path,
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
