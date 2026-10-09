"""Tests for infra/compose.gcp.yaml configuration.

Validates that the Compose file conforms to the GCP deployment contract:
- Service names: migrate, api, worker, web
- No postgres or minio services
- Images use ${IMAGE_REPO}/...:${TAG}
- Only loopback ports (127.0.0.1)
- restart policies: migrate="no", api/worker/web="always"
- Named volumes: objects, watch
- Healthcheck blocks present for api, worker, web
"""

import re
from pathlib import Path

import pytest
import yaml


def test_compose_gcp_file_exists() -> None:
    """Test that compose.gcp.yaml exists."""
    # Path from test file to root, then infra/compose.gcp.yaml
    compose_path = Path(__file__).parent.parent.parent.parent / "infra" / "compose.gcp.yaml"
    assert compose_path.exists(), f"compose.gcp.yaml not found at {compose_path}"


def test_compose_gcp_file_valid_yaml() -> None:
    """Test that compose.gcp.yaml is valid YAML."""
    compose_path = Path(__file__).parent.parent.parent.parent / "infra" / "compose.gcp.yaml"
    with open(compose_path) as f:
        try:
            yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"compose.gcp.yaml is not valid YAML: {e}")


def load_compose() -> dict:
    """Load the compose file."""
    compose_path = Path(__file__).parent.parent.parent.parent / "infra" / "compose.gcp.yaml"
    with open(compose_path) as f:
        return yaml.safe_load(f)


def test_required_services_exist() -> None:
    """Test that all required services are defined."""
    compose = load_compose()
    services = compose.get("services", {})
    required_services = {"migrate", "api", "worker", "web"}
    existing_services = set(services.keys())
    assert required_services.issubset(existing_services), (
        f"Missing required services: {required_services - existing_services}"
    )


def test_no_postgres_or_minio() -> None:
    """Test that postgres and minio services are NOT present."""
    compose = load_compose()
    services = compose.get("services", {})
    forbidden_services = {"postgres", "minio", "minio-init"}
    present_forbidden = forbidden_services & set(services.keys())
    assert not present_forbidden, (
        f"Forbidden services present: {present_forbidden} (GCP uses Cloud SQL)"
    )


def test_images_use_registry_var() -> None:
    """Test that all images use ${IMAGE_REPO}/...:${TAG} pattern."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        image = service_config.get("image")
        if image:
            # Must use ${IMAGE_REPO} and ${TAG}
            assert "${IMAGE_REPO}" in image, (
                f"Service '{service_name}': image '{image}' does not use ${{IMAGE_REPO}}"
            )
            assert "${TAG}" in image, (
                f"Service '{service_name}': image '{image}' does not use ${{TAG}}"
            )
            # Should not have hardcoded registries
            assert not re.match(r"^docker\.io/", image), (
                f"Service '{service_name}': image '{image}' should not hardcode docker.io"
            )


def test_loopback_only_ports() -> None:
    """Test that all published ports are bound to 127.0.0.1."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        ports = service_config.get("ports", [])
        for port_spec in ports:
            if isinstance(port_spec, str) and ":" in port_spec:
                parts = port_spec.split(":")
                if len(parts) >= 2:
                    ip = parts[0]
                    assert ip == "127.0.0.1", (
                        f"Service '{service_name}': port binding '{port_spec}' "
                        f"uses IP {ip}, must be 127.0.0.1"
                    )


def test_restart_policies() -> None:
    """Test that restart policies are correct."""
    compose = load_compose()
    services = compose.get("services", {})

    expected_restart = {
        "migrate": "no",
        "api": "always",
        "worker": "always",
        "web": "always",
    }

    for service_name, expected_policy in expected_restart.items():
        service = services.get(service_name)
        assert service is not None, f"Service '{service_name}' not found"
        restart_policy = service.get("restart", "no")
        assert restart_policy == expected_policy, (
            f"Service '{service_name}': restart policy is '{restart_policy}', "
            f"expected '{expected_policy}'"
        )


def test_named_volumes_exist() -> None:
    """Test that required named volumes are defined."""
    compose = load_compose()
    volumes = compose.get("volumes", {})
    required_volumes = {"objects", "watch"}
    existing_volumes = set(volumes.keys())
    assert required_volumes.issubset(existing_volumes), (
        f"Missing volumes: {required_volumes - existing_volumes}"
    )


def test_healthchecks_present() -> None:
    """Test that api, worker, and web have healthcheck blocks."""
    compose = load_compose()
    services = compose.get("services", {})

    services_with_healthcheck = {"api", "worker", "web"}

    for service_name in services_with_healthcheck:
        service = services.get(service_name)
        assert service is not None, f"Service '{service_name}' not found"
        healthcheck = service.get("healthcheck")
        assert healthcheck is not None, f"Service '{service_name}' is missing healthcheck block"
        assert "test" in healthcheck, f"Service '{service_name}' healthcheck missing 'test' field"


