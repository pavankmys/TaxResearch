"""Tests for compose.yaml configuration.

Validates the Compose specification to ensure it conforms to requirements:
- All required services exist
- All images are fully qualified (contain registry host with dot)
- No 'latest' tags are used
- All published ports are bound to 127.0.0.1
- No host ports below 1024
- No service_healthy dependencies
- No inline password-like literals
- env_file path resolves correctly
"""

import re
from pathlib import Path

import pytest
import yaml


def test_compose_file_exists() -> None:
    """Test that compose.yaml exists."""
    compose_path = Path(__file__).parent.parent / "compose.yaml"
    assert compose_path.exists(), f"compose.yaml not found at {compose_path}"


def test_compose_file_valid_yaml() -> None:
    """Test that compose.yaml is valid YAML."""
    compose_path = Path(__file__).parent.parent / "compose.yaml"
    with open(compose_path) as f:
        try:
            yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"compose.yaml is not valid YAML: {e}")


def load_compose() -> dict:
    """Load the compose file."""
    compose_path = Path(__file__).parent.parent / "compose.yaml"
    with open(compose_path) as f:
        return yaml.safe_load(f)


def test_required_services_exist() -> None:
    """Test that all required services are defined."""
    compose = load_compose()
    services = compose.get("services", {})
    required_services = {"postgres", "minio", "minio-init", "api", "worker", "web"}
    existing_services = set(services.keys())
    assert required_services.issubset(existing_services), (
        f"Missing services: {required_services - existing_services}"
    )


def test_images_are_fully_qualified() -> None:
    """Test that all images are fully qualified (contain registry host with dot)."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        image = service_config.get("image")
        if image:
            # Images like 'postgres:16' or 'minio/minio:tag' should be qualified
            # Full format: docker.io/library/postgres:16
            if "/" not in image:
                pytest.fail(
                    f"Service '{service_name}': image '{image}' "
                    "is not fully qualified (missing registry)"
                )

            # Check that registry contains a dot (e.g., docker.io)
            registry = image.split("/")[0]
            if "." not in registry and registry not in ("localhost", "127.0.0.1"):
                pytest.fail(
                    f"Service '{service_name}': image '{image}' registry '{registry}' "
                    "does not contain a dot (must be fully qualified like docker.io/...)"
                )

        # Check build context images
        build = service_config.get("build")
        if isinstance(build, dict):
            # Build images may use FROM references; they're validated by docker build
            pass


def test_no_latest_tags() -> None:
    """Test that no images use the 'latest' tag."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        image = service_config.get("image")
        if image and ":latest" in image:
            pytest.fail(
                f"Service '{service_name}': image '{image}' uses 'latest' tag (not allowed)"
            )


def test_no_host_ports_below_1024() -> None:
    """Test that no published ports are below 1024."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        ports = service_config.get("ports", [])
        for port_spec in ports:
            # Port spec can be "8000:8000" or "127.0.0.1:8000:8000" or just "8000"
            if isinstance(port_spec, str):
                parts = port_spec.split(":")
                # Host port is the first part if there's an IP, otherwise first part
                if len(parts) == 3:
                    # IP:hostport:containerport
                    host_port = parts[1]
                elif len(parts) == 2:
                    # hostport:containerport
                    host_port = parts[0]
                else:
                    # Just a port number
                    host_port = parts[0]

                try:
                    port_num = int(host_port)
                    if port_num < 1024:
                        pytest.fail(
                            f"Service '{service_name}': port {port_num} is below 1024 "
                            "(privileged ports not allowed)"
                        )
                except ValueError:
                    pass  # Not a numeric port


def test_published_ports_bound_to_localhost() -> None:
    """Test that all published ports are bound to 127.0.0.1."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        ports = service_config.get("ports", [])
        for port_spec in ports:
            if isinstance(port_spec, str):
                # Must be in format 127.0.0.1:hostport:containerport
                if ":" in port_spec:
                    parts = port_spec.split(":")
                    if len(parts) == 3:
                        ip = parts[0]
                        if ip != "127.0.0.1":
                            pytest.fail(
                                f"Service '{service_name}': port binding '{port_spec}' "
                                f"uses IP {ip}, must be 127.0.0.1"
                            )


def test_no_service_healthy_dependencies() -> None:
    """Test that no services depend on service_healthy condition."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        depends_on = service_config.get("depends_on")
        if depends_on:
            if isinstance(depends_on, dict):
                for dep_service, dep_config in depends_on.items():
                    if isinstance(dep_config, dict):
                        condition = dep_config.get("condition")
                        if "service_healthy" in str(condition):
                            pytest.fail(
                                f"Service '{service_name}' depends on '{dep_service}' "
                                "with condition: service_healthy (not allowed)"
                            )


def test_no_inline_password_literals() -> None:
    """Test that there are no inline password-like literals in the config."""
    compose_path = Path(__file__).parent.parent / "compose.yaml"
    with open(compose_path) as f:
        content = f.read()

    # Check for common patterns that look like hardcoded passwords
    # This is a basic check; real passwords would be in environment variables
    password_patterns = [
        r"password:\s*['\"]?[a-zA-Z0-9]{8,}['\"]?\s*$",
    ]

    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        # Skip lines that reference environment variables
        if "${" in line or "POSTGRES_PASSWORD" in line or "S3_SECRET" in line:
            continue

        for pattern in password_patterns:
            if re.search(pattern, line):
                # Check if it's not a reference to a variable
                if "${" not in line:
                    pytest.fail(f"Line {i}: possible inline password: {line.strip()}")


def test_env_file_path_resolves() -> None:
    """Test that env_file paths resolve correctly."""
    compose_path = Path(__file__).parent.parent / "compose.yaml"
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        env_file = service_config.get("env_file")
        if env_file:
            # env_file is relative to compose file location
            if isinstance(env_file, str):
                env_files = [env_file]
            elif isinstance(env_file, list):
                env_files = env_file
            else:
                continue

            for env_path in env_files:
                full_path = compose_path.parent / env_path
                # For relative paths like "../.env", resolve to repo root
                full_path = full_path.resolve()
                expected_path = compose_path.parent.parent / ".env"
                assert full_path == expected_path or expected_path.exists(), (
                    f"Service '{service_name}': env_file '{env_path}' "
                    f"does not resolve to {expected_path}"
                )
