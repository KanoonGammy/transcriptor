from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.database import get_db_connection, log_activity
from app.auth import require_admin, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=6)
    role: str = Field(default="user") # 'admin' or 'user'

class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

@router.get("")
def list_users(current_admin: Dict[str, Any] = Depends(require_admin)):
    """List all registered users in the system."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, full_name, role, is_active, created_at, last_login_at
            FROM users ORDER BY id ASC;
        """)
        users = [dict(row) for row in cursor.fetchall()]
        return {"users": users}

@router.post("")
def create_user(
    req: CreateUserRequest,
    request: Request,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Admin creates a new user account."""
    clean_username = req.username.strip().lower()
    if not clean_username.isalnum() and "_" not in clean_username and "-" not in clean_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ชื่อผู้ใช้ต้องเป็นตัวอักษรภาษาอังกฤษ ตัวเลข หรือขีดล่างเท่านั้น"
        )

    if req.role not in ("admin", "user"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="บทบาท (Role) ต้องเป็น 'admin' หรือ 'user' เท่านั้น"
        )

    client_ip = request.client.host if request.client else "unknown"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?;", (clean_username,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ชื่อผู้ใช้ '{clean_username}' มีอยู่ในระบบแล้ว"
            )

        hashed = hash_password(req.password)
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?);
        """, (clean_username, hashed, req.full_name.strip(), req.role, now_iso))
        new_id = cursor.lastrowid
        conn.commit()

        log_activity(
            action="CREATE_USER",
            user_id=current_admin["id"],
            username=current_admin["username"],
            ip_address=client_ip,
            target=f"users/{new_id}",
            details=f"Admin created user '{clean_username}' with role '{req.role}'"
        )

        return {
            "message": f"สร้างผู้ใช้งาน '{clean_username}' สำเร็จ",
            "user": {
                "id": new_id,
                "username": clean_username,
                "full_name": req.full_name.strip(),
                "role": req.role
            }
        }

@router.put("/{user_id}")
def update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Admin updates existing user attributes or resets password."""
    client_ip = request.client.host if request.client else "unknown"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, is_active FROM users WHERE id = ?;", (user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Guard: Cannot deactivate or demote own admin account
        if target_user["id"] == current_admin["id"]:
            if req.is_active is False:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่สามารถปิดการใช้งานบัญชีตนเองได้")
            if req.role and req.role != "admin":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่สามารถลดระดับสิทธิ์ของตนเองได้")

        updates = []
        params = []

        if req.full_name is not None and req.full_name.strip():
            updates.append("full_name = ?")
            params.append(req.full_name.strip())

        if req.role is not None:
            if req.role not in ("admin", "user"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
            updates.append("role = ?")
            params.append(req.role)

        if req.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if req.is_active else 0)

        if req.password is not None and req.password.strip():
            if len(req.password.strip()) < 6:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 6 chars")
            updates.append("password_hash = ?")
            params.append(hash_password(req.password.strip()))

        if updates:
            params.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?;"
            cursor.execute(query, tuple(params))
            conn.commit()

            log_activity(
                action="UPDATE_USER",
                user_id=current_admin["id"],
                username=current_admin["username"],
                ip_address=client_ip,
                target=f"users/{user_id}",
                details=f"Updated user fields: {updates}"
            )

        return {"message": "อัปเดตข้อมูลผู้ใช้งานเรียบร้อยแล้ว"}

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Admin deletes user account."""
    if user_id == current_admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่สามารถลบบัญชีผู้ดูแลระบบที่กำลังใช้งานอยู่ได้"
        )

    client_ip = request.client.host if request.client else "unknown"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = ?;", (user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # If deleting an admin, ensure at least one other active admin remains
        if target_user["role"] == "admin":
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?;", (user_id,))
            remaining_admins = cursor.fetchone()[0]
            if remaining_admins == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ไม่สามารถลบได้ เนื่องจากต้องมีผู้ดูแลระบบ (Admin) อย่างน้อย 1 คนในระบบ"
                )

        cursor.execute("DELETE FROM users WHERE id = ?;", (user_id,))
        conn.commit()

        log_activity(
            action="DELETE_USER",
            user_id=current_admin["id"],
            username=current_admin["username"],
            ip_address=client_ip,
            target=f"users/{user_id}",
            details=f"Admin deleted user '{target_user['username']}'"
        )

        return {"message": f"ลบผู้ใช้งาน '{target_user['username']}' เรียบร้อยแล้ว"}
