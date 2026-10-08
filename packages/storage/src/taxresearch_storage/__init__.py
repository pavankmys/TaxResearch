"""Object storage shared by the worker and the API.

Holds the ObjectStore interface and its two implementations (a local folder and S3 or an
S3-compatible service), key validation, a factory that does not depend on either app's settings,
and a sniffer for the file types the pipeline accepts.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

__all__ = [
    "LocalFolderObjectStore",
    "ObjectStore",
    "S3ObjectStore",
    "make_object_store",
    "raw_key",
    "sniff_mime",
]

# How many leading bytes sniff_mime looks at. Matches the acquire stage.
_HEAD_BYTES = 1024

# Error codes boto3 uses for a missing key on head_object (which has no body to name the error).
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class ObjectStore(ABC):
    """Abstract base class for object storage implementations."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """
        Store data at the given key.

        Args:
            key: Object key/path.
            data: Binary data to store.
            content_type: Optional MIME type.
        """
        pass

    @abstractmethod
    def get(self, key: str) -> bytes:
        """
        Retrieve data at the given key.

        Args:
            key: Object key/path.

        Returns:
            Binary data.

        Raises:
            KeyError: If the key does not exist.
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if a key exists.

        Args:
            key: Object key/path.

        Returns:
            True if the key exists, False otherwise.
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete the object at the given key.

        Args:
            key: Object key/path.
        """
        pass

    @abstractmethod
    def list(self, prefix: str) -> list[str]:
        """
        List all keys with the given prefix.

        Args:
            prefix: Prefix to filter by.

        Returns:
            List of keys.
        """
        pass


def _validate_key(key: str) -> None:
    """
    Validate a key for path traversal safety.

    Raises ValueError if the key is unsafe.
    """
    if not key:
        raise ValueError("Key cannot be empty")

    # Reject absolute paths
    if key.startswith("/") or key.startswith("\\"):
        raise ValueError("Key cannot be absolute")

    # Reject .. (path traversal)
    if ".." in key:
        raise ValueError("Key cannot contain '..'")

    # Reject backslashes (Windows path separators)
    if "\\" in key:
        raise ValueError("Key cannot contain backslashes")

    # Reject NUL characters
    if "\x00" in key:
        raise ValueError("Key cannot contain NUL")

    # Reject keys with empty segments (consecutive slashes)
    if "//" in key:
        raise ValueError("Key cannot contain empty path segments")


def raw_key(sha256: str) -> str:
    """Object key for raw bytes. Content-addressed, so it is never overwritten."""
    return f"raw/{sha256[:2]}/{sha256}"


def sniff_mime(data: bytes) -> str | None:
    """Identify a file by its first bytes. Only PDF and HTML are recognised.

    Same rules as the worker's acquire stage: ``%PDF-`` anywhere in the first 1024 bytes is a
    PDF, and ``<html`` or ``<!doctype html`` (any case) is HTML. Anything else returns None.
    """
    head = data[:_HEAD_BYTES]
    if b"%PDF-" in head:
        return "application/pdf"
    lowered = head.lower()
    if b"<html" in lowered or b"<!doctype html" in lowered:
        return "text/html"
    return None


class LocalFolderObjectStore(ObjectStore):
    """Object store backed by a local filesystem directory."""

    def __init__(self, root: str | Path) -> None:
        """
        Initialize the local folder store.

        Args:
            root: Root directory path.
        """
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store data at the given key."""
        _validate_key(key)

        path = (self._root / key).resolve()

        # Verify the resolved path stays within root
        try:
            path.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Key resolves outside root: {key}") from None

        # Create parent directories
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        """Retrieve data at the given key."""
        _validate_key(key)

        path = (self._root / key).resolve()

        # Verify the resolved path stays within root
        try:
            path.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Key resolves outside root: {key}") from None

        if not path.exists():
            raise KeyError(f"Key not found: {key}")

        return path.read_bytes()

    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        _validate_key(key)

        path = (self._root / key).resolve()

        # Verify the resolved path stays within root
        try:
            path.relative_to(self._root)
        except ValueError:
            return False

        return path.exists()

    def delete(self, key: str) -> None:
        """Delete the object at the given key."""
        _validate_key(key)

        path = (self._root / key).resolve()

        # Verify the resolved path stays within root
        try:
            path.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Key resolves outside root: {key}") from None

        if path.exists():
            path.unlink()

    def list(self, prefix: str) -> list[str]:
        """List all keys with the given prefix."""
        if prefix:
            _validate_key(prefix)

        prefix_path = self._root / prefix if prefix else self._root
        prefix_path_resolved = prefix_path.resolve()

        # Verify the resolved path stays within root
        try:
            prefix_path_resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Prefix resolves outside root: {prefix}") from None

        if not prefix_path_resolved.exists():
            return []

        keys = []
        for item in prefix_path_resolved.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(self._root)
                # Use forward slashes for consistency
                keys.append(str(rel_path).replace("\\", "/"))

        return sorted(keys)


