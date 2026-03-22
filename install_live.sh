#!/bin/bash
set -e

INSTALL_DIR="/workspace/LivePortrait"
CONDA_ENV="liveportrait"

echo "=== Clone LivePortrait ==="
cd /workspace
git clone https://github.com/KwaiVGI/LivePortrait.git
cd "$INSTALL_DIR"

echo "=== Création env conda Python 3.10 ==="
conda create -n "$CONDA_ENV" python=3.10 -y
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

echo "=== Install PyTorch CUDA 11.8 ==="
pip install torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 \
  --index-url https://download.pytorch.org/whl/cu118

echo "=== Install dépendances ==="
pip install -r requirements.txt

echo "=== Téléchargement poids via HuggingFace ==="
# git lfs requis
apt-get install -y git-lfs 2>/dev/null || yum install -y git-lfs 2>/dev/null || true
git lfs install
git clone https://huggingface.co/KwaiVGI/liveportrait pretrained_weights

echo "=== Test rapide avec les exemples fournis ==="
python inference.py \
  -s assets/examples/source/s9.jpg \
  -d assets/examples/driving/d0.mp4 \
  -o animations/test_output.mp4

echo ""
echo "=== Installation terminée ==="
echo "Résultat test : $INSTALL_DIR/animations/test_output.mp4"
echo ""
echo "Usage idle Maya :"
echo "  conda activate $CONDA_ENV"
echo "  cd $INSTALL_DIR"
echo "  python inference.py -s maya.jpg -d driver_idle.mp4 --flag_crop_driving_video -o maya_idle.mp4"
