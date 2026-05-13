import asyncio
import os
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import settings


GITHUB_API_BASE = "https://api.github.com"


def normalize_version(version: str) -> str:
    value = (version or "").strip()
    if not value:
        return "v0.0.0"
    return value if value.startswith("v") else f"v{value}"


def _version_parts(version: str) -> Tuple[int, ...]:
    raw = normalize_version(version).lstrip("v")
    numeric = raw.split("-", 1)[0]
    parts = []
    for item in numeric.split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer_version(latest: Optional[str], current: str) -> bool:
    if not latest:
        return False
    return _version_parts(latest) > _version_parts(current)


def get_source_version_tag() -> Optional[str]:
    if not os.path.isdir(settings.VPS_UPDATE_WORKDIR):
        return None

    try:
        tagged = _run_command(["git", "describe", "--tags", "--exact-match", "HEAD"])
        if tagged.returncode == 0 and tagged.stdout.strip():
            return tagged.stdout.strip()

        latest_tag = _run_command(["git", "describe", "--tags", "--abbrev=0"])
        if latest_tag.returncode == 0 and latest_tag.stdout.strip():
            return latest_tag.stdout.strip()
    except Exception:
        return None

    return None


def get_current_app_version() -> str:
    return normalize_version(get_source_version_tag() or settings.APP_VERSION)


async def fetch_latest_release() -> Dict[str, Any]:
    url = f"{GITHUB_API_BASE}/repos/{settings.RELEASE_REPO}/releases/latest"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        return response.json()


def _run_command(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=settings.VPS_UPDATE_WORKDIR,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_git_revision_status() -> Dict[str, Any]:
    if not os.path.isdir(settings.VPS_UPDATE_WORKDIR):
        return {
            "current_commit": None,
            "remote_commit": None,
            "source_update_available": None,
            "error": f"源码目录不存在: {settings.VPS_UPDATE_WORKDIR}",
        }

    try:
        current = _run_command(["git", "rev-parse", "HEAD"])
        if current.returncode != 0:
            raise RuntimeError((current.stderr or current.stdout).strip())

        fetch = _run_command(["git", "fetch", "--tags", "origin", "main"])
        if fetch.returncode != 0:
            raise RuntimeError((fetch.stderr or fetch.stdout).strip())

        remote = _run_command(["git", "rev-parse", "origin/main"])
        if remote.returncode != 0:
            raise RuntimeError((remote.stderr or remote.stdout).strip())

        current_commit = current.stdout.strip()
        remote_commit = remote.stdout.strip()
        return {
            "current_commit": current_commit,
            "remote_commit": remote_commit,
            "source_update_available": bool(current_commit and remote_commit and current_commit != remote_commit),
            "error": None,
        }
    except Exception as exc:
        return {
            "current_commit": None,
            "remote_commit": None,
            "source_update_available": None,
            "error": str(exc),
        }


def _update_enabled_message() -> str:
    return (
        "请使用最新 docker-compose.yml 重建 app 容器，确认 /app/source 和 "
        "/var/run/docker.sock 已挂载，并在 .env.docker 设置 VPS_UPDATE_ENABLED=true。"
    )


def get_vps_update_command() -> str:
    return "docker compose --env-file .env.docker --profile update up --build -d updater"


def can_run_vps_update() -> Tuple[bool, Optional[str]]:
    if not settings.VPS_UPDATE_ENABLED:
        return False, "VPS 在线更新未启用。" + _update_enabled_message()
    if not os.path.isdir(settings.VPS_UPDATE_WORKDIR):
        return False, f"源码目录不存在: {settings.VPS_UPDATE_WORKDIR}"
    if not os.path.exists("/var/run/docker.sock"):
        return False, "容器内未挂载 /var/run/docker.sock，无法调用宿主机 Docker。"
    if not os.environ.get("GANKAIGC_HOST_PROJECT_DIR"):
        return False, "容器内未设置 GANKAIGC_HOST_PROJECT_DIR，请使用最新 docker-compose.yml 重建 app 容器。"
    return True, None


async def build_update_status() -> Dict[str, Any]:
    current_version = get_current_app_version()
    latest_release: Dict[str, Any] = {}
    release_error = None
    try:
        latest_release = await fetch_latest_release()
    except Exception as exc:
        release_error = str(exc)

    latest_version = normalize_version(latest_release.get("tag_name") or current_version)
    can_run_update, disabled_reason = can_run_vps_update()
    git_status = get_git_revision_status()

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "release_update_available": is_newer_version(latest_version, current_version),
        "release_name": latest_release.get("name") or latest_version,
        "release_url": latest_release.get("html_url") or f"https://github.com/{settings.RELEASE_REPO}/releases",
        "published_at": latest_release.get("published_at"),
        "release_error": release_error,
        "source_update_available": git_status.get("source_update_available"),
        "current_commit": git_status.get("current_commit"),
        "remote_commit": git_status.get("remote_commit"),
        "git_error": git_status.get("error"),
        "vps_update_enabled": settings.VPS_UPDATE_ENABLED,
        "can_run_update": can_run_update,
        "disabled_reason": disabled_reason,
        "setup_command": get_vps_update_command(),
        "manual_update_command": settings.VPS_UPDATE_COMMAND,
    }


def start_vps_update() -> Dict[str, Any]:
    can_run_update, disabled_reason = can_run_vps_update()
    if not can_run_update:
        raise RuntimeError(disabled_reason or "VPS 在线更新不可用")

    os.makedirs(os.path.dirname(settings.VPS_UPDATE_LOG_FILE), exist_ok=True)
    with open(settings.VPS_UPDATE_LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now(timezone.utc).isoformat()}] start vps update\n")
        log_file.flush()
        subprocess.Popen(
            settings.VPS_UPDATE_COMMAND,
            cwd=settings.VPS_UPDATE_WORKDIR,
            shell=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    return {
        "started": True,
        "message": "VPS 更新任务已启动，服务会在拉取代码并重建容器后短暂重启。",
        "command": settings.VPS_UPDATE_COMMAND,
        "log_file": settings.VPS_UPDATE_LOG_FILE,
    }