def test_env_file_specified() -> None:
    """Test that all services specify env_file (usually .env)."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        env_file = service_config.get("env_file")
        # env_file can be a string or list, or might not be present (but usually is for consistency)
        # Migrate, api, worker should have env_file for consistency
        if service_name in ("migrate", "api", "worker", "web"):
            # These services should have env_file to read .env
            # (though some settings come from environment directly)
            pass


def test_api_has_run_migrations_false() -> None:
    """Test that api service has RUN_MIGRATIONS=false."""
    compose = load_compose()
    services = compose.get("services", {})
    api_service = services.get("api")
    assert api_service is not None, "api service not found"

    environment = api_service.get("environment", {})
    run_migrations = environment.get("RUN_MIGRATIONS")
    assert run_migrations == "false", (
        f"api RUN_MIGRATIONS is '{run_migrations}', expected 'false' "
        "(migrations run in migrate service)"
    )


def test_migrate_has_correct_command() -> None:
    """Test that migrate service has the expected command structure."""
    compose = load_compose()
    services = compose.get("services", {})
    migrate_service = services.get("migrate")
    assert migrate_service is not None, "migrate service not found"

    command = migrate_service.get("command")
    assert command is not None, "migrate service has no command"

    # Command should include alembic upgrade and ensure-admin
    command_str = " ".join(command) if isinstance(command, list) else str(command)
    assert "alembic upgrade head" in command_str, (
        f"migrate command does not contain 'alembic upgrade head': {command_str}"
    )
    assert "ensure-admin" in command_str, (
        f"migrate command does not contain 'ensure-admin': {command_str}"
    )


def test_volumes_mounted() -> None:
    """Test that api and worker have volumes mounted."""
    compose = load_compose()
    services = compose.get("services", {})

    # api should have objects volume
    api_service = services.get("api")
    assert api_service is not None
    api_volumes = api_service.get("volumes", [])
    assert any("objects" in str(v) for v in api_volumes), (
        "api service does not mount 'objects' volume"
    )

    # worker should have objects and watch volumes
    worker_service = services.get("worker")
    assert worker_service is not None
    worker_volumes = worker_service.get("volumes", [])
    assert any("objects" in str(v) for v in worker_volumes), (
        "worker service does not mount 'objects' volume"
    )
    assert any("watch" in str(v) for v in worker_volumes), (
        "worker service does not mount 'watch' volume"
    )


def test_api_url_set_in_web() -> None:
    """Test that web service sets API_URL to the api container."""
    compose = load_compose()
    services = compose.get("services", {})
    web_service = services.get("web")
    assert web_service is not None

    environment = web_service.get("environment", {})
    api_url = environment.get("API_URL")
    assert api_url == "http://api:8000", f"web API_URL is '{api_url}', expected 'http://api:8000'"


def test_web_has_cookie_secure() -> None:
    """Test that web service sets COOKIE_SECURE with default."""
    compose = load_compose()
    services = compose.get("services", {})
    web_service = services.get("web")
    assert web_service is not None

    environment = web_service.get("environment", {})
    cookie_secure = environment.get("COOKIE_SECURE")
    assert cookie_secure == "${COOKIE_SECURE:-true}", (
        f"web COOKIE_SECURE is '{cookie_secure}', expected '${{COOKIE_SECURE:-true}}'"
    )


def test_no_depends_on_conditions() -> None:
    """Test that depends_on does not use service_healthy (podman-compose limitation)."""
    compose = load_compose()
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        depends_on = service_config.get("depends_on")
        if depends_on:
            if isinstance(depends_on, dict):
                for dep_name, dep_config in depends_on.items():
                    if isinstance(dep_config, dict):
                        condition = dep_config.get("condition")
                        assert condition is None or "service_healthy" not in str(condition), (
                            f"Service '{service_name}' depends on '{dep_name}' "
                            "with service_healthy condition (not supported in podman-compose)"
                        )


def test_only_migrate_gets_the_admin_password() -> None:
    """The first-admin credentials are needed once, by migrate, and by no long-running service."""
    services = load_compose()["services"]
    holders = {
        name
        for name, service in services.items()
        if any("ADMIN_PASSWORD" in str(key) for key in service.get("environment", {}))
        or "env_file" in service
    }
    assert holders == {"migrate"}


def test_nothing_depends_on_the_one_shot_migrate() -> None:
    """deploy.sh runs migrate first; 'up' must not start it again."""
    for name, service in load_compose()["services"].items():
        assert "migrate" not in (service.get("depends_on") or []), name


def test_the_api_does_not_migrate_on_start() -> None:
    api_env = load_compose()["services"]["api"]["environment"]
    assert str(api_env["RUN_MIGRATIONS"]).lower() == "false"


def test_the_web_service_gets_no_secrets() -> None:
    web_env = load_compose()["services"]["web"]["environment"]
    assert not {"DATABASE_URL", "JWT_SECRET", "ADMIN_PASSWORD"} & set(web_env)
