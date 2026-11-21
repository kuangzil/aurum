import json
import os
import sqlite3
import sys

import httpx
import pytest

from backend.tests.conftest import ROOT, free_port

QUERY = "Research whether a momentum-based strategy could work for gold trading."
BODY = {"session_id": "integration-demo", "message": QUERY}


def assert_research(payload):
    assert payload["session_id"] == BODY["session_id"]
    assert payload["status"] == "completed"
    assert len(payload["validation"]) == 2
    assert all(review["provenance_check"] == "passed" for review in payload["validation"])
    assert len(payload["research"]) == 2
    a2a = [event for event in payload["trace"] if event["agent"] == "a2a"]
    assert [event["stage"] for event in a2a] == ["discovering", "discovered", "sent", "received"] * 2
    assert len({event["message_id"] for event in a2a}) == 2
    assert payload["round_id"] in payload["reply"]


def test_real_a2a_between_independent_services(services):
    assert services["validator"].pid != services["research"].pid != os.getpid()
    card = httpx.get(services["validation_url"] + "/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    response = httpx.post(services["research_url"] + "/chat", json=BODY, timeout=10)
    assert response.status_code == 200, response.text
    assert_research(response.json())
    # Uvicorn access log proves that the separate process actually handled RPC.
    assert 'POST /a2a/jsonrpc HTTP/1.1" 200' in services["validator_log"].read_text()


def test_validator_unavailability(services):
    services["validator"].terminate()
    services["validator"].wait(timeout=5)
    response = httpx.post(services["research_url"] + "/chat", json=BODY, timeout=10)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "waiting_review"
    assert result["validation"] == []
    assert len(result["research"]) == 2
    assert any(event["stage"] == "failed" for event in result["trace"])
    assert "待完成" in result["reply"]


def test_a2a_server_rejects_invalid_research(services):
    response = httpx.post(services["validation_url"] + "/a2a/jsonrpc", headers={"A2A-Version": "1.0"}, json={
        "jsonrpc": "2.0", "id": "invalid-demo", "method": "SendMessage",
        "params": {"message": {"messageId": "invalid-payload", "role": "ROLE_USER", "parts": [{"data": {"query": "missing fields"}}]}},
    })
    assert "error" in response.json()
    assert "result" not in response.json()


def test_progress_stream(services):
    response = httpx.post(services["research_url"] + "/chat", json=BODY, headers={"Accept": "application/x-ndjson"}, timeout=10)
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["event"]["stage"] == "context_cache_miss"
    assert any(event.get("event", {}).get("agent") == "validation" for event in events)
    assert events[-1]["type"] == "result"
    assert_research(events[-1]["result"])


@pytest.mark.e2e
def test_nextjs_proxy_to_final_response(services, launch, tmp_path):
    assert (ROOT / ".next/BUILD_ID").exists(), "Run npm run build first"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    launch(["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(port)], url, {"RESEARCH_API_URL": services["research_url"]})
    response = httpx.post(url + "/api/chat", json=BODY, timeout=15)
    assert response.status_code == 200, response.text
    assert_research(response.json())
    streamed = httpx.post(url + "/api/chat", json=BODY, headers={"Accept": "application/x-ndjson"}, timeout=15)
    events = [json.loads(line) for line in streamed.text.splitlines()]
    assert_research(events[-1]["result"])
    for invalid in [None, [], {"session_id": 3, "message": "test"}, {"session_id": "s", "message": " "}]:
        assert httpx.post(url + "/api/chat", content=json.dumps(invalid), headers={"Content-Type": "application/json"}).status_code == 400
    services["validator"].terminate()
    services["validator"].wait(timeout=5)
    degraded = httpx.post(url + "/api/chat", json=BODY, timeout=15).json()
    assert degraded["status"] == "waiting_review"
    with sqlite3.connect(tmp_path / 'aurum.sqlite3') as conn:
        before = conn.execute('SELECT COUNT(*) FROM factor_experiments').fetchone()[0]
    launch([sys.executable, '-m', 'uvicorn', 'backend.tests.research_fixture_server:validation_app',
            '--factory', '--host', '127.0.0.1', '--port', services['validation_url'].rsplit(':', 1)[1]],
           services['validation_url'] + '/.well-known/agent-card.json',
           {'VALIDATION_AGENT_URL': services['validation_url']})
    resumed = httpx.post(url + '/api/chat', json={**BODY, 'message': 'Resume review',
                         'round_id': degraded['round_id']}, timeout=15)
    assert resumed.status_code == 200, resumed.text
    assert_research(resumed.json())
    with sqlite3.connect(tmp_path / 'aurum.sqlite3') as conn:
        assert conn.execute('SELECT COUNT(*) FROM factor_experiments').fetchone()[0] == before
    services["research"].terminate()
    services["research"].wait(timeout=5)
    assert httpx.post(url + "/api/chat", json=BODY).status_code == 503
