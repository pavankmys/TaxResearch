"""Object store interface and implementations."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


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
        except self._s3_client.exceptions.NoSuchKey:
            return False

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


def make_object_store(settings: Any) -> ObjectStore:
    """
    Factory function to create an ObjectStore based on settings.

    Args:
        settings: Settings object with object_store configuration.

    Returns:
        An ObjectStore instance.

    Raises:
        ValueError: If the object_store type is unknown.
    """
    if settings.object_store == "local":
        return LocalFolderObjectStore(settings.local_store_path)
    elif settings.object_store == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url if settings.s3_endpoint_url else None,
            access_key=settings.s3_access_key if settings.s3_access_key else None,
            secret_key=settings.s3_secret_key if settings.s3_secret_key else None,
        )
    else:
        raise ValueError(f"Unknown object_store type: {settings.object_store}")
