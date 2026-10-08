"""The shared object store as a FastAPI dependency (raw files, page images, uploads)."""

from functools import lru_cache

from taxresearch_storage import ObjectStore, make_object_store

from app.settings import get_settings


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    """Build the store named by the settings once per process."""
    settings = get_settings()
    return make_object_store(
        settings.object_store,
        local_path=settings.local_store_path,
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
