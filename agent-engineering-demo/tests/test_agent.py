import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from openai import AsyncOpenAI
from business import FinanceStore, Principal
from seed import seed
from backends import open_backend
from catalog import CapabilityPolicy, ToolFailure
from runtime import execute_call, run_agent


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "demo.sqlite3"
    seed(path)
    return path


@pytest.mark.parametrize("tenant,user,amount,record", [
    ("demo-a", "alice", "8420.50", "RE-9958"),
    ("demo-a", "bob", "9100.00", "RE-BOB"),
    ("demo-b", "alice", "123.45", "RE-OTHER"),
])
@pytest.mark.parametrize("mode", ["local", "mcp"])
async def test_identity_isolation(db, tenant, user, amount, record, mode):
    async with open_backend(mode, db, Principal(tenant, user)) as backend:
        assert (await backend.call("query_balance", {}))["amount_decimal"] == amount
        found = await backend.call("find_reimbursements", {"keyword": "办公设备", "limit": 3})
        assert [row["id"] for row in found["items"]] == [record]


def test_literal_search_empty_and_not_found(db):
    store = FinanceStore(db, Principal("demo-a", "alice"))
    assert store.find_reimbursements("' OR 1=1 --", 3)["items"] == []
    assert store.find_reimbursements("%", 3)["items"] == []
    assert store.find_reimbursements("不存在", 3)["items"] == []
    assert len(store.find_reimbursements("", 10)["items"]) == 2
    limited = store.find_reimbursements("", 1)
    assert len(limited["items"]) == 1 and limited["has_more"]
    assert FinanceStore(db, Principal("missing", "alice")).query_balance() == {"found": False}


@pytest.mark.parametrize("name,arguments", [
    ("query_balance", '{"user_id":"bob"}'),
    ("query_balance", "not-json"),
    ("find_reimbursements", '{"keyword":"办公设备","limit":0}'),
    ("find_reimbursements", '{"keyword":"办公设备","limit":true}'),
    ("delete_account", "{}"),
])
def test_host_rejects_bad_calls(name, arguments):
    policy = CapabilityPolicy()
    policy.load("finance-readonly")
    with pytest.raises(ToolFailure):
        policy.parse(name, arguments, policy.offered())


def test_skill_activation_cannot_elevate_old_snapshot():
    policy = CapabilityPolicy()
    old_offered = policy.offered()
    assert set(old_offered) == {"load_skill"}
    policy.load("finance-readonly")
    with pytest.raises(ToolFailure, match="tool_not_allowed"):
        policy.parse("query_balance", "{}", old_offered)
    assert "query_balance" in policy.offered()


def function_call(call_id, name, args):
    return {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id,
            "name": name, "arguments": json.dumps(args), "status": "completed"}


def response_payload(output, index):
    return {"id": f"resp_{index}", "object": "response", "created_at": 0,
            "model": "fixture-model", "status": "completed", "output": output}


@pytest.mark.parametrize("mode", ["local", "mcp"])
async def test_actual_sdk_serialization_and_full_loop(db, mode):
    requests = []
    steps = [
        [{"type": "reasoning", "id": "rs_fixture", "summary": [], "encrypted_content": "fixture"},
         function_call("skill", "load_skill", {"name": "finance-readonly"})],
        [function_call("balance", "query_balance", {}),
         function_call("archive", "find_reimbursements", {"keyword": "办公设备", "limit": 3})],
        [{"type": "message", "id": "msg_fixture", "role": "assistant", "status": "completed",
          "content": [{"type": "output_text", "text": "查询完成", "annotations": []}]}],
    ]

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests) - 1
        return httpx.Response(200, json=response_payload(steps[index], index))

    async with AsyncOpenAI(api_key="offline-fixture", max_retries=0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        async with open_backend(mode, db, Principal("demo-a", "alice")) as backend:
            assert await run_agent(client, backend, "fixture-model", "余额和办公设备报销") == "查询完成"
    assert len(requests) == 3
    assert [tool["name"] for tool in requests[0]["tools"]] == ["load_skill"]
    assert "query_balance" in {tool["name"] for tool in requests[1]["tools"]}
    assert any(item["type"] == "reasoning" for item in requests[1]["input"] if "type" in item)
    outputs = {item["call_id"]: json.loads(item["output"])
               for item in requests[2]["input"] if item.get("type") == "function_call_output"}
    assert outputs["balance"]["data"]["amount_decimal"] == "8420.50"
    assert outputs["archive"]["data"]["items"][0]["id"] == "RE-9958"
    assert requests[2]["store"] is False


async def test_timeout_returns_correlated_error():
    class SlowBackend:
        async def call(self, name, args):
            await asyncio.sleep(1)
    policy = CapabilityPolicy()
    policy.load("finance-readonly")
    call = SimpleNamespace(name="query_balance", arguments="{}", call_id="slow")
    result = await execute_call(policy, SlowBackend(), call, policy.offered(), 0.001, "fixture")
    assert result["call_id"] == "slow"
    assert json.loads(result["output"])["error"]["code"] == "tool_timeout"


async def test_loop_budget_stops_repeated_calls(db):
    class EndlessResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(status="completed", output_text="", output=[SimpleNamespace(
                type="function_call", name="load_skill", arguments='{"name":"finance-readonly"}',
                call_id="repeated")])
    client = SimpleNamespace(responses=EndlessResponses())
    async with open_backend("local", db, Principal("demo-a", "alice")) as backend:
        with pytest.raises(RuntimeError, match="步数超过上限"):
            await run_agent(client, backend, "fixture-model", "余额", max_steps=2)
        with pytest.raises(RuntimeError, match="次数超过上限"):
            await run_agent(client, backend, "fixture-model", "余额", max_calls=1)


async def test_large_result_is_not_silently_truncated():
    class LargeBackend:
        async def call(self, name, args):
            return {"value": "x" * 24000}
    policy = CapabilityPolicy()
    policy.load("finance-readonly")
    call = SimpleNamespace(name="query_balance", arguments="{}", call_id="large")
    result = await execute_call(policy, LargeBackend(), call, policy.offered(), 1, "fixture")
    assert json.loads(result["output"])["error"]["code"] == "result_too_large"
