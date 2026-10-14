from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.database import get_db_connection, log_activity
from app.auth import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    """Authenticate user, set cookie and return token."""
    username = req.username.strip()
    client_ip = request.client.host if request.client else "unknown"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, password_hash, full_name, role, is_active 
            FROM users WHERE username = ?;
        """, (username,))
        user = cursor.fetchone()

        if not user or not verify_password(req.password, user["password_hash"]):
            log_activity(
                action="LOGIN_FAILED",
                username=username,
                ip_address=client_ip,
                target="auth",
                details="Invalid username or password attempt"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง (Invalid username or password)"
            )

        if not user["is_active"]:
            log_activity(
                action="LOGIN_BLOCKED",
                user_id=user["id"],
                username=username,
                ip_address=client_ip,
                target="auth",
                details="Attempted login on deactivated account"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="บัญชีนี้ถูกปิดการใช้งาน กรุณาติดต่อผู้ดูแลระบบ (Account deactivated)"
            )

        # Update last login
        now_iso = datetime.now().isoformat()
        cursor.execute("UPDATE users SET last_login_at = ? WHERE id = ?;", (now_iso, user["id"]))
        conn.commit()

        token = create_access_token({
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "full_name": user["full_name"]
        })

        # Set HTTP-only cookie for seamless browser downloads and streaming
        response.set_cookie(
            key="transcriptor_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=72 * 3600
        )

        log_activity(
            action="LOGIN",
            user_id=user["id"],
            username=user["username"],
            ip_address=client_ip,
            target="auth",
            details="User logged in successfully"
        )

        return {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "full_name": user["full_name"],
                "role": user["role"]
            }
        }

@router.post("/logout")
def logout(request: Request, response: Response, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Clear session cookie and log logout."""
    response.delete_cookie("transcriptor_token")
    client_ip = request.client.host if request.client else "unknown"
    log_activity(
        action="LOGOUT",
        user_id=current_user["id"],
        username=current_user["username"],
        ip_address=client_ip,
        target="auth",
        details="User logged out"
    )
    return {"message": "Logged out successfully"}

@router.get("/me")
def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Return currently authenticated user."""
    return {"user": current_user}

@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Allow logged in user to update their password."""
    client_ip = request.client.host if request.client else "unknown"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = ?;", (current_user["id"],))
        row = cursor.fetchone()
        if not row or not verify_password(req.current_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสผ่านปัจจุบันไม่ถูกต้อง (Current password incorrect)"
            )

        new_hash = hash_password(req.new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?;", (new_hash, current_user["id"]))
        conn.commit()

        log_activity(
            action="PASSWORD_CHANGE",
            user_id=current_user["id"],
            username=current_user["username"],
            ip_address=client_ip,
            target="users",
            details="User updated own password"
        )

        return {"message": "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว (Password updated)"}
