"""Database access helpers and convenience wrappers.

Provides thin helpers for conversation and outreach CRUD operations.
"""

import hashlib
import psycopg
from psycopg.rows import dict_row
import os
from datetime import date as _date, datetime as _datetime

from dotenv import load_dotenv
load_dotenv()

_USE_RENDER_DB = os.getenv("USE_RENDER_DB", "").lower() in ("1", "true", "yes")
if _USE_RENDER_DB:
    CONNECTION_STRING = os.getenv("RENDER_DATABASE_URL") or os.getenv("DATABASE_URL")
else:
    CONNECTION_STRING = os.getenv("DATABASE_URL")

def update_conversation(metadata, previous_text, service_user_id):
    """
    Update the information in the conversations database
        Based on a new message

    Arguments:
        metadata: Dictionary with username and conversation_id
        previous_text: List of dictionaries with sender and text
    
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

    conn.commit()
    conn.close()

def generate_service_user_id(provider_username: str, patient_name: str) -> str:
    """
    Deterministically generate a pseudonymous service user ID
    based on the provider and service user's names.
    """
    raw = f"{provider_username.strip().lower()}::{patient_name.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]  # short, unique, anonymized


def add_new_service_user(provider_username, patient_name, last_session, next_checkin, location, followup_message):
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()
    try:
        service_user_id = generate_service_user_id(provider_username, patient_name)

        cursor.execute('''
            INSERT INTO profiles (service_user_id, service_user_name, provider, location, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (service_user_id) DO NOTHING
        ''', (service_user_id, patient_name, provider_username, location, "Active"))

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
):
    """Update name, location, and/or status in the profiles table."""
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