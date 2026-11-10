import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", help="Test through a built Next.js production server")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--e2e"):
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Run npm run build, then pytest --e2e"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def launch(tmp_path):
    processes = []

    def start(command, url, env=None):
        log_path = tmp_path / f"service-{len(processes)}.log"
        log = log_path.open("w+")
        process = subprocess.Popen(
            command, cwd=ROOT, env={**os.environ, "LLM_MODE": "mock", **(env or {})},
            stdout=log, stderr=subprocess.STDOUT,
        )
        processes.append((process, log))
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(log_path.read_text())
            try:
                if httpx.get(url, timeout=0.5).status_code == 200:
                    return process, log_path
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError(f"Service did not start: {log_path.read_text()}")

    yield start
    for process, log in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()


@pytest.fixture
def services(launch):
    validator_url = f"http://127.0.0.1:{free_port()}"
    research_url = f"http://127.0.0.1:{free_port()}"
    validator, validator_log = launch(
        [sys.executable, "-m", "uvicorn", "backend.validation_agent.service:create_app", "--factory", "--host", "127.0.0.1", "--port", validator_url.rsplit(":", 1)[1]],
        validator_url + "/.well-known/agent-card.json", {"VALIDATION_AGENT_URL": validator_url},
    )
    research, _ = launch(
        [sys.executable, "-m", "uvicorn", "backend.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", research_url.rsplit(":", 1)[1]],
        research_url + "/health", {"VALIDATION_AGENT_URL": validator_url, "A2A_TIMEOUT_SECONDS": "2"},
    )
    return {"validation_url": validator_url, "research_url": research_url, "validator": validator, "research": research, "validator_log": validator_log}
