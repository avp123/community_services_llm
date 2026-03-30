"""Database access helpers and convenience wrappers.

Provides thin helpers for conversation and outreach CRUD operations.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

import psycopg
import psycopg.errors
from psycopg.rows import dict_row
import os
from datetime import date as _date, datetime as _datetime

from dotenv import load_dotenv
load_dotenv()

_USE_LOCAL_DB = os.getenv("USE_LOCAL_DB", "").lower() in ("1", "true", "yes")
if _USE_LOCAL_DB:
    CONNECTION_STRING = os.getenv("LOCAL_DATABASE_URL")
else:
    CONNECTION_STRING = os.getenv("DATABASE_URL")

if _USE_LOCAL_DB:
    print("[DB] Local main DB mode enabled.")


def _refresh_conversation_stats(cursor, conversation_id: str) -> None:
    """Denormalize roll-up stats onto conversations after new messages (optional columns)."""
    try:
        cursor.execute(
            """
            UPDATE conversations c SET
                stats_message_count = agg.cnt,
                stats_user_messages = agg.ucnt,
                stats_assistant_messages = agg.acnt,
                stats_total_chars = agg.tchars,
                stats_user_chars = agg.uchars,
                stats_assistant_chars = agg.achars,
                stats_first_message_at = agg.first_at,
                stats_last_message_at = agg.last_at,
                stats_updated_at = NOW()
            FROM (
                SELECT
                    COUNT(*)::int AS cnt,
                    COUNT(*) FILTER (WHERE sender = 'user')::int AS ucnt,
                    COUNT(*) FILTER (WHERE sender IN ('system', 'assistant'))::int AS acnt,
                    COALESCE(SUM(CHAR_LENGTH(COALESCE(text, ''))), 0)::bigint AS tchars,
                    COALESCE(
                        SUM(CHAR_LENGTH(COALESCE(text, ''))) FILTER (WHERE sender = 'user'),
                        0
                    )::bigint AS uchars,
                    COALESCE(
                        SUM(CHAR_LENGTH(COALESCE(text, '')))
                        FILTER (WHERE sender IN ('system', 'assistant')),
                        0
                    )::bigint AS achars,
                    MIN(created_at) AS first_at,
                    MAX(created_at) AS last_at
                FROM messages
                WHERE conversation_id = %s
            ) agg
            WHERE c.id = %s
            """,
            (conversation_id, conversation_id),
        )
    except psycopg.errors.UndefinedColumn:
        # If stats columns don't exist yet, Postgres marks the transaction aborted.
        # Roll back just this failed statement's transaction so later updates can succeed.
        cursor.connection.rollback()
        return
    except Exception as e:
        print(f"[DB] _refresh_conversation_stats (non-fatal): {e}")


def _try_set_conversation_title(cursor, conversation_id: str, scrubbed: str) -> None:
    """Set conversations.title once when still empty (migration 002)."""
    if not scrubbed or not str(scrubbed).strip():
        return
    try:
        from backend.app.conversation_meta import derive_chat_title_from_scrubbed_text

        title = derive_chat_title_from_scrubbed_text(scrubbed)
        cursor.execute(
            """
            UPDATE conversations
            SET title = %s
            WHERE id = %s
              AND (title IS NULL OR TRIM(COALESCE(title, '')) = '')
            """,
            (title, conversation_id),
        )
    except psycopg.errors.UndefinedColumn:
        cursor.connection.rollback()
        return
    except Exception as e:
        print(f"[DB] _try_set_conversation_title (non-fatal): {e}")


def _merge_tool_usage_stats(cursor, conversation_id: str, tool_names: List[str]) -> None:
    """Increment per-conversation tool counters (migration 002)."""
    if not tool_names:
        return
    try:
        cursor.execute(
            """
            SELECT stats_tool_calls_total, stats_tool_calls_by_name
            FROM conversations WHERE id = %s
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return
        prev_total = row[0] or 0
        raw = row[1]
        if raw is None:
            by_name: Dict[str, int] = {}
        elif isinstance(raw, dict):
            by_name = {str(k): int(v) for k, v in raw.items()}
        else:
            by_name = {}
        for t in tool_names:
            by_name[t] = by_name.get(t, 0) + 1
        new_total = prev_total + len(tool_names)
        cursor.execute(
            """
            UPDATE conversations
            SET stats_tool_calls_total = %s,
                stats_tool_calls_by_name = %s::jsonb
            WHERE id = %s
            """,
            (new_total, json.dumps(by_name), conversation_id),
        )
    except psycopg.errors.UndefinedColumn:
        cursor.connection.rollback()
        return
    except Exception as e:
        print(f"[DB] _merge_tool_usage_stats (non-fatal): {e}")


