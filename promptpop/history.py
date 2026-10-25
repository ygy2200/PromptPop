"""历史记录 + 模板库（SQLite，M3）。"""
import sqlite3
import time

from .config import config_dir


def _conn():
    p = config_dir() / "promptpop.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(p))


def init_db():
    conn = _conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS history("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, mode TEXT, "
            "provider TEXT, model TEXT, input TEXT, output TEXT)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS templates("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, "
            "category TEXT, content TEXT, ts REAL)")
        try:
            conn.execute("ALTER TABLE history ADD COLUMN pinned INTEGER DEFAULT 0")
        except Exception:
            pass  # 列已存在
        try:
            conn.execute("ALTER TABLE history ADD COLUMN tags TEXT DEFAULT ''")
        except Exception:
            pass  # 列已存在
        conn.commit()
    finally:
        conn.close()


def add_history(mode, provider, model, inp, out):
    init_db()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO history(ts,mode,provider,model,input,output) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), mode, provider, model, inp, out))
        conn.commit()
    finally:
        conn.close()


def list_history(limit=200):
    init_db()
    conn = _conn()
    try:
        return conn.execute(
            "SELECT id,ts,mode,provider,model,input,output,tags,pinned FROM history "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()


def add_template(name, category, content):
    init_db()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO templates(name,category,content,ts) VALUES(?,?,?,?)",
            (name, category, content, time.time()))
        conn.commit()
    finally:
        conn.close()


def find_template_by_name(name):
    """按名称找模板，返回其 id；不存在返回 None。

    用于保存前查重：原 add_template 盲目 INSERT，重名会在列表里出现
    重复项且难以分辨。
    """
    init_db()
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM templates WHERE name=? "
                           "ORDER BY id DESC LIMIT 1", (name,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def list_templates():
    init_db()
    conn = _conn()
    try:
        return conn.execute(
            "SELECT id,name,category,content FROM templates ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()


def export_templates():
    """导出全部模板为可序列化列表 [{"name","category","content"}]。"""
    init_db()
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT name,category,content FROM templates ORDER BY id DESC").fetchall()
        return [{"name": r[0], "category": r[1], "content": r[2]} for r in rows]
    finally:
        conn.close()


def import_templates(items, merge=True):
    """从导出结构导入模板。merge=True 时同名模板跳过（不覆盖）；
    merge=False 时先清空再导入。返回 (新增数, 跳过数)。"""
    if not isinstance(items, list):
        return (0, 0)
    init_db()
    conn = _conn()
    try:
        if not merge:
            conn.execute("DELETE FROM templates")
        existing = set()
        if merge:
            existing = {r[0] for r in conn.execute("SELECT name FROM templates").fetchall()}
        added = skipped = 0
        for it in items:
            if not isinstance(it, dict):
                continue                     # 非 dict 条目（如字符串）安全跳过
            name = str(it.get("name", "")).strip()
            if not name:
                continue
            if name in existing:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO templates(name,category,content,ts) VALUES(?,?,?,?)",
                (name, str(it.get("category", "导入")), str(it.get("content", "")),
                 time.time()))
            existing.add(name)
            added += 1
        conn.commit()
        return (added, skipped)
    finally:
        conn.close()


def delete_template(tid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM templates WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()


def update_template(tid, content):
    """更新模板内容（编辑保存，不动名称/分类）。返回是否成功。"""
    conn = _conn()
    try:
        conn.execute("UPDATE templates SET content=?, ts=? WHERE id=?",
                     (content, time.time(), tid))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def delete_history(hid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM history WHERE id=?", (hid,))
        conn.commit()
    finally:
        conn.close()


def clear_history():
    """清空全部历史记录（不可逆）。返回删除的条数。"""
    init_db()
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        conn.execute("DELETE FROM history")
        try:
            # 重置自增计数，避免清空后 id 接着旧值跳
            conn.execute("DELETE FROM sqlite_sequence WHERE name='history'")
        except Exception:
            pass
        conn.commit()
        return n
    finally:
        conn.close()


def set_tags(hid, tags):
    """给某条历史打标签（tags: 可迭代的标签字符串列表）。返回是否成功。"""
    if not isinstance(hid, int):
        try:
            hid = int(hid)
        except Exception:
            return False
    joined = ",".join(str(t).strip() for t in (tags or []) if str(t).strip())
    conn = _conn()
    try:
        conn.execute("UPDATE history SET tags=? WHERE id=?", (joined, hid))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def search_by_tag(tag):
    """按单个标签精确匹配（标签以逗号分隔存储）。返回匹配的历史行。"""
    tag = (tag or "").strip()
    if not tag:
        return []
    init_db()
    conn = _conn()
    try:
        # 用 ','||tags||',' 包裹，保证首尾标签也能精确命中
        return conn.execute(
            "SELECT id,ts,mode,provider,model,input,output,tags FROM history "
            "WHERE (',' || COALESCE(tags,'') || ',') LIKE ? ORDER BY id DESC",
            ("%," + tag + ",%",)).fetchall()
    finally:
        conn.close()


def pin_history(hid, pinned=True):
    conn = _conn()
    try:
        conn.execute("UPDATE history SET pinned=? WHERE id=?",
                     (1 if pinned else 0, hid))
        conn.commit()
    finally:
        conn.close()


def prune_history(retention_days):
    """清理 retention_days 天前的非固定历史，返回删除条数。<=0 不清理。"""
    if not retention_days or retention_days <= 0:
        return 0
    cutoff = time.time() - float(retention_days) * 86400
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM history WHERE ts < ? AND (pinned IS NULL OR pinned=0)",
            (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def export_markdown(rows):
    """rows → Markdown 文本（便于分享/存档）。
    行兼容 8 列（无 pinned）与 9 列（list_history 新版含 pinned）。"""
    from datetime import datetime
    # 内容本身含 ``` 时换用波浪线围栏，避免提前闭合破坏导出结构
    joined = "\n".join((r[5] or "") + (r[6] or "") for r in rows)
    fence = "~~~~" if "```" in joined else "```"
    lines = ["# PromptPop 历史导出", ""]
    for r in rows:
        _id, ts, mode, provider, model, inp, out = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        tags = r[7] if len(r) > 7 else ""
        try:
            dt = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = str(ts)
        head = "## %s · %s · %s · %s" % (dt, mode, provider, model)
        if tags:
            head += "  #" + " #".join(t for t in tags.split(",") if t)
        lines.append(head)
        lines.append("")
        lines.append("**输入：**")
        lines.append("")
        lines.append(fence)
        lines.append((inp or "").strip())
        lines.append(fence)
        lines.append("")
        lines.append("**输出：**")
        lines.append("")
        lines.append(fence)
        lines.append((out or "").strip())
        lines.append(fence)
        lines.append("")
    return "\n".join(lines)
