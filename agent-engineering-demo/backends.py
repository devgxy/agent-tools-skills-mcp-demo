"""同一业务工具的本地执行与 MCP 执行适配器。"""
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from business import FinanceStore, Principal
from catalog import BUSINESS_ALLOWLIST, TOOLS, ToolFailure
from jsonschema import Draft202012Validator


class LocalBackend:
    def __init__(self, store):
        self.store = store

    async def call(self, name: str, args: dict):
        functions = {"query_balance": self.store.query_balance,
                     "find_reimbursements": self.store.find_reimbursements}
        if name not in functions:
            raise ToolFailure("tool_not_allowed")
        # 小型演示直接执行短 SQLite 查询；服务端应选择异步驱动或受控线程池。
        return functions[name](**args)


class MCPBackend:
    def __init__(self, session, remote_tools):
        self.session = session
        self.remote_tools = remote_tools

    async def call(self, name: str, args: dict):
        if name not in BUSINESS_ALLOWLIST or name not in self.remote_tools:
            raise ToolFailure("tool_not_allowed")
        tool = self.remote_tools[name]
        Draft202012Validator(tool.inputSchema).validate(args)
        result = await self.session.call_tool(name, arguments=args)
        if result.isError:
            # 服务端异常正文可能有内部细节，不直接回传给模型。
            raise ToolFailure("mcp_tool_error")
        if result.structuredContent is None:
            raise ToolFailure("missing_structured_result")
        if tool.outputSchema:
            Draft202012Validator(tool.outputSchema).validate(result.structuredContent)
        return result.structuredContent


@asynccontextmanager
async def open_backend(mode: str, db_path: Path, principal: Principal):
    if mode == "local":
        yield LocalBackend(FinanceStore(db_path, principal))
        return
    if mode != "mcp":
        raise ValueError("未知 backend")
    # 一个本地子进程只绑定一个 Principal。这是应用的部署选择，不是 MCP 身份保证。
    params = StdioServerParameters(command=sys.executable, args=[
        str(Path(__file__).parent / "mcp_server.py"), "--db", str(db_path.resolve()),
        "--tenant", principal.tenant_id, "--user", principal.user_id],
        env={},  # 不把 OPENAI_API_KEY 传给工具子进程；SDK 只补充基本启动环境。
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
            await session.initialize()  # 1.x 兼容流程；2026-07-28 新协议不要求此握手。
            remote_tools = {}
            cursor = None
            for _ in range(20):
                page = await asyncio.wait_for(session.list_tools(cursor=cursor), timeout=10)
                for tool in page.tools:
                    if tool.name in BUSINESS_ALLOWLIST:
                        if tool.name in remote_tools:
                            raise RuntimeError("MCP 工具名称重复")
                        remote_tools[tool.name] = tool
                cursor = page.nextCursor
                if not cursor:
                    break
            else:
                raise RuntimeError("MCP 工具目录分页超过上限")
            if set(remote_tools) != set(BUSINESS_ALLOWLIST):
                raise RuntimeError("MCP Server 缺少预期工具")
            # 本例只桥接这两个已知工具；不宣称支持任意 MCP Schema 自动转 strict。
            for name, tool in remote_tools.items():
                if set(tool.inputSchema.get("properties", {})) != set(TOOLS[name]["parameters"]["properties"]):
                    raise RuntimeError("MCP Schema 与宿主工具定义不兼容")
            yield MCPBackend(session, remote_tools)
