# 大模型智能体（Agent）工业级架构白皮书

> **导语**：大模型（LLM）本身是无状态的“超级大脑”，而智能体（Agent）工程的本质，就是通过严密的软件架构为这个大脑接上“双手”（行动能力）并赋予“规章”（业务直觉）。本文件由 Agent 架构专家系统梳理，全面打通了从底层物理通信到顶层业务编排的全套知识体系，旨在帮助开发者攻克 Token 爆仓、状态污染、多租户隔离、高并发抗压以及跨平台集成的核心痛点。

---

## 目录
1. [大模型 Tools（工具调用）的核心原理](#1-大模型-tools工具调用的核心原理)
2. [多轮对话历史记录的运行时裁剪与持久化分离](#2-多轮对话历史记录的运行时裁剪与持久化分离)
3. [长记忆反查与历史 RAG（应急工具设计）](#3-长记忆反查与历史-rag应急工具设计)
4. [声明式 Skill（技能包）与 Tools 前置筛选](#4-声明式-skill技能包与-tools-前置筛选)
5. [MCP（模型上下文协议）的分层价值与物理透视](#5-mcp模型上下文协议的分层价值与物理透视)
6. [状态管理深水区：无状态 Tool 与有状态 MCP Server](#6-状态管理深水区无状态-tool-与有状态-mcp-server)
7. [高并发抗压设计：中央数据库的破局之道](#7-高并发抗压设计中央数据库的破局之道)
8. [工业级 Agent 终极版图：高内聚组件拼图](#8-工业级-agent-终极版图高内聚组件拼图)
9. [不依赖第三方框架的工业级纯 Python 闭环骨架源码](#9-不依赖第三方框架的工业级纯-python-闭环骨架源码)

---

## 1. 大模型 Tools（工具调用）的核心原理

### 1.1 原生支持（Native Tool-Use） vs 提示词模拟
* **原生支持（API参数）**：现代大模型（如 GPT-4o, Claude 3.5, DeepSeek-V3 等）在底层经过了特殊的监督微调（SFT）和强化学习（RLHF）。开发者在发起 API 请求时，通过一个独立的、显式的 `tools` 参数（通常符合 JSON Schema 规范）将工具定义发送给大模型。模型一旦判断需要使用工具，会直接触发一个特殊的停止信号（Finish Reason = `tool_calls`），并精准输出符合格式的 JSON 字符串参数。
* **System Prompt 提示词模拟**：在早期模型或小尺寸开源模型不支持 `tools` 参数时，开发者被迫在系统提示词中用大白话或强行规定特定标签（如“请严格按照 `<call>函数名(参数)</call>` 的格式输出”）来教模型使用工具。这种方式完全依赖模型的泛化和文本跟从能力，极其不稳定，极易发生格式错乱、幻觉和解析失败。

### 1.2 为什么必须在 API 参数中独立设置 Tools
1. **结构化边界清晰**：避免工具描述与用户的聊天文本发生语义混淆，模型底层有专属的注意力机制（Attention）去解析 JSON Schema。
2. **强制契约控制**：平台层可以通过参数（如 `tool_choice="required"`）强制控制模型是否必须调用工具，这是纯提示词很难稳定控制的。
3. **性能优化**：服务商可以在工程上对工具参数进行缓存和预解析（Prompt Caching），从而极大地降低首字延迟（TTFT）。

---

## 2. 多轮对话历史记录的运行时裁剪与持久化分离

大模型本身是**无状态的（Stateless）**。每一次对话，模型都不会记住上一次的上下文，必须由后端代码将历史记录以 `messages` 数组的形式全量发送。当引入 Tools 后，消息的角色演化得更加复杂：

### 2.1 包含 Tools 的标准多轮对话演进状态
1. **HumanMessage**：人类用户的提问。
2. **AIMessage（含 tool_calls）**：大模型做出的推理决策，表明自己不直接回答文本，而是**申请调用工具**，带有专属的 `id`、函数名和参数。
3. **ToolMessage**：后端代码拦截到上面的 `tool_calls` 后，去物理世界执行真实的 Python 函数或 API 接口，然后**必须带着对应的 `tool_call_id`** 将真实数据结果喂回给模型。
4. **AIMessage（最终文本）**：大模型结合 `ToolMessage` 里的真实数据，重新组织语言输出给人类的最终自然语言回答。

### 2.2 核心工程分离：持久化存储 vs 运行时裁剪
在企业级架构中，必须将**底层的“完整存储”**与**应用层的“视窗裁剪”**彻底解耦：
* **面向数据库（持久化存储与完整读取）**：每一次的 `HumanMessage`, `AIMessage`（包含其内部的工具调用意图）以及庞大、凌乱的 `ToolMessage`（如数据库返回的几百行原始 JSON）必须**一字不差地原封不动写入底层数据库**（如 PostgreSQL, MongoDB 或 Redis）。因为用户查阅历史、系统 Debug 审计、后续的模型微调（Fine-tuning）必须依赖绝对完整的数据资产。
* **面向模型 API（运行时视窗裁剪与压缩）**：在单次调用核心模型时，由于上下文窗口限制和 Token 计费，不能把几万字的历史明细全拍在模型脸上。后端代码必须利用专门的裁剪器（如 LangChain 最新的 `trim_messages`）进行动态截断（通常是基于 Token 计数的滑动窗口）。

> **🌟 避坑雷区（断链报错）**：如果在进行运行时裁剪时，生硬地切断了历史消息，导致一条 `ToolMessage` 保留了，但发起它的 `AIMessage(tool_calls)` 因为太旧被删掉了，大模型 API 会直接报 **400 物理调用链不完整** 错误。因此，裁剪器必须支持诸如 `allow_partial=False` 的机制，确保一整套工具调用链要么一起保留，要么一起从运行时上下文里抹除。

---

## 3. 长记忆反查与历史 RAG（应急工具设计）

### 3.1 语义压缩带来的“细节丢失”痛点
为了追求低成本，业界常用大模型在后台异步将老旧的消息明细压缩为一小段文字（如：将前天发的一大堆详细采购清单压缩为“*用户于前天发起了一笔约 10 万元的办公设备采购申请*”），并作为 `summary` 常驻系统提示词。
然而，如果接下来的对话中，用户突然追问：“*我前天采购单里第 3 项商品的具体型号和数量是什么？*”，大模型看着眼前的“摘要”，由于缺失细节，必然发生严重的认知断层和幻觉。

### 3.2 两阶段记忆检索机制（History RAG 闭环）
为了解决上述痛点，必须设计一种**应急反查工具**。整个闭环链路运转如下：

```
[ 1. 用户提问远期细节 ] ──> [ 2. AI 翻阅当前请求上下文 ] ──> 发现只有摘要，丢失明细
                                                                  │
[ 5. AI 获得精练原文，精准作答 ] <── [ 4. 工具内部执行局部 RAG / 切片过滤 ] <── [ 3. AI 主动触发历史反查 Tool ]
```

1. **工具定义**：定义一个特殊的 Tool，例如 `fetch_archived_chat_details(query_keyword)`。并在工具的描述（Description）里严厉警告模型：“*只有当你确定当前的上下文摘要丢失了细节，且用户明确在追问过去的具体内容时才调用！严禁在日常闲聊中频繁调用！*”
2. **工具内部逻辑**：大模型触发该工具后，后端代码拿到用户的 `session_id`，去底层的完整历史数据库中把当年那场庞大的原始对话捞出来。
3. **防暴防护（局部 RAG）**：如果捞出来的历史原文很大，**绝对不能**原封不动直接扔回给 Tool 响应，否则单次 Token 还是会爆。必须在工具内部进行**文本语义切片（Chunking）与局部向量匹配（Vector Search）**，只挑选匹配度最高的 Top 3 精准片段，作为 `ToolMessage` 的内容返回给模型。
4. **高精度作答**：大模型在下一轮的 `ToolMessage` 里看清了当年的细节，给用户做出确定、完美的历史考古级回复。

---

## 4. 声明式 Skill（技能包）与 Tools 前置筛选

### 4.1 为什么要进行 Tools 的前置筛选（斩断 Token 爆炸）
在大型企业 Agent 系统中，可能会有成百上千个 Tools（查天气、查股票、提请假、改密码、删服务器等）。如果你盲目地使用 `llm.bind_tools(所有工具)`，**每一次对话**，系统都必须把这几百个工具的 JSON Schema 说明书无条件全部塞进大模型 API 的请求体里。
这不仅会导致 **Token 基础开销出现灾难性暴涨（每聊一句都要为几万 Token 废话说明书买单）**，更致命的是摆在模型面前的干扰项太多，**模型的幻觉率和调错工具的概率会呈线性上升**。

### 4.2 什么是声明式 Skill
为了破局，业界引入了 **Skill（技能包 / 配置式技能）** 流派。它通常表现为一个独立的 **Markdown（.md）格式文件**。它不仅定义了工具，还绑定了业务的 SOP、语气规范和小样本示例。

```markdown
# 技能: 财务专家技能包 (finance_skill.md)
## 描述: 处理用户关于预算、报销、薪资、账户余额的提问。
## 工具声明: [query_user_balance, run_reimbursement_flow]
## 业务 SOP:
1. 给出任何金额时，必须加上 ¥ 符号并保留两位小数。
2. 涉及审批时，必须主动提供人工客服热线。
```

### 4.3 运行时前置筛选的 3 种工程手段
系统在调用核心大模型之前，先通过一层极其轻量级的“看门人”逻辑，从 100 个 `.md` 技能文件中精准挑出最相关的 1 个，**动态解析并只把这 1 个技能包含的 2 个工具通过 `bind_tools` 挂载给大模型**。

1. **向量相似度检索（Embedding + Vector DB，最推荐）**：系统启动时，把所有 MD 文件的 `## 描述` 段落存入向量数据库。用户提问进来，先用几毫秒对问题做向量检索，精准命中相关技能。**完美解决模糊语义（如用户说“钱包空了”，能自动匹配到财务技能）**。
2. **轻量级意图分类模型（Intent Router）**：用一个极速、极便宜的小模型（如 `gpt-4o-mini`）充当前台分流员，看着技能菜单对用户问题做纯文本分类，输出技能 ID。
3. **规则与关键词矩阵（Regex / Tokenizer）**：针对技能少的冷启动业务，在代码层硬编码关键词（如 `["钱", "发票", "报销"]` 触发财务）。成本为零，速度最快，但缺乏泛化能力。

---

## 5. MCP（模型上下文协议）的分层价值与物理透视

### 5.1 什么是 MCP（Model Context Protocol）
MCP 是由 Anthropic 推出并迅速成为开放工业标准的跨平台协议。它彻底解决了智能体工程中**接口碎片化、重复制置连接器**的痛苦。

### 5.2 Tool、MCP 与 Skill 的分层金字塔关系
它们三者绝不是竞争替代关系，而是自上而下的完美咬合协同：

```
  ┌────────────────────────┐
  │     1. SKILL (指挥层)   │ ──> 负责看管业务 SOP 规章与提示词边界，指挥何时干什么。
  └───────────┬────────────┘
  ┌───────────▼────────────┐
  │     2. MCP (互联层)     │ ──> 负责定义统一的连接协议网关，让大模型通过标准接口连通世界。
  └───────────┬────────────┘
  ┌───────────▼────────────┐
  │     3. TOOL (原子层)    │ ──> 负责具体动作落地执行。由 MCP Server 自动映射成模型看得懂的 Schema。
  └────────────────────────┘
```

* **传统 Tools 的痛苦**：你想连接 GitHub、Slack、Notion 和 PostgreSQL 数据库，你需要自己手写 4 坨完全不同的 Python SDK 请求和参数组装代码，一旦第三方 API 升级，代码直接崩溃。
* **MCP 带来的变革**：MCP 将架构抽象为了 **MCP Client（你的 Agent 外壳）** 和 **MCP Server（外部系统的独立代理进程）**。大模型和任何外部系统的对话，统一说基于 **JSON-RPC 2.0 规范的 MCP 普通话**。你只需要去社区 Registry（注册表）里即插即用拉起现成的 `GitHub MCP Server` 或 `Postgres MCP Server`，它暴露出的所有能力会自动被大模型感知并转化为可调用的 Tools。

### 5.3 MCP Server 的物理存在形式
在操作系统内核层面，MCP Server 是一个**独立运行的、长期驻留的后端进程**。
* **本地 Stdio 模式**：通过操作系统的**管道（Pipe）/ Unix Domain Socket** 进行本机的免网络、纯内存拷贝式的高速进程间通信。Client 进程向 Server 的标准输入（Stdin）写 JSON-RPC 指令，Server 异步从标准输出（Stdout）返回结果。
* **云端 SSE 模式**：MCP Server 作为一个轻量级的高性能 Web 服务器，在特定端口挂起。它通过标准的 **TCP 网络 Socket 长连接（Server-Sent Events 协议）** 监听来自远程多台 Agent 的并发调用请求，并利用专属的 `Session ID` 维持多租户会话。

---

## 6. 状态管理深水区：无状态 Tool 与有状态 MCP Server

### 6.1 传统 Tools 为什么被设计为“无状态的纯函数”
在软件工程设计中，传统的 Tools 被刻意设计为**无状态（Stateless）**。大模型调用工具时只传参数，不传类对象的指针。
* **原因**：这顺应了大模型自身无状态的特征，更顺应了分布式容器集群（如 K8s）横向弹性扩容的需要。用户的请求可以随机被分流到任何一台服务器节点上运行工具，工具自身绝不利用**类字段（Class Fields）**保存全局变量。如果需要状态，工具函数必须外置状态——每次执行都通过显式传入的 `session_id` 去统一的 Redis 存储里“现捞现写”（Stateless I/O）。

### 6.2 MCP Server 为什么能保存“类字段状态状态变量”
随着 Agent 向本地桌面操作和边缘高频交互演进，“无状态”带来了高频网络 I/O 导致的严重延迟。
* **MCP 的状态接管**：MCP Server 作为一个独立的常驻进程，天生支持**会话保持（Stateful）**。当多台 Agent 连上同一个 MCP Server 时，协议层（Client-Server长连接）会自动分配并管理 `Session` 实例。
* **多租户对象隔离机制**：MCP Server 进程内部可以安全地声明类字段。它在常驻内存中维护一个映射字典：`self.active_sessions: Dict[str, UserContextObject]`。当某条 Socket 管道传来 Tool 调用时，Server 内部的网关会**先根据 SessionID 锁定对应的那个用户的私有实例对象**，再在该对象内部读写类字段。这就完美实现了**“长留存、高性能内存状态保存”与“多租户并发绝对安全隔离”**的结合。

---

## 7. High-Concurrency: 中央数据库的破局之道

当系统面临高并发（千万级用户连击提问）时，“状态外置”架构下让 Tools 和 Agent 强刷统一的中央分布式数据库/Redis，会导致写 I/O 暴涨、网络句柄耗尽而全面崩溃。工业界采用以下组合拳硬抗压力：

### 7.1 核心抗压架构策略
1. **本地内存 + 异步批量刷盘（Write-Back 策略）**：Tool 产生的所有状态变更和长对话历史记录，第一步**只写入当前应用进程的本地极速内存缓冲区（L1 Cache）**。后台启动一个独立的异步 Worker 线程或通过消息队列（MQ），将数据“攒一波”，每隔 5 秒钟将多条记录合并，**批量（Batch）一次性写入**中央 Redis/数据库。
2. **多级缓存架构（L1 进程内存 / L2 集中式 Redis / L3 数据库）**：利用局部性原理，由于同一个用户通常在几分钟内连续打字，其状态在 L1 本地内存里有极高的命中率，90% 的连续对话请求在应用层内部被自我消化，中央 Redis 只有在会话开启和结束时才会被访问。
3. **分布式水平分片（Sharding Cluster）**：对中央 Redis 部署集群模式，根据用户的 `session_id` 进行哈希（Hash）计算，把海量的用户数据均匀打散到不同的物理 Redis 实例中，消除单点物理瓶颈。

---

## 8. 工业级 Agent 终极版图：高内聚组件拼图

在企业级商业落地中，一个高可用、可进化的 Agent 平台，除了 Tools、MCP 和 Skill，还必须把以下模块有机地捆绑在同一个“黑匣子技能包”中交付：

1. **记忆与局部知识库（Memory & Local RAG）**：包含用户的长效标签画像（Persona）与该技能专属的产品手册、条文法规。
2. **安全合规防护盾（Guardrails & RBAC Security）**：前置拦截恶意用户的 **Prompt 注入攻击**，后置对 Tool 吐出的敏感私钥、身份证等 PII 数据进行自动**脱敏擦除**，并在执行前强制校验当前用户 Session 凭证的真实**操作权限（鉴权）**。
3. **小样本示例库（Few-Shots Registry）**：存放 3~5 组极高质量的“思考 -> 工具调用 -> 结果组装”的真实规范 JSON 范例，在 Skill 被激活时动态合并进上下文，彻底驯化大模型、终结幻觉。
4. **日志追踪与自动化评测（Observability & Eval）**：通过树状图可视化记录每一次工具调用的耗时与因果锁链（LLM Trace），并在系统发布前运行自动化回归测试集，确保修改 Skill 描述后工具调用准确率不会滑坡。

---

## 9. 不依赖第三方框架的工业级纯 Python 闭环骨架源码

以下代码是一个纯 Python 编写的**动态 Skill 筛选、Token 运行时裁剪、原子 Tool 动态绑定与多轮工具状态流转**的企业级全套骨架。你可以直接将其贴入项目或作为架构选型的参考：

```python
import os
import re
from typing import List, Dict, Any, Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, trim_messages

# ==========================================
# [组件一] 原子工具库：纯函数，无内部状态类字段
# ==========================================
def query_user_balance(user_id: str) -> str:
    """原子工具：去极速 Redis 缓存查当前用户的实时余额"""
    return f"【API 响应】用户 {user_id} 当前可用余额为：¥8,420.50 元。"

def fetch_archived_logs(keyword: str) -> str:
    """高阶考古工具：去底层大容量归档库反查长历史明细（历史 RAG 内部封装）"""
    return f"【API 响应】找到归档明细：2026-10-01 该用户曾提交过一笔办公设备报销申请，单号为 RE-9958，金额 ¥130,000.00。"

# 全局工具路由映射表
AVAILABLE_TOOLS_MAP = {
    "query_user_balance": query_user_balance,
    "fetch_archived_logs": fetch_archived_logs
}

# ==========================================
# [组件二] 声明式配置化技能库 (Markdown 规范)
# ==========================================
MOCK_SKILLS_DIRECTORY = {
    "finance_skill": """
# 技能: 财务资产管理小助手
## 描述: 当用户询问自己的钱包、钱、余额、资产、报销进度时激活本技能。
## 工具声明: [query_user_balance]
## 业务 SOP:
1. 回复金额时必须严谨，无条件加上人民币符号(¥)并保留两位小数。
2. 给出结果后，必须礼貌地询问是否需要导出为财务电子对账单。
""",
    "archive_skill": """
# 技能: 远期历史档案考古学家
## 描述: 当用户追问很早以前的聊天死角、很久之前的合同细节或过去提供的采购清单明细时激活。
## 工具声明: [fetch_archived_logs]
## 业务 SOP:
1. 先真诚安抚用户，明确告知正在调取底层冷存储归档库，可能需要 1-2 秒。
2. 必须以严格的 Markdown 列表形式展示反查出来的历史文本明细。
"""
}

# ==========================================
# [组件三] 运行时动态 Skill 前置筛选器
# ==========================================
class RuntimeSkillRouter:
    @staticmethod
    def route_and_compile(user_input: str) -> Dict[str, Any]:
        """
        前置分流核心：在惊动大模型之前，通过规则/向量动态锁定唯一技能，完成 Tools 的前置筛选
        """
        selected_md_content = None
        
        # 工业界冷启动推荐：关键词矩阵精准阻断（后续可一键升级为向量数据库 similarity_search）
        if any(keyword in user_input for keyword in ["钱", "余额", "报销", "资产"]):
            selected_md_content = MOCK_SKILLS_DIRECTORY["finance_skill"]
        elif any(keyword in user_input for keyword in ["过去", "历史", "很久之前", "前天", "清单"]):
            selected_md_content = MOCK_SKILLS_DIRECTORY["archive_skill"]
            
        if not selected_md_content:
            # 无特定技能命中，返回白纸底座
            return {"system_extension": "", "active_tools_list": []}
            
        # 正则解析选中的 MD 文件，动态提取被 Skill 锁定的原子工具名
        extracted_tool_names = re.findall(r"\[(.*?)\]", selected_md_content)
        active_tools_list = [
            AVAILABLE_TOOLS_MAP[name] for name in extracted_tool_names if name in AVAILABLE_TOOLS_MAP
        ]
        
        return {
            "system_extension": f"\n\n【当前已激活专属技能规范与 SOP，请严格执行】:\n{selected_md_content}",
            "active_tools_list": active_tools_list
        }

# ==========================================
# [组件四] Agent 运行时上下文调度内核
# ==========================================
class IndustrialAgentRuntime:
    def __init__(self, model_name: str = "gpt-4o"):
        self.llm = ChatOpenAI(model=model_name, temperature=0)

    def execute_chat_turn(self, user_id: str, user_input: str, chat_history: List[AnyMessage]) -> str:
        """
        单轮多步工具流转核心方法
        """
        # 1. 将用户本轮新提问压入历史记录
        chat_history.append(HumanMessage(content=user_input))
        
        # 2. 🌟 执行前置 Skill 筛选器：斩断 Token 暴涨，锁死工具边界
        matching_package = RuntimeSkillRouter.route_and_compile(user_input)
        
        # 3. 动态组装融入了 MD SOP 约束的全新系统提示词
        base_system_prompt = "你是一个高专业度、通过统一协议驱动的企业级核心 AI 助理。"
        final_system_content = base_system_prompt + matching_package["system_extension"]
        
        # 4. 构建当前网络请求的消息队列（剔除旧的 system 消息，将最新的注入在头部）
        clean_messages = [SystemMessage(content=final_system_content)] + [
            msg for msg in chat_history if not isinstance(msg, SystemMessage)
        ]
        
        # 5. 🌟 运行时 Token 精准裁剪：保护系统不爆窗口，且 allow_partial=False 守住工具链完整性
        trimmer = trim_messages(
            max_tokens=2000, 
            strategy="last", 
            token_counter=self.llm, 
            include_system=True,
            allow_partial=False
        )
        pruned_messages = trimmer.invoke(clean_messages)
        
        # 6. 🌟 动态工具绑定：只把被选中的专属工具递给大模型说明书
        if matching_package["active_tools_list"]:
            runnable_llm = self.llm.bind_tools(matching_package["active_tools_list"])
        else:
            runnable_llm = self.llm
            
        # 7. 发起第一轮大模型推理
        response = runnable_llm.invoke(pruned_messages)
        
        # 8. 🌟 判定模型是否提出了结构化工具调用申请 (Tool Calling 流转)
        if response.tool_calls:
            target_call = response.tool_calls[0]
            print(f"-> 🎯 [模型决策成功] 经由 Skill 筛选过滤，AI 决定触发原子工具: {target_call['name']}")
            
            # 动态检索并物理执行对应的本地 Python 函数
            executor_func = AVAILABLE_TOOLS_MAP[target_call['name']]
            # 运行时动态注入多租户隔离上下文（如用户 ID），防止状态交叉污染
            actual_args = target_call['args']
            if 'user_id' in executor_func.__code__.co_varnames:
                actual_args['user_id'] = user_id
                
            tool_output_string = executor_func(**actual_args)
            
            # 将模型的调用意图和最终的工具执行结果，作为自洽的调用链追加进数据库历史中
            chat_history.append(response)
            chat_history.append(
                ToolMessage(content=tool_output_string, tool_call_id=target_call['id'])
            )
            
            # 带着所有的历史数据与新鲜的工具结果，经过裁剪后，发起第二轮终极大模型请求
            final_pruned = trimmer.invoke([SystemMessage(content=final_system_content)] + chat_history)
            final_response = self.llm.invoke(final_pruned)
            return final_response.content
            
        # 若无需调用工具，直接返回普通自然语言
        return response.content

# ==========================================
# [组件五] 生产现场模拟跑通
# ==========================================
if __name__ == "__main__":
    # 模拟属于某个特定用户的、持久化在后端数据库里的完整多轮对话历史数组
    db_user_message_history = []
    runtime_engine = IndustrialAgentRuntime()
    
    print("⚡ [第一轮对话流转开始] 用户提问财务敏感数据...")
    answer_1 = runtime_engine.execute_chat_turn(
        user_id="user_9958", 
        user_input="帮我看一下我的账户上还剩多少钱？", 
        chat_history=db_user_message_history
    )
    print(f"🤖 [AI 最终回复]:\n{answer_1}\n")
    
    print("⚡ [第二轮对话流转开始] 用户开启考古模式（触发长历史反查 RAG）...")
    answer_2 = runtime_engine.execute_chat_turn(
        user_id="user_9958", 
        user_input="我想查一下我很久之前提交过的那笔办公设备报销单号是多少？", 
        chat_history=db_user_message_history
    )
    print(f"🤖 [AI 最终回复]:\n{answer_2}")
```

---
*本白皮书由大模型智能体专家组编写，版权属于全体开源社区建设者。在 AI 浪潮向通用人工智能（AGI）演进的深水区，愿以此文助诸位开发者驭繁为简，成功落地具备商业价值的智能体巨系统。*
