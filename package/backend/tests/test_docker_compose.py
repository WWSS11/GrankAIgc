from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_default_docker_compose_does_not_grant_app_docker_control():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    app_section = compose.split("\n  app:", 1)[1].split("\n  worker:", 1)[0]

    assert "target: /app/source" not in app_section
    assert "/var/run/docker.sock" not in app_section
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/.env.docker" in compose
    assert "target: /app/config/.env.docker" in compose
    assert "- ./:/app/source" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "updater:" not in compose
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/backups" in app_section
    assert "target: /backups" in app_section
    assert "read_only: true" in app_section


def test_default_docker_compose_includes_postgres_backup_service():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  backup:" in compose
    assert "docker-postgres-backup.sh" in compose
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/backups" in compose
    assert "target: /backups" in compose
    assert "BACKUP_RETENTION_DAYS" in compose
    assert "BACKUP_INTERVAL_SECONDS" in compose
    assert "condition: service_healthy" in compose


def test_docker_compose_documents_manual_update_command_only():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "docker compose --env-file .env.docker pull" not in compose
    assert "--profile update" not in compose


def test_docker_env_example_disables_web_triggered_update():
    env_example = (PROJECT_ROOT / ".env.docker.example").read_text(encoding="utf-8")

    assert "VPS_UPDATE_ENABLED=false" in env_example
    assert "VPS_UPDATE_COMMAND" not in env_example
    assert "docker.sock" not in env_example
    assert "git fetch --tags origin main" in env_example
    assert "git pull --ff-only origin main" in env_example
    assert "docker compose --env-file .env.docker up -d --build" in env_example
    assert "docker compose --env-file .env.docker pull" not in env_example
    assert "BACKUP_RETENTION_DAYS=14" in env_example
    assert "BACKUP_INTERVAL_SECONDS=86400" in env_example
    assert "docker-compose.update.yml" not in env_example


def test_ci_creates_runtime_env_file_before_compose_validation():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "cp .env.docker.example .env.docker" in workflow
    assert "docker compose --env-file .env.docker config --quiet" in workflow


def test_ci_validates_update_profile_and_keeps_frontend_dist_artifact():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "--profile update" not in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "package/frontend/dist" in workflow
