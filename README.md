# Tools / Skills / MCP 工程实践示例

同一套 Python 业务函数分别通过本地调用和真实 MCP stdio 服务执行，并使用 Responses API 演示有边界的工具调用循环。

- [可运行 demo 与函数调用流程图](agent-engineering-demo/README.md)
- [工程实践指南](tools-skills-mcp工程实践指南.md)
- [原始学习笔记](agent_architecture_guide.md)：保留原文；技术修正和验证以工程实践指南为准。
- [交互式调用过程 HTML](agent-flow.html)
- [在线交互演示](https://agent-tool-flow.airyspark2.chatgpt.site)
- [静态架构图](agent-architecture.svg)

## 本地运行

```bash
cd agent-engineering-demo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python smoke.py
python -m pytest -q
```

离线验证包含实际 SQLite 查询、MCP 子进程通信和模型响应夹具。已通过 18 项测试；真实模型与 API 密钥尚未联调，详细记录见 [VERIFICATION.md](agent-engineering-demo/VERIFICATION.md)。

数据库记录均为演示数据。运行环境、数据库、缓存与密钥不在仓库中；真实 API Key 仅从环境变量读取。
