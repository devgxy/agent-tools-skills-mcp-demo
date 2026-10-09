"""MCP Python SDK 1.30.0 / 旧版协议兼容示例。stdout 仅供协议使用。"""
from pathlib import Path
import argparse
from typing import Any
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from business import FinanceStore, Principal


def build_server(store: FinanceStore):
    server = FastMCP("finance-readonly")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=annotations)
    def query_balance() -> dict[str, Any]:
        """查询本地宿主绑定的用户余额。"""
        return store.query_balance()

    @server.tool(annotations=annotations)
    def find_reimbursements(keyword: str, limit: int) -> dict[str, Any]:
        """查询本地宿主绑定用户的报销记录；limit 1..10。"""
        return store.find_reimbursements(keyword, limit)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    build_server(FinanceStore(args.db, Principal(args.tenant, args.user))).run(transport="stdio")
