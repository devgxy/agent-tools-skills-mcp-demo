"""工具定义、渐进式 Skill 读取、宿主侧能力策略。"""
from pathlib import Path
import json
import yaml
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent
SKILL_PATH = ROOT / "skills/finance-readonly/SKILL.md"
# 这是本应用的能力配置，不是 Agent Skills 标准字段。
SKILL_TOOLS = {"finance-readonly": frozenset({"query_balance", "find_reimbursements"})}
BUSINESS_ALLOWLIST = frozenset({"query_balance", "find_reimbursements"})


def function_tool(name, description, properties):
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False},
            "strict": True}


TOOLS = {
    "load_skill": function_tool("load_skill", "读取已知技能的完整操作规范，然后再调用业务工具。", {
        "name": {"type": "string", "enum": ["finance-readonly"]}}),
    "query_balance": function_tool("query_balance", "查询当前已认证用户的账户余额，只读。", {}),
    "find_reimbursements": function_tool("find_reimbursements", "按标题或单号的字面子串查本人历史报销，最多10条；空关键词表示全部。", {
        "keyword": {"type": "string"}, "limit": {"type": "integer"}}),
}


def skill_metadata() -> dict:
    # 启动时只读取 YAML 元数据，不把完整正文放进模型上下文。
    with SKILL_PATH.open(encoding="utf-8") as source:
        if source.readline().strip() != "---":
            raise ValueError("缺少技能元数据")
        lines = []
        for line in source:
            if line.strip() == "---":
                break
            lines.append(line)
        else:
            raise ValueError("技能元数据未闭合")
    meta = yaml.safe_load("".join(lines))
    return {"name": meta["name"], "description": meta["description"]}


class ToolFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CapabilityPolicy:
    def __init__(self):
        self.active: set[str] = set()

    def offered(self) -> dict:
        permitted = {"load_skill"}
        for skill in self.active:
            permitted.update(SKILL_TOOLS[skill] & BUSINESS_ALLOWLIST)
        return {name: TOOLS[name] for name in sorted(permitted)}

    def parse(self, name: str, arguments: str, offered: dict) -> dict:
        # 使用当前模型请求的工具快照，不能在同一响应中先激活再偷跑未暴露工具。
        if name not in offered:
            raise ToolFailure("tool_not_allowed")
        try:
            args = json.loads(arguments)
            Draft202012Validator(offered[name]["parameters"]).validate(args)
        except (json.JSONDecodeError, ValidationError, TypeError):
            raise ToolFailure("invalid_arguments") from None
        if name == "find_reimbursements":
            if len(args["keyword"]) > 100 or type(args["limit"]) is not int or not 1 <= args["limit"] <= 10:
                raise ToolFailure("invalid_arguments")
        return args

    def load(self, name: str) -> dict:
        if name not in SKILL_TOOLS:
            raise ToolFailure("unknown_skill")
        instructions = SKILL_PATH.read_text(encoding="utf-8")
        self.active.add(name)
        return {"skill": name, "instructions": instructions}
