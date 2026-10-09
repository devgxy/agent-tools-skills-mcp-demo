"""创建演示数据；重复运行只添加缺失记录，不清空已有数据。"""
from pathlib import Path
import argparse
import sqlite3


def seed(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS balances (
            tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
            PRIMARY KEY (tenant_id, user_id));
        CREATE TABLE IF NOT EXISTS reimbursements (
            tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, id TEXT NOT NULL,
            submitted_at TEXT NOT NULL, title TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, user_id, id));
        CREATE INDEX IF NOT EXISTS reimbursement_owner_date
            ON reimbursements (tenant_id, user_id, submitted_at DESC);
        """)
        conn.executemany("INSERT OR IGNORE INTO balances VALUES (?, ?, ?, ?)", [
            ("demo-a", "alice", 842050, "CNY"),
            ("demo-a", "bob", 910000, "CNY"),
            ("demo-b", "alice", 12345, "CNY"),
        ])
        conn.executemany("INSERT OR IGNORE INTO reimbursements VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("demo-a", "alice", "RE-9958", "2026-10-01", "办公设备采购", 13000000, "CNY", "待审批"),
            ("demo-a", "alice", "RE-9959", "2026-10-03", "差旅火车票", 56000, "CNY", "已支付"),
            ("demo-a", "bob", "RE-BOB", "2026-10-01", "办公设备采购", 220000, "CNY", "已支付"),
            ("demo-b", "alice", "RE-OTHER", "2026-10-01", "办公设备采购", 330000, "CNY", "已支付"),
        ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path(__file__).parent / "data/demo.sqlite3")
    args = parser.parse_args()
    seed(args.db)
    print(f"演示数据库已就绪：{args.db.resolve()}")
