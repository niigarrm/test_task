import json
import os
import psycopg2
from dotenv import load_dotenv
import csv
from collections import Counter
from pathlib import Path
# --- Constants ---
INPUT_PATH = "data/messages.json"
OUTPUT_CSV = "output/classified_messages.csv"
OUTPUT_SUMMARY = "output/summary_report.txt"
CATEGORY_RULES = [
    ("report_request",   ["report", "file", "send again", "document"]),
    ("grant_search",     ["grant", "funding", "deadline", "scholarship"]),
    ("general_question", ["how", "what", "can you", "where", "why"]),
]
DEFAULT_CATEGORY = "unknown"

def load_messages(path):
    """Load messages from a JSON file and return a list of dicts."""
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Could not find {path}")
    
    with open(file, "r", encoding="utf-8") as f:
        messages = json.load(f)
    
    return messages

# --- Classification rules ---
# Order matters: higher priority categories listed first.
# A message is assigned the FIRST category whose keywords match.



def clean_messages(messages):
    """
    Remove invalid messages and normalise whitespace.
    
    A message is invalid if:
      - user_id is missing or blank
      - message is missing or blank (after stripping whitespace)
    """
    cleaned = []
    
    
    for msg in messages:
        # Get fields safely — .get() returns None if key is missing
        user_id = msg.get("user_id")
        text = msg.get("message")
        
        # Skip if user_id is missing, not a string, or blank
        if not isinstance(user_id, str) or not user_id.strip():
            continue
        
        # Skip if message is missing, not a string, or blank after stripping
        if not isinstance(text, str) or not text.strip():
            continue
        
        # Build a clean copy with stripped fields
        cleaned_msg = {
            "user_id": user_id.strip(),
            "message": text.strip(),
            "created_at": msg.get("created_at"),
            "channel": msg.get("channel"),
        }
        
        cleaned.append(cleaned_msg)
    
    return cleaned

def classify_one(text):
    """
    Classify a single message into one category.
    
    Uses substring matching, case-insensitive. The first rule whose
    keywords appear in the message wins (priority order).
    """
    lowered = text.lower()
    
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in lowered:
                return category
    
    return DEFAULT_CATEGORY

def classify_messages(messages):
    """Add a 'category' field to each message based on classify_one."""
    classified = []
    for msg in messages:
        new_msg = dict(msg)  # copy, don't mutate input
        new_msg["category"] = classify_one(msg["message"])
        classified.append(new_msg)
    return classified

def save_to_csv(messages, path):
    """Write classified messages to a CSV file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    fieldnames = ["user_id", "message", "created_at", "channel", "category"]
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(messages)

def generate_summary(messages):
    """Build a human-readable summary report as a string."""
    total = len(messages)
    
    by_category = Counter(m["category"] for m in messages)
    by_channel  = Counter(m["channel"]  for m in messages)
    by_user     = Counter(m["user_id"]  for m in messages)
    
    lines = []
    lines.append("=" * 50)
    lines.append("MESSAGE CLASSIFICATION SUMMARY")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Total valid messages: {total}")
    lines.append("")
    
    lines.append("Messages per category:")
    for category, count in by_category.most_common():
        lines.append(f"  {category:18} {count}")
    lines.append("")
    
    lines.append("Messages per channel:")
    for channel, count in by_channel.most_common():
        lines.append(f"  {channel:18} {count}")
    lines.append("")
    
    lines.append("Messages per user:")
    for user_id, count in by_user.most_common():
        lines.append(f"  {user_id:18} {count}")
    
    return "\n".join(lines)

def save_summary(summary, path):
    """Write a summary string to a text file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(summary)

def get_db_connection():
    """Return a connection to Postgres using credentials from environment variables."""
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )

def save_to_postgres(messages):
    """Create the table if needed, then replace all data with the given messages."""
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS classified_messages (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            channel VARCHAR(50) NOT NULL,
            category VARCHAR(50) NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    
    insert_sql = """
        INSERT INTO classified_messages
            (user_id, message, created_at, channel, category)
        VALUES (%s, %s, %s, %s, %s);
    """
    
    rows = [
        (m["user_id"], m["message"], m["created_at"], m["channel"], m["category"])
        for m in messages
    ]
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(create_table_sql)
            cur.execute("TRUNCATE classified_messages RESTART IDENTITY;")
            cur.executemany(insert_sql, rows)
        conn.commit()
    finally:
        conn.close()

def main():
    """Run the full pipeline: load, clean, classify, save."""
    load_dotenv()
    
    messages = load_messages(INPUT_PATH)
    print(f"Loaded {len(messages)} messages")
    
    cleaned = clean_messages(messages)
    print(f"After cleaning: {len(cleaned)} messages")
    
    classified = classify_messages(cleaned)
    
    save_to_csv(classified, OUTPUT_CSV)
    print(f"Wrote CSV to {OUTPUT_CSV}")
    
    summary = generate_summary(classified)
    save_summary(summary, OUTPUT_SUMMARY)
    print(f"Wrote summary to {OUTPUT_SUMMARY}")
    
    try:
        save_to_postgres(classified)
        print(f"Saved {len(classified)} rows to Postgres")
    except Exception as e:
        print(f"Skipped Postgres step: {e}")


if __name__ == "__main__":
    main()
