"""Tests for ObjectStore implementations."""

import tempfile
from pathlib import Path

import pytest
from worker.objectstore import (
    LocalFolderObjectStore,
    S3ObjectStore,
    _validate_key,
)


class TestValidateKey:
    """Tests for key validation."""

    def test_empty_key_raises_error(self) -> None:
        """Test that empty keys are rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_key("")

    def test_absolute_path_with_slash_raises_error(self) -> None:
        """Test that absolute paths with / are rejected."""
        with pytest.raises(ValueError, match="cannot be absolute"):
            _validate_key("/absolute/path")

    def test_absolute_path_with_backslash_raises_error(self) -> None:
        """Test that absolute paths with \\ are rejected."""
        with pytest.raises(ValueError, match="cannot be absolute"):
            _validate_key("\\absolute\\path")

    def test_path_traversal_raises_error(self) -> None:
        """Test that .. path traversal is rejected."""
        with pytest.raises(ValueError, match="cannot contain"):
            _validate_key("../../../etc/passwd")

    def test_backslash_raises_error(self) -> None:
        """Test that backslashes are rejected."""
        with pytest.raises(ValueError, match="cannot contain backslashes"):
            _validate_key("folder\\file.txt")

    def test_nul_character_raises_error(self) -> None:
        """Test that NUL characters are rejected."""
        with pytest.raises(ValueError, match="cannot contain NUL"):
            _validate_key("file\x00name.txt")

    def test_empty_segments_raise_error(self) -> None:
        """Test that consecutive slashes (empty segments) are rejected."""
        with pytest.raises(ValueError, match="cannot contain empty path segments"):
            _validate_key("folder//file.txt")

    def test_valid_key_passes(self) -> None:
        """Test that valid keys pass validation."""
        _validate_key("folder/subfolder/file.txt")
        _validate_key("file.txt")
        _validate_key("deep/nested/structure/file.txt")


class TestLocalFolderObjectStore:
    """Tests for LocalFolderObjectStore."""

    @pytest.fixture
    def store(self) -> tuple[LocalFolderObjectStore, Path]:
        """Create a temporary folder store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = LocalFolderObjectStore(root)
            yield store, root

    def test_put_and_get(self, store: tuple[LocalFolderObjectStore, Path]) -> None:
        """Test basic put and get operations."""
        s, _ = store
        data = b"Hello, World!"

        s.put("file.txt", data)
        retrieved = s.get("file.txt")

        assert retrieved == data

    def test_get_nonexistent_raises_keyerror(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that get on nonexistent key raises KeyError."""
        s, _ = store

        with pytest.raises(KeyError):
            s.get("nonexistent.txt")

    def test_exists_returns_true_for_existing_file(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that exists returns True for existing files."""
        s, _ = store
        data = b"test"

        s.put("file.txt", data)

        assert s.exists("file.txt") is True

    def test_exists_returns_false_for_nonexistent_file(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that exists returns False for nonexistent files."""
        s, _ = store

        assert s.exists("nonexistent.txt") is False

    def test_delete_removes_file(self, store: tuple[LocalFolderObjectStore, Path]) -> None:
        """Test that delete removes a file."""
        s, _ = store

        s.put("file.txt", b"data")
        assert s.exists("file.txt") is True

        s.delete("file.txt")

        assert s.exists("file.txt") is False

    def test_delete_nonexistent_doesnt_error(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that delete on nonexistent file doesn't raise an error."""
        s, _ = store

        s.delete("nonexistent.txt")  # Should not raise

    def test_list_returns_all_keys(self, store: tuple[LocalFolderObjectStore, Path]) -> None:
        """Test that list returns all keys with prefix."""
        s, _ = store

        s.put("dir1/file1.txt", b"1")
        s.put("dir1/file2.txt", b"2")
        s.put("dir2/file3.txt", b"3")

        keys = s.list("dir1/")
        assert sorted(keys) == ["dir1/file1.txt", "dir1/file2.txt"]

    def test_list_empty_prefix_returns_all(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that list with empty prefix returns all files."""
        s, _ = store

        s.put("file1.txt", b"1")
        s.put("dir/file2.txt", b"2")

        keys = s.list("")
        assert sorted(keys) == ["dir/file2.txt", "file1.txt"]

    def test_put_creates_nested_directories(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that put creates nested directories."""
        s, _ = store

        s.put("a/b/c/d/file.txt", b"data")

        assert s.exists("a/b/c/d/file.txt") is True

    def test_path_traversal_attack_rejected(
        self, store: tuple[LocalFolderObjectStore, Path]
    ) -> None:
        """Test that path traversal attacks are rejected."""
        s, root = store

        with pytest.raises(ValueError):
            s.put("../../../etc/passwd", b"evil")

    def test_symlink_escape_rejected(self, store: tuple[LocalFolderObjectStore, Path]) -> None:
        """Test that escaping via symlink resolution is blocked."""
        s, root = store

        # Create a file outside the root
        outside = root.parent / "outside.txt"
        outside.write_bytes(b"outside")

        # Try to access it via a crafted key that resolves outside root
        with pytest.raises(ValueError):
            _validate_key("../outside.txt")

    @pytest.mark.parametrize(
        "malicious_key",
        [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/passwd",
            "\\windows\\system32",
            "file\x00name.txt",
            "file//double/slash",
        ],
    )
    def test_malicious_keys_rejected(
        self, store: tuple[LocalFolderObjectStore, Path], malicious_key: str
    ) -> None:
        """Test that at least 10 malicious keys are rejected."""
        s, _ = store

        with pytest.raises(ValueError):
            s.put(malicious_key, b"data")


class TestS3ObjectStore:
    """Tests for S3ObjectStore (key validation without network)."""

    def test_key_validation_on_put(self) -> None:
        """Test that S3ObjectStore validates keys on put."""

        # Create a fake S3 client
        class FakeBotoClient:
            def put_object(self, **kwargs: dict) -> None:
                pass

            def get_object(self, **kwargs: dict) -> dict:
                return {"Body": None}

            def head_object(self, **kwargs: dict) -> None:
                pass

            def delete_object(self, **kwargs: dict) -> None:
                pass

            class exceptions:
                class NoSuchKey(Exception):
                    pass

        store = S3ObjectStore("test-bucket")
        store._s3_client = FakeBotoClient()  # type: ignore

        # Test that invalid keys are rejected before any S3 call
        with pytest.raises(ValueError):
            store.put("../../../etc/passwd", b"data")

    def test_key_validation_on_get(self) -> None:
        """Test that S3ObjectStore validates keys on get."""

        class FakeBotoClient:
            def put_object(self, **kwargs: dict) -> None:
                pass

            def get_object(self, **kwargs: dict) -> dict:
                return {"Body": None}

            def head_object(self, **kwargs: dict) -> None:
                pass

            def delete_object(self, **kwargs: dict) -> None:
                pass

            class exceptions:
                class NoSuchKey(Exception):
                    pass

        store = S3ObjectStore("test-bucket")
        store._s3_client = FakeBotoClient()  # type: ignore

        with pytest.raises(ValueError):
            store.get("../../../etc/passwd")

    def test_key_validation_on_exists(self) -> None:
        """Test that S3ObjectStore validates keys on exists."""

        class FakeBotoClient:
            def put_object(self, **kwargs: dict) -> None:
                pass

            def get_object(self, **kwargs: dict) -> dict:
                return {"Body": None}

            def head_object(self, **kwargs: dict) -> None:
                pass

            def delete_object(self, **kwargs: dict) -> None:
                pass

            class exceptions:
                class NoSuchKey(Exception):
                    pass

        store = S3ObjectStore("test-bucket")
        store._s3_client = FakeBotoClient()  # type: ignore

        with pytest.raises(ValueError):
            store.exists("../../../etc/passwd")

    def test_key_validation_on_delete(self) -> None:
        """Test that S3ObjectStore validates keys on delete."""

        class FakeBotoClient:
            def put_object(self, **kwargs: dict) -> None:
                pass

            def get_object(self, **kwargs: dict) -> dict:
                return {"Body": None}

            def head_object(self, **kwargs: dict) -> None:
                pass

            def delete_object(self, **kwargs: dict) -> None:
                pass

            class exceptions:
                class NoSuchKey(Exception):
                    pass

        store = S3ObjectStore("test-bucket")
        store._s3_client = FakeBotoClient()  # type: ignore

        with pytest.raises(ValueError):
            store.delete("../../../etc/passwd")

    def test_key_validation_on_list(self) -> None:
        """Test that S3ObjectStore validates keys on list."""

        class FakeBotoClient:
            def put_object(self, **kwargs: dict) -> None:
                pass

            def get_object(self, **kwargs: dict) -> dict:
                return {"Body": None}

            def head_object(self, **kwargs: dict) -> None:
                pass

            def delete_object(self, **kwargs: dict) -> None:
                pass

            def get_paginator(self, **kwargs: dict) -> object:
                return self  # type: ignore

            def paginate(self, **kwargs: dict) -> list:
                return []

            class exceptions:
                class NoSuchKey(Exception):
                    pass

        store = S3ObjectStore("test-bucket")
        store._s3_client = FakeBotoClient()  # type: ignore

        with pytest.raises(ValueError):
            store.list("../../../etc")
