#!/bin/bash

TARGET_FILE="gdrive_memory.py"
BACKUP_FILE="gdrive_memory.py.bak"

echo "=== GDRIVE MEMORY MODULE INSTALLER ==="

# ================= BACKUP =================

if [ -f "$TARGET_FILE" ]; then
    echo "[INFO] Existing file detected → Backup created"
    cp "$TARGET_FILE" "$BACKUP_FILE"
else
    echo "[INFO] No existing file → Fresh install"
fi

# ================= WRITE MODULE =================

cat > "$TARGET_FILE" << 'EOF'
import io
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'

class GDriveMemory:

    def __init__(self, folder_id=None):
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        self.service = build('drive', 'v3', credentials=credentials)
        self.folder_id = folder_id

    def _find_file(self, filename):
        query = f"name='{filename}' and trashed=false"

        if self.folder_id:
            query += f" and '{self.folder_id}' in parents"

        results = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])
        return files[0] if files else None

    def load_conversation(self, filename):

        file = self._find_file(filename)

        if not file:
            return None

        request = self.service.files().get_media(fileId=file['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)

        return json.loads(fh.read().decode())

    def save_conversation(self, filename, conversation):

        file = self._find_file(filename)

        json_data = json.dumps(conversation, indent=2)
        fh = io.BytesIO(json_data.encode())

        media = MediaIoBaseUpload(fh, mimetype='application/json')

        if file:
            self.service.files().update(
                fileId=file['id'],
                media_body=media
            ).execute()
        else:
            metadata = {'name': filename}

            if self.folder_id:
                metadata['parents'] = [self.folder_id]

            self.service.files().create(
                body=metadata,
                media_body=media
            ).execute()

    def append_message(self, filename, role, content):

        conversation = self.load_conversation(filename)

        if not conversation:
            conversation = [
                {"role": "system", "content": "Tu es un assistant utile."}
            ]

        conversation.append({
            "role": role,
            "content": content
        })

        self.save_conversation(filename, conversation)

        return conversation
EOF

echo "[SUCCESS] Module written → $TARGET_FILE"

# ================= DONE =================

echo "=== INSTALL COMPLETE ==="
echo "Rollback if needed:"
echo "cp $BACKUP_FILE $TARGET_FILE"
