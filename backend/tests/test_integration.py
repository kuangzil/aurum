import json
import os

import httpx
import pytest

from backend.tests.conftest import ROOT, free_port

QUERY = "Research whether a momentum-based strategy could work for gold trading."
BODY = {"session_id": "integration-demo", "message": QUERY}


def assert_research(payload):
    assert payload["session_id"] == BODY["session_id"]
    assert payload["status"] == "completed"
    assert payload["validation"]["verdict"] == "insufficient_evidence"
    assert payload["research"]["evidence_kind"] == "synthetic"
    a2a = [event for event in payload["trace"] if event["agent"] == "a2a"]
    assert [event["stage"] for event in a2a] == ["discovering", "discovered", "sent", "received"]
    assert len({event["message_id"] for event in a2a}) == 1
    assert "does not establish strategy profitability" in payload["reply"]


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
    assert result["status"] == "validation_unavailable"
    assert result["validation"] is None
    assert result["research"]["evidence"]
    assert any(event["stage"] == "failed" for event in result["trace"])
    assert "No independent verdict was obtained" in result["reply"]


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
    assert events[0]["event"]["stage"] == "planning"
    assert any(event.get("event", {}).get("agent") == "validation" for event in events)
    assert events[-1]["type"] == "result"
    assert_research(events[-1]["result"])


@pytest.mark.e2e
def test_nextjs_proxy_to_final_response(services, launch):
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
    assert degraded["status"] == "validation_unavailable"
    services["research"].terminate()
    services["research"].wait(timeout=5)
    assert httpx.post(url + "/api/chat", json=BODY).status_code == 503
