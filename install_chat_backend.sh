#!/bin/bash

TARGET_FILE="chat_backend.py"
BACKUP_FILE="chat_backend.py.bak"

echo "=== CHAT BACKEND INSTALLER ==="

# ================= BACKUP =================

if [ -f "$TARGET_FILE" ]; then
    echo "[INFO] Existing backend detected → Backup created"
    cp "$TARGET_FILE" "$BACKUP_FILE"
else
    echo "[INFO] No existing backend → Fresh install"
fi

# ================= WRITE BACKEND =================

cat > "$TARGET_FILE" << 'EOF'
from openai import OpenAI
from gdrive_memory import GDriveMemory

client = OpenAI()
memory = GDriveMemory()

SYSTEM_PROMPT = "Tu es un assistant utile."

def ask_gpt(user_id, user_message):

    filename = f"chat_memory_{user_id}.json"

    # ================= LOAD MEMORY =================

    conversation = memory.load_conversation(filename)

    if not conversation:
        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # ================= APPEND USER =================

    conversation.append({
        "role": "user",
        "content": user_message
    })

    # ================= GPT CALL =================

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation
    )

    reply = response.choices[0].message.content

    # ================= APPEND ASSISTANT =================

    conversation.append({
        "role": "assistant",
        "content": reply
    })

    # ================= MEMORY LIMIT (SAFE PROD) =================

    conversation = conversation[-20:]

    # ================= SAVE MEMORY =================

    memory.save_conversation(filename, conversation)

    return reply
EOF

echo "[SUCCESS] Backend written → $TARGET_FILE"

# ================= DONE =================

echo "=== INSTALL COMPLETE ==="
echo "Rollback if needed:"
echo "cp $BACKUP_FILE $TARGET_FILE"
