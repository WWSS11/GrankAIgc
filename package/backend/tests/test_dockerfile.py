from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_dockerfile_does_not_install_docker_control_tools_in_app_image():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    app_stage = dockerfile.split("FROM ${DOCKER_IMAGE_PREFIX}library/python:3.11-slim AS app", 1)[1]

    assert "ARG DOCKER_COMPOSE_VERSION" not in app_stage
    assert "docker-cli" not in app_stage
    assert "docker.io" not in app_stage
    assert "git config --system --add safe.directory /app/source" not in app_stage
    assert "docker compose version" not in app_stage


def test_dockerfile_copies_packaged_version_file():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY package/VERSION /app/package/VERSION" in dockerfile