class S3ObjectStore(ObjectStore):
    """Object store backed by S3 (or S3-compatible service like MinIO)."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        """
        Initialize the S3 object store.

        Args:
            bucket: S3 bucket name.
            endpoint_url: Optional S3 endpoint URL (for MinIO or other S3-compatible services).
            access_key: AWS access key or MinIO access key.
            secret_key: AWS secret key or MinIO secret key.
        """
        import boto3

        self._bucket = bucket
        self._endpoint_url = endpoint_url

        # Create S3 client
        kwargs: dict[str, Any] = {}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        self._s3_client = boto3.client("s3", **kwargs)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store data at the given key."""
        _validate_key(key)

        kwargs: dict[str, Any] = {}
        if content_type:
            kwargs["ContentType"] = content_type

        self._s3_client.put_object(Bucket=self._bucket, Key=key, Body=data, **kwargs)

    def get(self, key: str) -> bytes:
        """Retrieve data at the given key."""
        _validate_key(key)

        try:
            response = self._s3_client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"].read()
            return bytes(body) if not isinstance(body, bytes) else body
        except self._s3_client.exceptions.NoSuchKey as e:
            raise KeyError(f"Key not found: {key}") from e

    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        _validate_key(key)

        try:
            self._s3_client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            # head_object reports a missing key as a 404 with no error name in the body.
            if str(exc.response.get("Error", {}).get("Code", "")) in _MISSING_CODES:
                return False
            raise

    def delete(self, key: str) -> None:
        """Delete the object at the given key."""
        _validate_key(key)

        self._s3_client.delete_object(Bucket=self._bucket, Key=key)

    def list(self, prefix: str) -> list[str]:
        """List all keys with the given prefix."""
        if prefix:
            _validate_key(prefix)

        keys = []
        paginator = self._s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)

        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    # Skip directory markers
                    if not obj["Key"].endswith("/"):
                        keys.append(obj["Key"])

        return sorted(keys)


def make_object_store(
    kind: str,
    *,
    local_path: str | Path | None,
    bucket: str | None,
    endpoint_url: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> ObjectStore:
    """Build an ObjectStore from plain values. Empty strings count as not set.

    Args:
        kind: "local" for a folder, or "s3" for S3 or an S3-compatible service.
        local_path: Folder for the local store (required when kind is "local").
        bucket: Bucket name (required when kind is "s3").
        endpoint_url: Optional S3 endpoint URL.
        access_key: Optional S3 access key.
        secret_key: Optional S3 secret key.

    Raises:
        ValueError: The kind is unknown, or a required value is missing.
    """
    if kind == "local":
        if not local_path:
            raise ValueError("local object store needs a path")
        return LocalFolderObjectStore(local_path)
    if kind == "s3":
        if not bucket:
            raise ValueError("s3 object store needs a bucket")
        return S3ObjectStore(
            bucket=bucket,
            endpoint_url=endpoint_url or None,
            access_key=access_key or None,
            secret_key=secret_key or None,
        )
    raise ValueError(f"Unknown object_store type: {kind}")
