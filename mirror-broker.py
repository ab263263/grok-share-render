#!/usr/bin/env python3
"""Mirror broker for grok-share-render.

Provides a tiny local control plane that can be safely exposed under the same
origin as the mirror frontend:
- dynamic /token.js generation
- account pool round-robin with cooldown
- success/failure feedback
- local unified conversation persistence
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DB_NAME = os.environ.get("MIRROR_DB_NAME", "cool")
DB_USER = os.environ.get("MIRROR_DB_USER", "root")
BROKER_HOST = os.environ.get("MIRROR_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.environ.get("MIRROR_BROKER_PORT", "18081"))
DEFAULT_COOLDOWN_SEC = int(os.environ.get("MIRROR_ACCOUNT_COOLDOWN_SEC", "1800"))
MAX_BODY_BYTES = int(os.environ.get("MIRROR_MAX_BODY_BYTES", str(2 * 1024 * 1024)))
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
CONV_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _mysql(args: list[str], *, input_text: str | None = None, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    cmd = ["mysql", "-u", DB_USER, DB_NAME, "--batch", "--raw", "--skip-column-names", *args]
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _execute(sql: str, *, timeout: int = 20) -> None:
    result = _mysql([], input_text=sql, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mysql execute failed")


def _execute_many(statements: list[str], *, timeout: int = 20) -> None:
    for sql in statements:
        _execute(sql, timeout=timeout)


def _query_rows(sql: str, *, timeout: int = 20) -> list[list[str]]:
    result = _mysql(["-e", sql], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mysql query failed")
    rows: list[list[str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        rows.append(line.split("\t"))
    return rows


def _sql_string(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    text = text.replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _safe_identifier(value: str, pattern: re.Pattern[str], field: str) -> str:
    if not value or not pattern.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def ensure_schema() -> None:
    _execute(
        """
