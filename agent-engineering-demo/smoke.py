"""无模型、无 API 密钥，真实运行本地函数和 stdio MCP 往返。"""
from pathlib import Path
import asyncio
import json
from business import Principal
from seed import seed
from backends import open_backend


async def main():
    db = Path(__file__).parent / "data/demo.sqlite3"
    seed(db)
    for mode in ("local", "mcp"):
        async with open_backend(mode, db, Principal("demo-a", "alice")) as backend:
            balance = await backend.call("query_balance", {})
            records = await backend.call("find_reimbursements", {"keyword": "办公设备", "limit": 3})
        assert balance["amount_decimal"] == "8420.50"
        assert [row["id"] for row in records["items"]] == ["RE-9958"]
        print(json.dumps({"backend": mode, "balance": balance, "records": records}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
