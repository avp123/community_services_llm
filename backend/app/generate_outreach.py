"""Outreach helpers: detect urgency, generate follow-ups, and manage check-ins.

Functions in this module interact with the database and the chat model to
produce follow-up messages and schedule check-ins for service users.
"""

import psycopg
import os
import json
from datetime import datetime, timedelta
from app.utils import call_chatgpt_api_all_chats
from app.database import CONNECTION_STRING
import spacy

from openai import AzureOpenAI
client = AzureOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_AZURE"),
    azure_endpoint=os.environ.get("OPENAI_AZURE_ENDPOINT"),
    api_version="2024-12-01-preview"
)

nlp = spacy.load("en_core_web_sm")

keyword_map = {
    "extremely pressing": {"food", "hungry", "unsafe", "shelter"},
    "pressing": {"housing", "rent", "bills", "job"},
    "less pressing": {"therapy", "support group", "resume"},
    "long-term": {"education", "section 8", "career", "training"}
}
negations = {"no", "not", "n't", "never", "without"}
check_in_delta_map = {
    "extremely pressing": 1,
    "pressing": 7,
    "less pressing": 21,
    "long-term": 90,
}


def detect_urgency(text):
    """Detect urgency levels in text using spaCy lemmas and simple negation handling."""
    doc = nlp(text.lower())
    found = set()
    for level, words in keyword_map.items():
        for token in doc:
            word = token.lemma_
            if word in words:
                negated = any(
                    (t.lemma_ in negations) and abs(t.i - token.i) <= 3
                    for t in doc
                )
                if not negated:
                    found.add(level)
    return sorted(found)


def generate_followup_message(messages):
    """Given a set of messages, create a dictionary with recommended followups."""
    all_message_list = [{'role': 'system', 'content': 'You are a Co-Pilot tool for {}, a peer-peer mental health organization. Please provider 1) A followup message (if applicable) and a followup date (if applicable). Do this in a JSON format: {"follow_up_message": "Hello", "follow_up_date": "2024-01-31"}'}]
    prior_messages = []
    for m in messages:
        prior_messages.append({'role': m['sender'], 'content': m['text']})
    all_message_list += prior_messages
    response = call_chatgpt_api_all_chats(all_message_list, max_tokens=750, stream=False, response_format={"type": "json_object"})
    return json.loads(response)