CREATE TABLE IF NOT EXISTS mirror_account_state (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  createTime DATETIME(3) NOT NULL,
  updateTime DATETIME(3) NOT NULL,
  sessionId BIGINT UNSIGNED NOT NULL,
  failCount BIGINT DEFAULT 0,
  cooldownUntil DATETIME(3) DEFAULT NULL,
  lastError TEXT DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY idx_mirror_account_state_session_id (sessionId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
    )
    _execute(
        """
CREATE TABLE IF NOT EXISTS mirror_conversations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  createTime DATETIME(3) NOT NULL,
  updateTime DATETIME(3) NOT NULL,
  deleted_at DATETIME(3) DEFAULT NULL,
  usertoken VARCHAR(255) NOT NULL,
  convid VARCHAR(255) NOT NULL,
  title TEXT,
  sso LONGTEXT,
  content LONGTEXT,
  PRIMARY KEY (id),
  UNIQUE KEY idx_mirror_conversation_user_conv (usertoken, convid),
  KEY idx_mirror_conversation_user_token (usertoken),
  KEY idx_mirror_conversation_conv_id (convid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
    )


def choose_account(*, rotate: bool = True) -> dict[str, Any]:
    ensure_schema()
    rows = _query_rows(
        """
SELECT s.id, s.officialSession, COALESCE(s.count, 0), COALESCE(m.failCount, 0)
FROM grok_session s
LEFT JOIN mirror_account_state m ON m.sessionId = s.id
WHERE s.deleted_at IS NULL
  AND s.status = 1
  AND s.officialSession IS NOT NULL
  AND s.officialSession != ''
  AND (m.cooldownUntil IS NULL OR m.cooldownUntil <= NOW())
ORDER BY COALESCE(m.failCount, 0) ASC, COALESCE(s.count, 0) ASC, s.updateTime ASC, s.id ASC
LIMIT 1;
"""
    )
    if not rows:
        rows = _query_rows(
            """
SELECT u.id, u.userToken, COALESCE(u.count, 0), 0
FROM grok_user u
WHERE u.deleted_at IS NULL
  AND u.userToken IS NOT NULL
  AND u.userToken != ''
  AND (u.expireTime IS NULL OR u.expireTime > NOW())
ORDER BY COALESCE(u.count, 0) ASC, u.updateTime ASC, u.id ASC
LIMIT 1;
"""
        )
    if not rows:
        raise LookupError("no available account")

    session_id, token, count, fail_count = rows[0][0], rows[0][1], rows[0][2], rows[0][3]
    if rotate:
        token_sql = _sql_string(token)
        _execute_many([
            f"""
UPDATE grok_session
SET count = COALESCE(count, 0) + 1, updateTime = NOW()
WHERE id = {int(session_id)};
""",
            f"""
INSERT INTO grok_user (createTime, updateTime, userToken, expireTime, isPro, remark, count)
SELECT NOW(), NOW(), {token_sql}, '2027-12-31 00:00:00', 0, 'mirror-broker', 0
WHERE NOT EXISTS (SELECT 1 FROM grok_user WHERE userToken = {token_sql});
""",
        ])
    return {
        "sessionId": int(session_id),
        "token": token,
        "count": int(count or 0),
        "failCount": int(fail_count or 0),
    }


def mark_failure(session_id: int | None, token: str | None, reason: str, cooldown_sec: int) -> dict[str, Any]:
    ensure_schema()
    if session_id is None and token:
        rows = _query_rows(
            f"SELECT id FROM grok_session WHERE officialSession = {_sql_string(token)} LIMIT 1;"
        )
        session_id = int(rows[0][0]) if rows else None
    if session_id is None:
        return {"status": "ignored", "reason": "missing session"}
    reason = (reason or "unknown")[:1000]
    cooldown_sec = max(60, min(int(cooldown_sec or DEFAULT_COOLDOWN_SEC), 24 * 3600))
    _execute_many([
        f"""
INSERT INTO mirror_account_state (createTime, updateTime, sessionId, failCount, cooldownUntil, lastError)
VALUES (NOW(), NOW(), {int(session_id)}, 1, DATE_ADD(NOW(), INTERVAL {cooldown_sec} SECOND), {_sql_string(reason)})
ON DUPLICATE KEY UPDATE
  updateTime = NOW(),
  failCount = failCount + 1,
  cooldownUntil = DATE_ADD(NOW(), INTERVAL {cooldown_sec} SECOND),
  lastError = VALUES(lastError);
""",
        f"UPDATE grok_session SET updateTime = NOW() WHERE id = {int(session_id)};",
    ])
    return {"status": "success", "sessionId": int(session_id), "cooldownSec": cooldown_sec}


def mark_success(session_id: int | None, token: str | None) -> dict[str, Any]:
    ensure_schema()
    if session_id is None and token:
        rows = _query_rows(
            f"SELECT id FROM grok_session WHERE officialSession = {_sql_string(token)} LIMIT 1;"
        )
        session_id = int(rows[0][0]) if rows else None
    if session_id is None:
        return {"status": "ignored", "reason": "missing session"}
    _execute_many([
        f"""
INSERT INTO mirror_account_state (createTime, updateTime, sessionId, failCount, cooldownUntil, lastError)
VALUES (NOW(), NOW(), {int(session_id)}, 0, NULL, NULL)
ON DUPLICATE KEY UPDATE
  updateTime = NOW(),
  failCount = 0,
  cooldownUntil = NULL,
  lastError = NULL;
""",
        f"UPDATE grok_session SET count = COALESCE(count, 0) + 1, updateTime = NOW() WHERE id = {int(session_id)};",
    ])
    return {"status": "success", "sessionId": int(session_id)}


def save_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    client_id = _safe_identifier(str(payload.get("clientId") or ""), CLIENT_ID_RE, "clientId")
    conv_id = _safe_identifier(str(payload.get("conversationId") or ""), CONV_ID_RE, "conversationId")
    title = str(payload.get("title") or "未命名会话")[:500]
    sso = str(payload.get("sso") or payload.get("sessionId") or "")[:2000]
    content = payload.get("content")
    if content is None:
        content = {k: v for k, v in payload.items() if k not in {"clientId", "conversationId", "title", "sso"}}
    content_json = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    _execute(
        f"""
INSERT INTO mirror_conversations (createTime, updateTime, usertoken, convid, title, sso, content)
VALUES (NOW(), NOW(), {_sql_string(client_id)}, {_sql_string(conv_id)}, {_sql_string(title)}, {_sql_string(sso)}, {_sql_string(content_json)})
ON DUPLICATE KEY UPDATE
  updateTime = NOW(),
  title = VALUES(title),
  sso = VALUES(sso),
  content = VALUES(content);
"""
    )
    return {"status": "success", "clientId": client_id, "conversationId": conv_id}


def list_conversations(client_id: str) -> dict[str, Any]:
    client_id = _safe_identifier(client_id, CLIENT_ID_RE, "clientId")
    rows = _query_rows(
        f"""
SELECT convid, COALESCE(title, ''), DATE_FORMAT(updateTime, '%Y-%m-%d %H:%i:%s')
FROM mirror_conversations
WHERE deleted_at IS NULL AND usertoken = {_sql_string(client_id)}
ORDER BY updateTime DESC
LIMIT 100;
"""
    )
    return {
        "status": "success",
        "items": [
            {"conversationId": row[0], "title": row[1], "updateTime": row[2]}
            for row in rows
        ],
    }


def get_conversation(client_id: str, conv_id: str) -> dict[str, Any]:
    client_id = _safe_identifier(client_id, CLIENT_ID_RE, "clientId")
    conv_id = _safe_identifier(conv_id, CONV_ID_RE, "conversationId")
    rows = _query_rows(
        f"""
SELECT convid, COALESCE(title, ''), COALESCE(content, '{{}}'), DATE_FORMAT(updateTime, '%Y-%m-%d %H:%i:%s')
FROM mirror_conversations
WHERE deleted_at IS NULL AND usertoken = {_sql_string(client_id)} AND convid = {_sql_string(conv_id)}
LIMIT 1;
"""
    )
    if not rows:
        raise LookupError("conversation not found")
    raw = rows[0][2]
    try:
        content = json.loads(raw)
    except json.JSONDecodeError:
        content = raw
    return {
        "status": "success",
        "conversationId": rows[0][0],
        "title": rows[0][1],
        "content": content,
        "updateTime": rows[0][3],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MirrorBroker/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or "0")
        if size > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(size) if size else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "same-origin")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/healthz":
                self._json({"status": "ok"})
                return
            if parsed.path == "/token.js":
                account = choose_account(rotate=True)
                token_js = account["token"].replace("\\", "\\\\").replace("'", "\\'")
                body = (
                    f"window.__GROK_LOGIN_TOKEN__ = '{token_js}';\n"
                    "window.__GROK_LOGIN_TOKEN_READY__ = true;\n"
                    "window.__GROK_LOGIN_TOKEN_ERROR__ = '';\n"
                    f"window.__GROK_LOGIN_SESSION_ID__ = {account['sessionId']};\n"
                ).encode("utf-8")
                self._send(200, body, "application/javascript; charset=utf-8")
                return
            if parsed.path == "/__mirror/conversation/list":
                qs = parse_qs(parsed.query)
                self._json(list_conversations((qs.get("clientId") or [""])[0]))
                return
            if parsed.path == "/__mirror/conversation/get":
                qs = parse_qs(parsed.query)
                self._json(get_conversation((qs.get("clientId") or [""])[0], (qs.get("conversationId") or [""])[0]))
                return
            self._json({"error": "not found"}, 404)
        except LookupError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/__mirror/account/next":
                self._json({"status": "success", **choose_account(rotate=True)})
                return
            if parsed.path == "/__mirror/account/fail":
                self._json(mark_failure(
                    payload.get("sessionId"),
                    payload.get("token"),
                    str(payload.get("reason") or "unknown"),
                    int(payload.get("cooldownSec") or DEFAULT_COOLDOWN_SEC),
                ))
                return
            if parsed.path == "/__mirror/account/success":
                self._json(mark_success(payload.get("sessionId"), payload.get("token")))
                return
            if parsed.path == "/__mirror/conversation/save":
                self._json(save_conversation(payload))
                return
            self._json({"error": "not found"}, 404)
        except LookupError as exc:
            self._json({"error": str(exc)}, 404)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def main() -> None:
    ensure_schema()
    httpd = ThreadingHTTPServer((BROKER_HOST, BROKER_PORT), Handler)
    print(f"mirror-broker listening on {BROKER_HOST}:{BROKER_PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
