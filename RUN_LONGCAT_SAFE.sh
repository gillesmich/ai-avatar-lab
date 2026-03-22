#!/bin/bash

echo "🧹 Nettoyage GPU / Processus..."

pkill -9 -f longcat 2>/dev/null
pkill -9 -f compile_worker 2>/dev/null

sleep 2

echo "✅ VRAM après nettoyage :"
nvidia-smi --query-gpu=memory.used --format=csv

echo ""
echo "🧠 Configuration CUDA SAFE..."

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo ""
echo "🚀 Lancement LongCat SAFE MODE..."
cd /workspace/LongCat-Video

torchrun --nproc_per_node=1 run_demo_avatar_single_audio_to_video.py \
  --checkpoint_dir ./weights/LongCat-Video-Avatar \
  --stage_1 ai2v \
  --input_json /tmp/avatar_input.json \
  --resolution 480p \
  --num_segments 1 \
  --num_inference_steps 10 \
  --ref_img_index 0 \
  --mask_frame_range 0 \
  --text_guidance_scale 1.0 \
  --audio_guidance_scale 1.0

echo ""
echo "🏁 Fin du run"