def _summarize_message_rows(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build summary stats from loaded message dicts (sender, text, created_at)."""
    user_n = ast_n = 0
    total_chars = user_chars = ast_chars = 0
    times: List[str] = []
    for m in messages:
        s = m.get("sender") or ""
        text = m.get("text") or ""
        ln = len(text)
        total_chars += ln
        if s == "user":
            user_n += 1
            user_chars += ln
        elif s in ("system", "assistant"):
            ast_n += 1
            ast_chars += ln
        ca = m.get("created_at")
        if ca is not None:
            times.append(ca if isinstance(ca, str) else ca.isoformat())
    first_at = min(times) if times else None
    last_at = max(times) if times else None
    n = len(messages)
    duration_seconds = None
    if first_at and last_at:
        try:
            from datetime import datetime

            a = datetime.fromisoformat(first_at.replace("Z", "+00:00"))
            b = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            duration_seconds = (b - a).total_seconds()
        except (ValueError, TypeError):
            pass
    return {
        "message_count": n,
        "user_message_count": user_n,
        "assistant_message_count": ast_n,
        "total_chars": total_chars,
        "user_chars": user_chars,
        "assistant_chars": ast_chars,
        "first_message_at": first_at,
        "last_message_at": last_at,
        "duration_seconds": duration_seconds,
        "avg_chars_per_message": round(total_chars / n, 1) if n else 0.0,
    }


def update_conversation(
    metadata,
    previous_text,
    service_user_id,
    scrubbed_first_user_text: Optional[str] = None,
    tool_names_this_turn: Optional[List[str]] = None,
):
    """
    Update the information in the conversations database
        Based on a new message

    Arguments:
        metadata: Dictionary with username and conversation_id
        previous_text: List of dictionaries with sender and text
        scrubbed_first_user_text: PHI-scrubbed first user line for one-time title (optional)
        tool_names_this_turn: Tool function names invoked during this generation (optional)

    Returns: None

    Side Effects: Writes the text in previous_text to the database
    """
    username = metadata.get("username")
    conversation_id = metadata.get("conversation_id")
    
    if not conversation_id:
        import uuid
        conversation_id = str(uuid.uuid4())
        print(f"[DB] Generated new conversation_id: {conversation_id}")

    if username == "" or conversation_id == "":
        return

    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM conversations WHERE id = %s", (conversation_id,))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO conversations (id, username,outreach_generated, service_user_id) VALUES (%s, %s, %s, %s)",
            (conversation_id, username,False, service_user_id)
        )

    cursor.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = %s",
        (conversation_id,),
    )
    msg_count_before = cursor.fetchone()[0]

    for msg in previous_text:
        sender = msg["role"]
        text = msg["content"]
        if sender and text:
            # Compute hash for deduplication (avoids btree index size limits)
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            cursor.execute(
                "INSERT INTO messages (conversation_id, sender, text, text_hash, service_user_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (conversation_id, sender, text_hash) DO NOTHING",
                (conversation_id, sender, text, text_hash, service_user_id)
            )

    # Commit base writes (conversation row + messages) first.
    # This prevents a later "optional column" failure from rolling back/poisoning
    # the core persistence, which would make chats disappear from history.
    conn.commit()

    # Start a fresh transaction for optional rollups (stats/title/tool counters).
    cursor = conn.cursor()
    _refresh_conversation_stats(cursor, conversation_id)

    if msg_count_before == 0 and scrubbed_first_user_text:
        _try_set_conversation_title(cursor, conversation_id, scrubbed_first_user_text)
    if tool_names_this_turn:
        _merge_tool_usage_stats(cursor, conversation_id, tool_names_this_turn)

    conn.commit()
    conn.close()

def generate_service_user_id(provider_username: str, patient_name: str) -> str:
    """
    Deterministically generate a pseudonymous service user ID
    based on the provider and service user's names.
    """
    raw = f"{provider_username.strip().lower()}::{patient_name.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]  # short, unique, anonymized


def fetch_service_user_custom_prompt(service_user_id: str):
    """Return profiles.custom_prompt for a service user, or None."""
    if not service_user_id:
        return None
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT custom_prompt FROM profiles WHERE service_user_id = %s",
                    (service_user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return row.get("custom_prompt")
    except Exception as e:
        print(f"[DB] fetch_service_user_custom_prompt error: {e}")
        return None


def add_new_service_user(
    provider_username,
    patient_name,
    last_session,
    next_checkin,
    location,
    followup_message,
    custom_prompt=None,
):
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()
    try:
        service_user_id = generate_service_user_id(provider_username, patient_name)

        cursor.execute(
            """
            INSERT INTO profiles (service_user_id, service_user_name, provider, location, status, custom_prompt)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (service_user_id) DO NOTHING
            """,
            (service_user_id, patient_name, provider_username, location, "Active", custom_prompt),
        )

        # ← this part was missing entirely
        if next_checkin:
            cursor.execute('''
                INSERT INTO outreach_details (service_user_id, last_session, check_in, follow_up_message)
                VALUES (%s, %s, %s, %s)
            ''', (service_user_id, last_session or None, next_checkin, followup_message or ''))

        conn.commit()
        return True, f"Check-in saved successfully (ID: {service_user_id})"
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()

def edit_service_user_outreach(check_in_id, date, message):
    conn = psycopg.connect(CONNECTION_STRING)
    conn.row_factory = dict_row
    cursor = conn.cursor()
    try:
        cursor.execute('''
        UPDATE outreach_details
        SET check_in = %s, follow_up_message = %s
        WHERE id = %s
        ''', (date, message, check_in_id))
        conn.commit()
        return True, "Success"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()
        


def fetch_service_user_checkins(service_user_id):
    conn = psycopg.connect(CONNECTION_STRING)
    conn.row_factory = dict_row
    cursor = conn.cursor()
    try:
        cursor.execute('''
        SELECT o.id, o.check_in, o.follow_up_message, o.last_session, o.created_at
        FROM outreach_details o
        WHERE o.service_user_id = %s
        ORDER BY o.check_in ASC
        LIMIT 3
        ''', (service_user_id,))
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        return True, result
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()
        
def fetch_provider_checkins_by_date(provider, check_in_date):
    conn = psycopg.connect(CONNECTION_STRING)
    conn.row_factory = dict_row
    cursor = conn.cursor()
    try:
        # Ensure check_in_date is a string in YYYY-MM-DD (DB stores check_in as text)
        if isinstance(check_in_date, (_date, _datetime)):
            check_in_date = check_in_date.strftime("%Y-%m-%d")

        cursor.execute('''
        SELECT p.service_user_id, p.service_user_name,
            o.check_in, o.follow_up_message
        FROM profiles p
        INNER JOIN outreach_details o ON p.service_user_id = o.service_user_id
        WHERE p.provider = %s
            AND o.check_in = %s
        ''', (provider, check_in_date))
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        return True, result
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def fetch_providers_to_notify_checkins(time_begin, time_end):
    conn = psycopg.connect(CONNECTION_STRING)
    conn.row_factory = dict_row
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT id, username, email, notification_time
            FROM users 
            WHERE notifications_enabled = TRUE
                AND email IS NOT NULL
                AND notification_time >= %s 
                AND notification_time < %s
        ''', (time_begin, time_end))
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        return True, result
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def update_notification_settings(username, email, notifications_enabled, notification_time):
    """
    Update user's email and notification settings
    
    Arguments:
        username: Username to update
        email: Email address
        notifications_enabled: Boolean for notifications on/off
        notification_time: Time string in HH:MM format (e.g., "09:00")
    
    Returns:
        Tuple: (success: bool, message: str)
    """
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        UPDATE users
        SET email = %s, 
            notifications_enabled = %s, 
            notification_time = %s
        WHERE username = %s
        ''', (email, notifications_enabled, notification_time, username))
        
        conn.commit()
        
        if cursor.rowcount == 0:
            return False, "User not found"
        
        return True, "Settings updated successfully"
        
    except Exception as e:
        conn.rollback()
        print(f"[DB Error] {e}")
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()


def get_notification_settings(username):
    """
    Get user's notification settings
    
    Arguments:
        username: Username to query
    
    Returns:
        Tuple: (success: bool, settings: dict or error message)
    """
    conn = psycopg.connect(CONNECTION_STRING)
    conn.row_factory = dict_row
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        SELECT email, notifications_enabled, notification_time
        FROM users
        WHERE username = %s
        ''', (username,))
        
        row = cursor.fetchone()
        
        if row is None:
            return False, "User not found"
        
        return True, dict(row)
        
    except Exception as e:
        print(f"[DB Error] {e}")
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()


def fetch_account_custom_prompt(username: str):
    """Return users.custom_prompt for the logged-in provider, or None."""
    if not username:
        return None
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT custom_prompt FROM users WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return row.get("custom_prompt")
    except Exception as e:
        print(f"[DB] fetch_account_custom_prompt error: {e}")
        return None


def update_account_custom_prompt(username: str, custom_prompt: Optional[str]):
    """Persist users.custom_prompt (empty string clears to empty)."""
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET custom_prompt = %s WHERE username = %s",
                    (custom_prompt if custom_prompt is not None else "", username),
                )
                n = cur.rowcount
            conn.commit()
        if n == 0:
            return False, "User not found"
        return True, "Updated"
    except Exception as e:
        print(f"[DB] update_account_custom_prompt error: {e}")
        return False, str(e)


def delete_service_user_checkin(check_in_id):
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM outreach_details WHERE id = %s",
                    (int(check_in_id),),  # cast to int to be safe
                )
            conn.commit()
        return True, "Deleted"
    except Exception as e:
        print(f"[DB] delete_service_user_checkin error: {e}")
        return False, str(e)


def add_service_user_checkin(service_user_id: str, check_in: str, follow_up_message: str = ""):
    """Insert a new check-in row and return the new row's ID."""
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                # Pull the latest last_session for this user so the row is consistent
                cur.execute(
                    """SELECT last_session FROM outreach_details
                       WHERE service_user_id = %s
                       ORDER BY created_at DESC LIMIT 1""",
                    (service_user_id,),
                )
                row = cur.fetchone()
                last_session = row[0] if row else None

                cur.execute(
                    """INSERT INTO outreach_details
                       (service_user_id, last_session, check_in, follow_up_message)
                       VALUES (%s, %s, %s, %s)
                       RETURNING id""",
                    (service_user_id, last_session, check_in, follow_up_message),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        return True, str(new_id)
    except Exception as e:
        print(f"[DB] add_service_user_checkin error: {e}")
        return False, str(e)


def update_service_user_profile(
    service_user_id: str,
    patientName: str = None,
    location: str = None,
    status: str = None,
    custom_prompt: str = None,
):
    """Update name, location, status, and/or custom_prompt in the profiles table."""
    fields = []
    values = []

    if patientName is not None:
        fields.append("service_user_name = %s")
        values.append(patientName)
    if location is not None:
        fields.append("location = %s")
        values.append(location)
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if custom_prompt is not None:
        fields.append("custom_prompt = %s")
        values.append(custom_prompt)

    if not fields:
        return True, "Nothing to update"

    values.append(service_user_id)
    sql = f"UPDATE profiles SET {', '.join(fields)} WHERE service_user_id = %s"

    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
            conn.commit()
        return True, "Updated"
    except Exception as e:
        print(f"[DB] update_service_user_profile error: {e}")
        return False, str(e)


def update_last_session_db(service_user_id: str, last_session: str):
    """Update last_session on the most recent outreach_details row for the user.
    If no outreach row exists yet, insert a minimal one.
    """
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                # Try to update the existing row
                cur.execute(
                    """UPDATE outreach_details
                       SET last_session = %s
                       WHERE id = (
                           SELECT id FROM outreach_details
                           WHERE service_user_id = %s
                           ORDER BY created_at DESC
                           LIMIT 1
                       )""",
                    (last_session, service_user_id),
                )
                if cur.rowcount == 0:
                    # No outreach row yet — insert a seed row
                    cur.execute(
                        """INSERT INTO outreach_details
                           (service_user_id, last_session)
                           VALUES (%s, %s)""",
                        (service_user_id, last_session),
                    )
            conn.commit()
        return True, "Last session updated"
    except Exception as e:
        print(f"[DB] update_last_session_db error: {e}")
        return False, str(e)


def list_conversation_summaries(username: str, limit: int = 50, offset: int = 0):
    """
    Aggregate per-conversation stats for a provider. Returns (True, list[dict]) or (False, error str).
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    sql = """
        SELECT
            c.id AS conversation_id,
            c.service_user_id,
            p.service_user_name,
            c.title,
            c.stats_tool_calls_total,
            c.stats_tool_calls_by_name,
            COUNT(m.id) AS message_count,
            COUNT(m.id) FILTER (WHERE m.sender = 'user') AS user_message_count,
            COUNT(m.id) FILTER (WHERE m.sender IN ('system', 'assistant')) AS assistant_message_count,
            COALESCE(SUM(CHAR_LENGTH(COALESCE(m.text, ''))), 0)::bigint AS total_chars,
            COALESCE(
                SUM(CHAR_LENGTH(COALESCE(m.text, ''))) FILTER (WHERE m.sender = 'user'),
                0
            )::bigint AS user_chars,
            COALESCE(
                SUM(CHAR_LENGTH(COALESCE(m.text, '')))
                FILTER (WHERE m.sender IN ('system', 'assistant')),
                0
            )::bigint AS assistant_chars,
            MIN(m.created_at) AS first_message_at,
            MAX(m.created_at) AS last_message_at
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        LEFT JOIN profiles p
            ON p.service_user_id = c.service_user_id AND p.provider = c.username
        WHERE c.username = %s
        GROUP BY c.id, c.service_user_id, p.service_user_name, c.title,
                 c.stats_tool_calls_total, c.stats_tool_calls_by_name
        ORDER BY MAX(m.created_at) DESC NULLS LAST, c.id DESC
        LIMIT %s OFFSET %s
    """
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(sql, (username, limit, offset))
                rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            first_at = d.get("first_message_at")
            last_at = d.get("last_message_at")
            duration_seconds = None
            if first_at is not None and last_at is not None:
                try:
                    duration_seconds = (last_at - first_at).total_seconds()
                except (TypeError, AttributeError):
                    duration_seconds = None
            d["duration_seconds"] = duration_seconds
            if first_at is not None and hasattr(first_at, "isoformat"):
                d["first_message_at"] = first_at.isoformat()
            if last_at is not None and hasattr(last_at, "isoformat"):
                d["last_message_at"] = last_at.isoformat()
            mc = d.get("message_count") or 0
            d["avg_chars_per_message"] = (
                round(d["total_chars"] / mc, 1) if mc else 0.0
            )
            for k in (
                "message_count",
                "user_message_count",
                "assistant_message_count",
                "total_chars",
                "user_chars",
                "assistant_chars",
            ):
                if d.get(k) is None:
                    d[k] = 0
            tc = d.get("stats_tool_calls_total")
            d["stats_tool_calls_total"] = int(tc) if tc is not None else 0
            raw_tools = d.get("stats_tool_calls_by_name")
            if raw_tools is None:
                d["stats_tool_calls_by_name"] = {}
            elif isinstance(raw_tools, dict):
                d["stats_tool_calls_by_name"] = {
                    str(k): int(v) for k, v in raw_tools.items()
                }
            else:
                d["stats_tool_calls_by_name"] = {}
            out.append(d)
        return True, out
    except Exception as e:
        print(f"[DB] list_conversation_summaries error: {e}")
        return False, str(e)


def get_user_conversation_global_stats(username: str):
    """
    Global conversation analytics for one provider account.
    Returns (True, dict) or (False, error str).
    """
    sql = """
        WITH per_conv AS (
            SELECT
                c.id AS conversation_id,
                MIN(m.created_at) AS first_message_at,
                MAX(m.created_at) AS last_message_at,
                COUNT(m.id)::int AS message_count,
                COUNT(m.id) FILTER (WHERE m.sender = 'user')::int AS user_message_count,
                COUNT(m.id) FILTER (WHERE m.sender IN ('system', 'assistant'))::int AS assistant_message_count,
                COALESCE(SUM(CHAR_LENGTH(COALESCE(m.text, ''))), 0)::bigint AS total_chars
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.username = %s
            GROUP BY c.id
        )
        SELECT
            COUNT(*)::int AS conversation_count,
            COALESCE(SUM(message_count), 0)::bigint AS message_count,
            COALESCE(SUM(user_message_count), 0)::bigint AS user_message_count,
            COALESCE(SUM(assistant_message_count), 0)::bigint AS assistant_message_count,
            COALESCE(SUM(total_chars), 0)::bigint AS total_chars,
            MIN(first_message_at) AS first_message_at,
            MAX(last_message_at) AS last_message_at,
            COALESCE(
                AVG(EXTRACT(EPOCH FROM (last_message_at - first_message_at)))
                FILTER (WHERE first_message_at IS NOT NULL AND last_message_at IS NOT NULL),
                0
            )::double precision AS avg_duration_seconds
        FROM per_conv
    """
    tools_sql = """
        SELECT c.stats_tool_calls_by_name
        FROM conversations c
        WHERE c.username = %s
          AND c.stats_tool_calls_by_name IS NOT NULL
    """
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(sql, (username,))
                row = dict(cur.fetchone() or {})
                cur.execute(tools_sql, (username,))
                tool_rows = cur.fetchall()

        conversation_count = int(row.get("conversation_count") or 0)
        message_count = int(row.get("message_count") or 0)
        user_message_count = int(row.get("user_message_count") or 0)
        assistant_message_count = int(row.get("assistant_message_count") or 0)
        total_chars = int(row.get("total_chars") or 0)

        tool_totals: Dict[str, int] = {}
        for r in tool_rows:
            raw = r.get("stats_tool_calls_by_name")
            if isinstance(raw, dict):
                for k, v in raw.items():
                    key = str(k)
                    tool_totals[key] = tool_totals.get(key, 0) + int(v or 0)

        top_tools = [
            {"name": name, "count": count}
            for name, count in sorted(tool_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]
        total_tool_calls = sum(tool_totals.values())

        first_at = row.get("first_message_at")
        last_at = row.get("last_message_at")
        avg_duration_seconds = float(row.get("avg_duration_seconds") or 0.0)

        return True, {
            "conversation_count": conversation_count,
            "message_count": message_count,
            "user_message_count": user_message_count,
            "assistant_message_count": assistant_message_count,
            "total_chars": total_chars,
            "avg_messages_per_conversation": round(message_count / conversation_count, 2) if conversation_count else 0.0,
            "avg_chars_per_message": round(total_chars / message_count, 2) if message_count else 0.0,
            "avg_duration_seconds": round(avg_duration_seconds, 2),
            "first_message_at": first_at.isoformat() if first_at is not None and hasattr(first_at, "isoformat") else None,
            "last_message_at": last_at.isoformat() if last_at is not None and hasattr(last_at, "isoformat") else None,
            "total_tool_calls": int(total_tool_calls),
            "distinct_tool_count": len(tool_totals),
            "top_tools": top_tools,
        }
    except Exception as e:
        print(f"[DB] get_user_conversation_global_stats error: {e}")
        return False, str(e)


def get_user_weekly_usage_stats(username: str, weeks: int = 12):
    """
    Weekly usage trend aggregates for one provider account.
    Returns (True, list[dict]) or (False, error str).
    """
    weeks = max(2, min(int(weeks), 52))
    sql = """
        WITH bounds AS (
            SELECT date_trunc('week', NOW())::date AS this_week
        ),
        week_series AS (
            SELECT (this_week - (gs * INTERVAL '1 week'))::date AS week_start
            FROM bounds, generate_series(%s - 1, 0, -1) AS gs
        ),
        msg_week AS (
            SELECT
                date_trunc('week', m.created_at)::date AS week_start,
                COUNT(*)::int AS messages_total,
                COUNT(*) FILTER (WHERE m.sender = 'user')::int AS messages_user,
                COUNT(*) FILTER (WHERE m.sender IN ('system', 'assistant'))::int AS messages_assistant,
                COALESCE(SUM(CHAR_LENGTH(COALESCE(m.text, ''))), 0)::bigint AS total_chars,
                COUNT(DISTINCT m.conversation_id)::int AS sessions_active
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.username = %s
              AND m.created_at >= ((SELECT this_week FROM bounds) - (%s - 1) * INTERVAL '1 week')
            GROUP BY 1
        ),
        conv_started AS (
            SELECT
                date_trunc('week', c.created_at)::date AS week_start,
                COUNT(*)::int AS sessions_started
            FROM conversations c
            WHERE c.username = %s
              AND c.created_at >= ((SELECT this_week FROM bounds) - (%s - 1) * INTERVAL '1 week')
            GROUP BY 1
        ),
        conv_created_week AS (
            SELECT
                date_trunc('week', c.created_at)::date AS week_start,
                COALESCE(c.stats_tool_calls_total, 0)::bigint AS tool_calls_total
            FROM conversations c
            WHERE c.username = %s
              AND c.created_at >= ((SELECT this_week FROM bounds) - (%s - 1) * INTERVAL '1 week')
        ),
        conv_tools_week AS (
            SELECT
                week_start,
                SUM(tool_calls_total)::bigint AS tool_calls_total
            FROM conv_created_week
            GROUP BY week_start
        )
        SELECT
            ws.week_start,
            COALESCE(mw.sessions_active, 0) AS sessions_active,
            COALESCE(cs.sessions_started, 0) AS sessions_started,
            COALESCE(mw.messages_total, 0) AS messages_total,
            COALESCE(mw.messages_user, 0) AS messages_user,
            COALESCE(mw.messages_assistant, 0) AS messages_assistant,
            COALESCE(mw.total_chars, 0)::bigint AS total_chars,
            COALESCE(clw.tool_calls_total, 0)::bigint AS tool_calls_total
        FROM week_series ws
        LEFT JOIN msg_week mw ON mw.week_start = ws.week_start
        LEFT JOIN conv_started cs ON cs.week_start = ws.week_start
        LEFT JOIN conv_tools_week clw ON clw.week_start = ws.week_start
        ORDER BY ws.week_start ASC
    """
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(sql, (weeks, username, weeks, username, weeks, username, weeks))
                rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in (
                "sessions_active",
                "sessions_started",
                "messages_total",
                "messages_user",
                "messages_assistant",
                "total_chars",
                "tool_calls_total",
            ):
                d[key] = int(d.get(key) or 0)
            mt = d["messages_total"]
            d["avg_chars_per_message"] = round(d["total_chars"] / mt, 2) if mt else 0.0
            ws = d.get("week_start")
            if ws is not None and hasattr(ws, "isoformat"):
                d["week_start"] = ws.isoformat()
            out.append(d)
        return True, out
    except Exception as e:
        print(f"[DB] get_user_weekly_usage_stats error: {e}")
        return False, str(e)


def get_conversation_messages_for_user(conversation_id: str, owner_username: str):
    """
    Load messages if the conversation belongs to owner_username.
    Returns (True, list[dict]) | (False, 'forbidden'|'not_found'|error str).
    """
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, service_user_id, title,
                           stats_tool_calls_total, stats_tool_calls_by_name
                    FROM conversations WHERE id = %s
                    """,
                    (conversation_id,),
                )
                conv = cur.fetchone()
                if conv is None:
                    return False, "not_found"
                if conv.get("username") != owner_username:
                    return False, "forbidden"
                service_user_id = conv.get("service_user_id")
                tc = conv.get("stats_tool_calls_total")
                tool_total = int(tc) if tc is not None else 0
                raw_tools = conv.get("stats_tool_calls_by_name")
                if raw_tools is None:
                    tool_by_name: Dict[str, int] = {}
                elif isinstance(raw_tools, dict):
                    tool_by_name = {str(k): int(v) for k, v in raw_tools.items()}
                else:
                    tool_by_name = {}
                cur.execute(
                    """
                    SELECT sender, text, created_at
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC NULLS LAST
                    """,
                    (conversation_id,),
                )
                msgs = cur.fetchall()
        result = []
        for m in msgs:
            row = dict(m)
            ca = row.get("created_at")
            if ca is not None and hasattr(ca, "isoformat"):
                row["created_at"] = ca.isoformat()
            result.append(row)
        summary = _summarize_message_rows(result)
        return True, {
            "service_user_id": service_user_id,
            "title": conv.get("title"),
            "stats_tool_calls_total": tool_total,
            "stats_tool_calls_by_name": tool_by_name,
            "messages": result,
            "summary": summary,
        }
    except Exception as e:
        print(f"[DB] get_conversation_messages_for_user error: {e}")
        return False, str(e)


def conversation_owned_by_user(conversation_id: str, owner_username: str):
    """Return (True, True/False) if conversation exists and is owned by user."""
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM conversations WHERE id = %s",
                    (conversation_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return True, False
                return True, row[0] == owner_username
    except Exception as e:
        print(f"[DB] conversation_owned_by_user error: {e}")
        return False, str(e)


def get_session_feedback(conversation_id: str, username: str):
    """Fetch autosaved 5-question feedback row for a conversation+user."""
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT q1, q2, q3, q4, q5, feedback_text, updated_at
                    FROM conversation_feedback
                    WHERE conversation_id = %s AND username = %s
                    """,
                    (conversation_id, username),
                )
                row = cur.fetchone()
        if not row:
            return True, {
                "q1": None,
                "q2": None,
                "q3": None,
                "q4": None,
                "q5": None,
                "feedback_text": "",
                "updated_at": None,
            }
        out = dict(row)
        ts = out.get("updated_at")
        if ts is not None and hasattr(ts, "isoformat"):
            out["updated_at"] = ts.isoformat()
        return True, out
    except Exception as e:
        print(f"[DB] get_session_feedback error: {e}")
        return False, str(e)


def upsert_session_feedback_answer(
    conversation_id: str,
    username: str,
    question_id: Optional[str] = None,
    value: Optional[int] = None,
    feedback_text: Optional[str] = None,
):
    """Upsert feedback row and update one answer and/or feedback text."""
    allowed = {"q1", "q2", "q3", "q4", "q5"}
    if question_id is None and feedback_text is None:
        return False, "No update payload provided"
    if question_id is not None and question_id not in allowed:
        return False, "Invalid question_id"
    if question_id is not None and (value is None or int(value) < 1 or int(value) > 5):
        return False, "Value must be an integer between 1 and 5"
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_feedback (conversation_id, username, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (conversation_id, username)
                    DO UPDATE SET updated_at = EXCLUDED.updated_at
                    """,
                    (conversation_id, username),
                )
                if question_id is not None:
                    cur.execute(
                        f"""
                        UPDATE conversation_feedback
                        SET {question_id} = %s, updated_at = NOW()
                        WHERE conversation_id = %s AND username = %s
                        """,
                        (int(value), conversation_id, username),
                    )
                if feedback_text is not None:
                    cur.execute(
                        """
                        UPDATE conversation_feedback
                        SET feedback_text = %s, updated_at = NOW()
                        WHERE conversation_id = %s AND username = %s
                        """,
                        (feedback_text, conversation_id, username),
                    )
            conn.commit()
        return True, "Saved"
    except Exception as e:
        print(f"[DB] upsert_session_feedback_answer error: {e}")
        return False, str(e)