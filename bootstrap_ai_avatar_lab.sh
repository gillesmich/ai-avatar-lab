#!/bin/bash

set -e

############################################
# CONFIG
############################################

GITHUB_USERNAME="gillesmich"
GITHUB_EMAIL="gillesmich@yahoo.fr"
REPO_NAME="ai-avatar-lab"
CONDA_ENV_NAME="ai-avatar"

############################################
# CHECK SSH
############################################

echo "== Checking SSH =="

if ! ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "❌ SSH not configured"
  echo "👉 Run:"
  echo "ssh-keygen -t ed25519 -C \"$GITHUB_EMAIL\""
  echo "👉 Then add key: https://github.com/settings/keys"
  exit 1
fi

echo "✅ SSH OK"

############################################
# CONFIG GIT
############################################

git config --global user.name "$GITHUB_USERNAME"
git config --global user.email "$GITHUB_EMAIL"

############################################
# CREATE / ENTER PROJECT
############################################

mkdir -p $REPO_NAME
cd $REPO_NAME

############################################
# CREATE STRUCTURE (idempotent)
############################################

mkdir -p {wav2lip,liveportrait,infinitetalk,wan2gp,scraper-api,api,shared,docker,scripts}

mkdir -p wav2lip/{app,models,scripts}
mkdir -p liveportrait/{app,models,scripts}
mkdir -p infinitetalk/{app,models,scripts}
mkdir -p wan2gp/{app,models,scripts}
mkdir -p scraper-api/{app,spiders,services}
mkdir -p api/flask_backend

############################################
# FILES (overwrite safe)
############################################

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

cat > README.md << 'EOL'
# AI Avatar Lab

Multi-engine AI avatar system:

- Wav2Lip
- LivePortrait
- InfiniteTalk
- Wan2GP
- Scraper API

## Setup

conda env create -f environment.yml
conda activate ai-avatar
EOL

cat > environment.yml << 'EOL'
name: ai-avatar
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.10
  - pip
  - ffmpeg
  - git
  - pip:
      - flask
      - requests
      - beautifulsoup4
      - numpy
      - torch
      - torchvision
EOL

cat > api/flask_backend/app.py << 'EOL'
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(port=5000)
EOL

############################################
# GIT INIT / UPDATE (idempotent)
############################################

if [ ! -d ".git" ]; then
  echo "== Initializing git =="
  git init
fi

git add .

if ! git diff --cached --quiet; then
  git commit -m "Update - AI Avatar Lab"
else
  echo "== No changes to commit =="
fi

git branch -M main 2>/dev/null || true

############################################
# REMOTE (safe reset)
############################################

if git remote | grep -q origin; then
  git remote remove origin
fi

git remote add origin git@github.com:$GITHUB_USERNAME/$REPO_NAME.git

############################################
# PUSH (with fallback)
############################################

echo "== Pushing to GitHub =="

set +e
git push -u origin main 2>/dev/null
STATUS=$?
set -e

if [ $STATUS -ne 0 ]; then
  echo ""
  echo "⚠️ Repo does not exist"
  echo "👉 Create it here:"
  echo "https://github.com/new"
  echo "Name: $REPO_NAME"
  echo ""
  read -p "Press ENTER when repo is created..."
  git push -u origin main
fi

############################################
# CONDA SETUP (safe)
############################################

echo "== Setting up conda =="

conda env list | grep -q "$CONDA_ENV_NAME" || conda env create -f environment.yml

############################################
# DONE
############################################

echo ""
echo "✅ DONE"
echo "Repo: https://github.com/$GITHUB_USERNAME/$REPO_NAME"
echo ""
echo "Run:"
echo "conda activate $CONDA_ENV_NAME"

