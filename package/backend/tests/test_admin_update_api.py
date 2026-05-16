import app.config as config_module
from app.services import update_service


def _admin_auth_headers(client):
    response = client.post(
        "/api/admin/login",
        json={
            "username": config_module.settings.ADMIN_USERNAME,
            "password": config_module.settings.ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _fake_latest_release():
    return {
        "tag_name": "v1.0.3",
        "html_url": "https://github.com/mumu-0922/GankAIGC/releases/tag/v1.0.3",
        "published_at": "2026-05-11T00:00:00Z",
        "name": "v1.0.3",
    }


def test_current_app_version_uses_packaged_version_without_source_mount(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_VERSION", "1.0.7", raising=False)
    monkeypatch.setattr(update_service, "get_source_version_tag", lambda: "v1.0.3")

    assert update_service.get_current_app_version() == "v1.0.7"


def test_git_revision_status_fetches_remote_tags(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module.settings, "VPS_UPDATE_WORKDIR", str(tmp_path), raising=False)
    calls = []

    def fake_run_command(args, timeout=15):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "abc\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(update_service, "_run_command", fake_run_command)

    update_service.get_git_revision_status()

    assert ["git", "fetch", "--tags", "origin", "main"] in calls


def test_admin_update_status_reports_manual_docker_update_command(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_VERSION", "1.0.0", raising=False)
    monkeypatch.setattr(update_service, "fetch_latest_release", _fake_latest_release)
    monkeypatch.setattr(
        update_service,
        "get_git_revision_status",
        lambda: {
            "current_commit": None,
            "remote_commit": None,
            "source_update_available": None,
            "error": "source repo is not mounted",
        },
    )

    response = client.get("/api/admin/update/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    data = response.json()
    assert data["current_version"] == "v1.0.0"
    assert data["latest_version"] == "v1.0.3"
    assert data["release_update_available"] is True
    assert data["vps_update_enabled"] is False
    assert data["can_run_update"] is False
    assert data["update_mode"] == "manual_ssh"
    assert "git fetch --tags origin main" in data["setup_command"]
    assert "git pull --ff-only origin main" in data["setup_command"]
    assert "docker compose --env-file .env.docker up -d --build" in data["setup_command"]
    assert "docker compose --env-file .env.docker pull" not in data["setup_command"]
    assert "docker.sock" not in data["setup_command"]
    assert data["disabled_reason"] in (None, "")


def test_admin_update_status_reports_latest_when_source_tag_matches_release(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_VERSION", "1.0.1", raising=False)
    monkeypatch.setattr(update_service, "fetch_latest_release", _fake_latest_release)
    monkeypatch.setattr(update_service, "get_current_app_version", lambda: "v1.0.3")
    monkeypatch.setattr(
        update_service,
        "get_git_revision_status",
        lambda: {
            "current_commit": "abc",
            "remote_commit": "abc",
            "source_update_available": False,
            "error": None,
        },
    )

    response = client.get("/api/admin/update/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    data = response.json()
    assert data["current_version"] == "v1.0.3"
    assert data["latest_version"] == "v1.0.3"
    assert data["release_update_available"] is False
    assert data["source_update_available"] is None
    assert data["can_run_update"] is False


def test_admin_update_run_always_rejects_remote_docker_execution(client, monkeypatch):
    response = client.post("/api/admin/update/run", headers=_admin_auth_headers(client))

    assert response.status_code == 403
    assert "SSH 到 VPS 执行升级命令" in response.json()["detail"]


def test_vps_update_never_runs_from_web_process_even_when_docker_socket_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(update_service.os.path, "exists", lambda path: path == "/var/run/docker.sock")

    can_run, reason = update_service.can_run_vps_update()

    assert can_run is False
    assert reason in (None, "")


def test_start_vps_update_cannot_spawn_shell(monkeypatch):
    def fail_popen(*args, **kwargs):
        raise AssertionError("subprocess.Popen must not be called")

    monkeypatch.setattr(update_service.subprocess, "Popen", fail_popen)

    try:
        update_service.start_vps_update()
    except RuntimeError as exc:
        assert "SSH 到 VPS 项目目录执行升级命令" in str(exc)
