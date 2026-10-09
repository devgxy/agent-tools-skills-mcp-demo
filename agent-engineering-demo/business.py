"""真实 SQLite I/O；身份由宿主注入，不进入模型可填的工具参数。"""
from dataclasses import dataclass
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str


class FinanceStore:
    def __init__(self, db_path: Path, principal: Principal):
        self.db_path = db_path.resolve()
        self.principal = principal

    @contextmanager
    def _connect(self):
        # mode=ro 防止运行工具时创建或修改数据库；timeout 是锁等待上限。
        conn = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def query_balance(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT amount_cents, currency FROM balances WHERE tenant_id=? AND user_id=?",
                (self.principal.tenant_id, self.principal.user_id),
            ).fetchone()
        if row is None:
            return {"found": False}
        return {"found": True, "amount_decimal": self._amount(row["amount_cents"]),
                "currency": row["currency"]}

    def find_reimbursements(self, keyword: str, limit: int) -> dict:
        # 对直接访问 MCP Server 的调用者也做业务参数校验。
        if not isinstance(keyword, str) or len(keyword) > 100:
            raise ValueError("keyword 必须为最多 100 字的字符串")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit 必须为 1 到 10 的整数")
        # instr 是字面子串查询；不会把 % 或 _ 当成 LIKE 通配符。
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, submitted_at, title, amount_cents, currency, status
                   FROM reimbursements WHERE tenant_id=? AND user_id=?
                   AND (instr(title, ?) > 0 OR instr(id, ?) > 0)
                   ORDER BY submitted_at DESC, id DESC LIMIT ?""",
                (self.principal.tenant_id, self.principal.user_id, keyword, keyword, limit + 1),
            ).fetchall()
        return {"items": [{"id": row["id"], "submitted_at": row["submitted_at"],
                           "title": row["title"], "amount_decimal": self._amount(row["amount_cents"]),
                           "currency": row["currency"], "status": row["status"],
                           "evidence_id": f"reimbursement:{row['id']}"}
                          for row in rows[:limit]], "has_more": len(rows) > limit}

    @staticmethod
    def _amount(cents: int) -> str:
        return format(Decimal(cents) / Decimal(100), ".2f")
