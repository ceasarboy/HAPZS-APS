"""MPS 排产日期工具（移植自 mps-web schedule.js:19-41 / priority.js:53-75 的 UTC 日期函数）。

micro 差异：invalid 输入返回 None/''（JS 返回 null/''），语义一致。
"""
import math
from datetime import date, datetime, timedelta

DAY = 86400000  # 毫秒常量（对齐 JS；Python 侧仅作文档保留）


def to_date(s):
    """解析 'YYYY-MM-DD...' → date；无效返回 None。

    micro 差异：`to_date("20260102")` 在 Py3.13 被 fromisoformat 接受（JS 正则拒绝）——畸形输入微差。
    """
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def to_str(d) -> str:
    if not d:
        return ""
    return d.isoformat()


def _js_round(x: float) -> int:
    """JS Math.round 语义：半上取整（floor(x+0.5)）。"""
    return math.floor(float(x) + 0.5)


js_round = _js_round  # 公开别名（priority/strategy 复用）


def add_days(s, n) -> str:
    d = to_date(s)
    if not d:
        return ""
    return (d + timedelta(days=_js_round(n))).isoformat()


def diff_days(a, b):
    """b − a（天）；任一无效返回 None。"""
    da, db = to_date(a), to_date(b)
    if not da or not db:
        return None
    return (db - da).days