def load_messages_for_conversation(conversation_id):
    """Loads all messages for a given conversation_id in chronological order."""
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sender, text, created_at FROM messages
        WHERE conversation_id = %s
        ORDER BY created_at ASC
    ''', (conversation_id,))
    messages = cursor.fetchall()
    conn.close()
    return [{"sender": sender, "text": text, "created_at": created_at}
            for sender, text, created_at in messages]


def _get_service_user_info(cursor, service_user_id):
    """Helper: fetch service_user_name and last_session for a given ID."""
    cursor.execute(
        """SELECT p.service_user_name, o.last_session
           FROM profiles p
           LEFT JOIN outreach_details o ON p.service_user_id = o.service_user_id
           WHERE p.service_user_id = %s
             AND o.last_session IS NOT NULL
             AND o.last_session != ''
           ORDER BY o.created_at DESC
           LIMIT 1""",
        (service_user_id,)
    )
    result = cursor.fetchone()
    if result and result[0]:
        return result[0], result[1]

    # Fall back to just the profile name with no last_session
    cursor.execute(
        "SELECT service_user_name FROM profiles WHERE service_user_id = %s",
        (service_user_id,)
    )
    profile = cursor.fetchone()
    if not profile:
        return None, None
    return profile[0], None


def generate_check_ins_gpt(service_user_id: str, conversation_id: str):
    """
    Use GPT to extract specific check-in dates and topics from the conversation,
    then insert them into outreach_details.

    Returns (True, [list of check-in dicts]) or (False, error_message).
    """
    messages = load_messages_for_conversation(conversation_id)
    if not messages:
        return False, "No messages found for this conversation"
    

    conversation_text = "\n".join(
        f"{m['sender'].upper()}: {m['text']}" for m in messages
    )
    print("Generating checkins for messages {}".format(conversation_text))

    today_str = datetime.now().strftime("%Y-%m-%d")
    today_display = datetime.now().strftime("%B %d, %Y")

    system_prompt = f"""You are a scheduling assistant for a peer support platform.
Today's date is {today_display} ({today_str}).

Your job is to read a conversation between a peer support worker and their AI assistant, 
and extract any check-in appointments or follow-up dates that were discussed or implied.

Rules:
- Extract SPECIFIC dates mentioned (e.g. "March 3rd", "next Monday", "in a week").
- Convert relative dates like "next week" or "in 3 days" relative to today ({today_str}).
- For each check-in, produce a short, warm follow-up message relevant to the topic discussed.
- If no specific date is mentioned but a follow-up is clearly implied, schedule one 7 days from today.
- Return ONLY a JSON array. No explanation. No markdown. Example format:
[
  {{
    "check_in_date": "2026-03-03",
    "follow_up_message": "Hey, checking in on how your smoking has been going — how are you feeling about it?"
  }}
]
- If there are truly no check-ins to schedule, return an empty array: []
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5-chat",  # same model as the rest of the app
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here is the conversation:\n\n{conversation_text}"}
            ],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()

        print("Raw response {}".format(raw))

        # GPT sometimes wraps in {"check_ins": [...]} — handle both
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            check_in_list = parsed
        elif isinstance(parsed, dict):
            # Try common wrapper keys
            check_in_list = [parsed]
        else:
            check_in_list = []

    except Exception as e:
        print(f"[GPT CheckIn] Error calling GPT: {e}")
        return False, f"GPT error: {str(e)}"
    print("Check In {}".format(check_in_list))


    if not check_in_list:
        return False, "GPT found no check-ins to schedule in this conversation"



    # Insert into DB
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    try:
        service_user_name, last_session = _get_service_user_info(cursor, service_user_id)
        if not service_user_name:
            return False, "Service user not found"

        last_session_str = last_session if last_session else today_str

        inserted = []
        for item in check_in_list:
            check_in_date = item.get("check_in_date", "").strip()
            message = item.get("follow_up_message", "").strip()

            if not check_in_date:
                continue

            # Validate date format
            try:
                datetime.strptime(check_in_date, "%Y-%m-%d")
            except ValueError:
                print(f"[GPT CheckIn] Skipping invalid date: {check_in_date}")
                continue

            if not message:
                message = f"Hey {service_user_name}, I wanted to check in and see how things are going."

            cursor.execute('''
                INSERT INTO outreach_details
                (service_user_id, last_session, check_in, follow_up_message)
                VALUES (%s, %s, %s, %s)
            ''', (service_user_id, last_session_str, check_in_date, message))

            inserted.append({"date": check_in_date, "message": message})

        conn.commit()
        print(f"[GPT CheckIn] Inserted {len(inserted)} check-ins for {service_user_name}")
        return True, inserted

    except Exception as e:
        conn.rollback()
        print(f"[DB Error] {e}")
        return False, str(e)
    finally:
        conn.close()


# Keep the old rule-based function but point the endpoint to the GPT one above.
# generate_check_ins_rule_based is aliased so the import in all_endpoints.py doesn't need to change.
generate_check_ins_rule_based = generate_check_ins_gpt


def generate_check_ins_standard(service_user_id: str, conversation_summary: str = ""):
    """Generate and insert 3 check-ins at 1, 2, and 3 weeks (fallback / manual trigger)."""
    conn = psycopg.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    try:
        service_user_name, last_session = _get_service_user_info(cursor, service_user_id)
        if not service_user_name:
            return False, "Service user not found"

        base_date = datetime.now()
        if last_session:
            try:
                base_date = datetime.strptime(last_session, "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        last_session_str = base_date.strftime("%Y-%m-%d")

        check_ins = []
        for weeks in [1, 2, 3]:
            check_in_date = base_date + timedelta(weeks=weeks)
            check_in_str = check_in_date.strftime("%Y-%m-%d")
            follow_up = f"Hey {service_user_name}, I wanted to see how things were going"
            cursor.execute('''
                INSERT INTO outreach_details
                (service_user_id, last_session, check_in, follow_up_message)
                VALUES (%s, %s, %s, %s)
            ''', (service_user_id, last_session_str, check_in_str, follow_up))
            check_ins.append({"date": check_in_str, "message": follow_up})

        conn.commit()
        return True, check_ins

    except Exception as e:
        conn.rollback()
        print(f"[DB Error] {e}")
        return False, str(e)
    finally:
        conn.close()