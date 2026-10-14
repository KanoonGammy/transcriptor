import io
import csv
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query, Response
from app.database import get_db_connection
from app.auth import require_admin

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("")
def list_logs(
    action: Optional[str] = None,
    username: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Retrieve audit activity logs with optional filtering."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        conditions = []
        params = []

        if action and action.strip():
            conditions.append("action LIKE ?")
            params.append(f"%{action.strip()}%")

        if username and username.strip():
            conditions.append("username LIKE ?")
            params.append(f"%{username.strip()}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Total count
        cursor.execute(f"SELECT COUNT(*) FROM activity_logs {where_clause};", tuple(params))
        total_count = cursor.fetchone()[0]

        # Fetch records
        query = f"""
            SELECT id, timestamp, user_id, username, ip_address, action, target, details
            FROM activity_logs {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?;
        """
        cursor.execute(query, tuple(params + [limit, offset]))
        logs = [dict(row) for row in cursor.fetchall()]

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "logs": logs
        }

@router.get("/export")
def export_logs_csv(current_admin: Dict[str, Any] = Depends(require_admin)):
    """Export all activity logs as CSV for auditing."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, user_id, username, ip_address, action, target, details
            FROM activity_logs ORDER BY id DESC;
        """)
        rows = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "User ID", "Username", "IP Address", "Action", "Target", "Details"])
    for r in rows:
        writer.writerow([r["id"], r["timestamp"], r["user_id"], r["username"], r["ip_address"], r["action"], r["target"], r["details"]])

    content = output.getvalue()
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transcriptor_activity_logs.csv"'}
    )
