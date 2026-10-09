from pathlib import Path
import argparse
import asyncio
import logging
import os
from openai import AsyncOpenAI
from business import Principal
from backends import open_backend
from runtime import run_agent


async def main(args):
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("请在本地设置 OPENAI_API_KEY；离线验证不需要密钥，见 README。")
    if not args.model:
        raise SystemExit("请设置 OPENAI_MODEL 或传入 --model，选择账号可用且支持 Responses 工具调用的模型。")
    principal = Principal(args.tenant, args.user)
    # CLI 的 tenant/user 仅供演示。Web 服务必须从已验证登录会话获得身份。
    async with AsyncOpenAI(timeout=45, max_retries=2) as client:
        async with open_backend(args.backend, args.db, principal) as backend:
            answer = await run_agent(client, backend, args.model, args.question)
    print(answer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--backend", choices=["local", "mcp"], default="local")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--db", type=Path, default=Path(__file__).parent / "data/demo.sqlite3")
    parser.add_argument("--tenant", default="demo-a")
    parser.add_argument("--user", default="alice")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main(args))
