#!/bin/bash

set -e

############################################
# CONFIG
############################################

GITHUB_USERNAME="gillesmich"
GITHUB_EMAIL="gillesmich@yahoo.fr"
REPO_NAME="ai-avatar-lab"

############################################
# CHECK SSH
############################################

if ! ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "❌ SSH not configured"
  exit 1
fi

############################################
# CONFIG GIT
############################################

git config --global user.name "$GITHUB_USERNAME"
git config --global user.email "$GITHUB_EMAIL"

############################################
# IMPORTANT: USE CURRENT DIRECTORY
############################################

echo "== Using current folder =="
pwd

############################################
# ADD .gitignore IF NOT EXISTS
############################################

if [ ! -f ".gitignore" ]; then
cat > .gitignore << 'EOL'
models/
*.pth
*.onnx
*.ckpt
uploads/
outputs/
streams/
.env
__pycache__/
*.pyc
logs/
EOL
fi

############################################
# INIT GIT (if needed)
############################################

if [ ! -d ".git" ]; then
  git init
fi

############################################
# ADD + COMMIT
############################################

git add .

if ! git diff --cached --quiet; then
  git commit -m "Initial commit - existing project"
else
  echo "== No changes to commit =="
fi

git branch -M main 2>/dev/null || true

############################################
# REMOTE
############################################

if git remote | grep -q origin; then
  git remote remove origin
fi

git remote add origin git@github.com:$GITHUB_USERNAME/$REPO_NAME.git

############################################
# PUSH
############################################

set +e
git push -u origin main
STATUS=$?
set -e

if [ $STATUS -ne 0 ]; then
  echo ""
  echo "👉 Create repo manually:"
  echo "https://github.com/new"
  echo "Name: $REPO_NAME"
  read -p "Press ENTER after creating repo..."
  git push -u origin main
fi

echo "✅ DONE: https://github.com/$GITHUB_USERNAME/$REPO_NAME"

