import app.config as config_module
from app.database import SessionLocal
from app.models.models import AdminAuditLog
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
        "tag_name": "v1.0.1",
        "html_url": "https://github.com/mumu-0922/GankAIGC/releases/tag/v1.0.1",
        "published_at": "2026-05-11T00:00:00Z",
        "name": "v1.0.1",
    }


def test_admin_update_status_reports_vps_prerequisites(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_VERSION", "1.0.0", raising=False)
    monkeypatch.setattr(config_module.settings, "VPS_UPDATE_ENABLED", False, raising=False)
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
    assert data["latest_version"] == "v1.0.1"
    assert data["release_update_available"] is True
    assert data["vps_update_enabled"] is False
    assert data["can_run_update"] is False
    assert "docker-compose.update.yml" in data["setup_command"]


def test_admin_update_run_rejects_when_vps_update_disabled(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "VPS_UPDATE_ENABLED", False, raising=False)

    response = client.post("/api/admin/update/run", headers=_admin_auth_headers(client))

    assert response.status_code == 403
    assert "VPS 在线更新未启用" in response.json()["detail"]


def test_admin_update_run_starts_updater_and_writes_audit_log(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "VPS_UPDATE_ENABLED", True, raising=False)
    monkeypatch.setattr(update_service, "can_run_vps_update", lambda: (True, None))

    calls = []

    def fake_start_vps_update():
        calls.append(True)
        return {
            "started": True,
            "message": "VPS 更新任务已启动",
            "command": "docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.update.yml --profile update up --build -d updater",
        }

    monkeypatch.setattr(update_service, "start_vps_update", fake_start_vps_update)

    response = client.post("/api/admin/update/run", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    assert response.json()["started"] is True
    assert calls == [True]

    db = SessionLocal()
    try:
        log = db.query(AdminAuditLog).filter(AdminAuditLog.action == "start_vps_update").one()
        assert "VPS 更新任务已启动" in (log.detail or "")
    finally:
        db.close()
