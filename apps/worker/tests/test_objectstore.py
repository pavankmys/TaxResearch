"""The worker's objectstore module re-exports taxresearch_storage and wraps the settings."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import taxresearch_storage
from worker import objectstore


def test_names_are_the_shared_implementations() -> None:
    assert objectstore.LocalFolderObjectStore is taxresearch_storage.LocalFolderObjectStore
    assert objectstore.S3ObjectStore is taxresearch_storage.S3ObjectStore
    assert objectstore.ObjectStore is taxresearch_storage.ObjectStore
    assert objectstore.sniff_mime is taxresearch_storage.sniff_mime


def test_settings_wrapper_builds_local_store(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        object_store="local",
        local_store_path=str(tmp_path / "store"),
        s3_bucket="",
        s3_endpoint_url="",
        s3_access_key="",
        s3_secret_key="",
    )
    store = objectstore.make_object_store(settings)
    assert isinstance(store, objectstore.LocalFolderObjectStore)


def test_settings_wrapper_rejects_unknown_kind() -> None:
    settings = SimpleNamespace(
        object_store="tape",
        local_store_path="",
        s3_bucket="",
        s3_endpoint_url="",
        s3_access_key="",
        s3_secret_key="",
    )
    with pytest.raises(ValueError, match="Unknown object_store type"):
        objectstore.make_object_store(settings)
