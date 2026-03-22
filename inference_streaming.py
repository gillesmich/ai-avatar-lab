from dotenv import load_dotenv
from pathlib import Path as _Path
load_dotenv(_Path(__file__).parent / '.env')
import os
import sys
import subprocess
import platform
import numpy as np
import cv2
import argparse
import audio
import shutil
import librosa
from os import listdir, path
from tqdm import tqdm
from PIL import Image
from scipy.io.wavfile import write
import gc
import time

import onnxruntime
onnxruntime.set_default_logger_severity(3)

from utils.retinaface import RetinaFace
from utils.face_alignment import get_cropped_head_256
detector = RetinaFace("utils/scrfd_2.5g_bnkps.onnx", provider=[("CUDAExecutionProvider", {"cudnn_conv_algo_search": "DEFAULT"}), "CPUExecutionProvider"], session_options=None)

from faceID.faceID import FaceRecognition
recognition = FaceRecognition('faceID/recognition.onnx')

parser = argparse.ArgumentParser(description='Inference code to lip-sync videos in the wild using Wav2Lip models')

parser.add_argument('--checkpoint_path', type=str, help='Name of saved checkpoint to load weights from', required=True)
parser.add_argument('--face', type=str, help='Filepath of video/image that contains faces to use', required=True)
parser.add_argument('--audio', type=str, help='Filepath of video/audio file to use as raw audio source', required=True)
parser.add_argument('--denoise', default=False, action="store_true", help="Denoise input audio to avoid unwanted lipmovement")
parser.add_argument('--outfile', type=str, help='Video path to save result. See default for an e.g.', default='results/result_voice.mp4')
parser.add_argument('--hq_output', default=False, action='store_true', help='HQ output')
parser.add_argument('--static', default=False, action='store_true', help='If True, then use only first video frame for inference')
parser.add_argument('--pingpong', default=False, action='store_true', help='pingpong loop if audio is longer than video')
parser.add_argument('--cut_in', type=int, default=0, help="Frame to start inference")
parser.add_argument('--cut_out', type=int, default=0, help="Frame to end inference")
parser.add_argument('--fade', action="store_true", help="Fade in/out")
parser.add_argument('--fps', type=float, help='Can be specified only if input is a static image (default: 25)', default=25., required=False)
parser.add_argument('--resize_factor', default=1, type=int, help='Reduce the resolution by this factor. Sometimes, best results are obtained at 480p or 720p')
parser.add_argument('--enhancer', default='none', choices=['none', 'gpen', 'gfpgan', 'codeformer', 'restoreformer'])
parser.add_argument('--blending', default=10, type=float, help='Amount of face enhancement blending 1 - 10')
parser.add_argument('--sharpen', default=False, action="store_true", help="Slightly sharpen swapped face")
parser.add_argument('--frame_enhancer', action="store_true", help="Use frame enhancer")
parser.add_argument('--face_mask', action="store_true", help="Use face mask")
parser.add_argument('--face_occluder', action="store_true", help="Use x-seg occluder face mask")
parser.add_argument('--pads', type=int, default=4, help='Padding top, bottom to adjust best mouth position, move crop up/down, between -15 to 15')
parser.add_argument('--face_mode', type=int, default=0, help='Face crop mode, 0 or 1, rect or square, affects mouth opening')
parser.add_argument('--preview', default=False, action='store_true', help='Preview during inference')
parser.add_argument('--stream_dir', type=str, help='Directory to save preview frames for streaming')
parser.add_argument('--stream_interval', type=int, default=int(os.environ.get('STREAM_INTERVAL','125')), help='Save preview frame every N frames (default: 125 = ~5sec at 25fps)')
parser.add_argument('--cached_frames', type=str, default=None,
                    help='Path to .npz file with pre-computed frames+faces cache (skip video read & face_detect)')
parser.add_argument('--batch_size', type=int, default=16,
                    help='Batch size ONNX inference (défaut: 16)')

args = parser.parse_args()

if args.checkpoint_path == 'checkpoints\\wav2lip_384.onnx' or args.checkpoint_path == 'checkpoints\\wav2lip_384_fp16.onnx':
    args.img_size = 384
else:
    args.img_size = 96

mel_step_size = 16
padY = max(-15, min(args.pads, 15))

device = 'cpu'
if onnxruntime.get_device() == 'GPU':
    device = 'cuda'
print("Running on " + device)


if args.enhancer == 'gpen':
    from enhancers.GPEN.GPEN import GPEN
    enhancer = GPEN(model_path="enhancers/GPEN/GPEN-BFR-256-sim.onnx", device=device)

if args.enhancer == 'codeformer':
    from enhancers.Codeformer.Codeformer import CodeFormer
    enhancer = CodeFormer(model_path="enhancers/Codeformer/weights/codeformer.pth", device=device)

if args.enhancer == 'restoreformer':
    from enhancers.restoreformer.restoreformer16 import RestoreFormer
    enhancer = RestoreFormer(model_path="enhancers/restoreformer/restoreformer16.onnx", device=device)

if args.enhancer == 'gfpgan':
    from enhancers.GFPGAN.GFPGAN import GFPGAN
    enhancer = GFPGAN(model_path="enhancers/GFPGAN/GFPGANv1.4.onnx", device=device)

if args.frame_enhancer:
    from enhancers.RealEsrgan.esrganONNX import RealESRGAN_ONNX
    frame_enhancer = RealESRGAN_ONNX(model_path="enhancers/RealEsrgan/clear_reality_x4.onnx", device=device)

if args.face_mask:
    from blendmasker.blendmask import BLENDMASK
    masker = BLENDMASK(model_path="blendmasker/blendmasker.onnx", device=device)

if args.face_occluder:
    from xseg.xseg import MASK
    occluder = MASK(model_path="xseg/xseg.onnx", device=device)

if args.denoise:
    from resemble_denoiser.resemble_denoiser import ResembleDenoiser
    denoiser = ResembleDenoiser(model_path='resemble_denoiser/denoiser.onnx', device=device)

if os.path.isfile(args.face) and args.face.split('.')[1] in ['jpg', 'png', 'jpeg']:
    args.static = True


def load_model(device):
    model_path = args.checkpoint_path
    session_options = onnxruntime.SessionOptions()
    session_options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    # A100 : laisser ONNX gérer les threads (ne pas limiter à 1)
    session_options.intra_op_num_threads = 0
    session_options.inter_op_num_threads = 0
    providers = ["CPUExecutionProvider"]
    if device == 'cuda':
        providers = [
            ("CUDAExecutionProvider", {
                "cudnn_conv_algo_search": "EXHAUSTIVE",  # plus lent 1er run, puis optimal
                "do_copy_in_default_stream": True,
                "arena_extend_strategy": "kNextPowerOfTwo",
            }),
            "CPUExecutionProvider"
        ]
    session = onnxruntime.InferenceSession(model_path, sess_options=session_options, providers=providers)
    print(f"[onnx] Providers actifs: {session.get_providers()}", flush=True)
    return session


def select_specific_face(model, spec_img, size, crop_scale=1.0):
    print("Headless mode - Auto-selecting first detected face")
    bboxes, kpss = model.detect(spec_img, input_size=(320, 320), det_thresh=0.3)
    if len(kpss) == 0:
        raise ValueError("No face detected in the input image/frame")
    print(f"Found {len(kpss)} face(s), selecting face #0")
    target_face, mat = get_cropped_head_256(spec_img, kpss[0], size=size, scale=crop_scale)
    target_face = cv2.resize(target_face, (112, 112))
    target_id = recognition(target_face)[0].flatten()
    return target_id


def process_video_specific(model, img, size, target_id, crop_scale=1.0):
    ori_img = img
    bboxes, kpss = model.detect(ori_img, input_size=(320, 320), det_thresh=0.3)
    assert len(kpss) != 0, "No face detected"
    best_score = -float('inf')
    best_aimg = None
    best_mat = None
    for kps in kpss:
        aimg, mat = get_cropped_head_256(ori_img, kps, size=size, scale=crop_scale)
        face = aimg.copy()
        face = cv2.resize(face, (112, 112))
        face_id = recognition(face)[0].flatten()
        score = target_id @ face_id
        if score > best_score:
            best_score = score
            best_aimg = aimg
            best_mat = mat
        if best_score < 0.4:
            best_aimg = np.zeros((256, 256), dtype=np.uint8)
            best_aimg = cv2.cvtColor(best_aimg, cv2.COLOR_GRAY2RGB) / 255
            best_mat = np.float32([[1, 2, 3], [1, 2, 3]])
    return best_aimg, best_mat


def face_detect(images, target_id):
    os.system('clear' if platform.system() != 'Windows' else 'cls')
    print("Detecting face and generating data...")
    sub_faces = []
    crop_faces = []
    matrix = []
    face_error = []
    for i in tqdm(range(0, len(images))):
        try:
            crop_face, M = process_video_specific(detector, images[i], 256, target_id, crop_scale=1.0)
            if args.face_mode == 0:
                sub_face = crop_face[65 - (padY):241 - (padY), 62:194]
            else:
                sub_face = crop_face[65 - (padY):241 - (padY), 42:214]
            sub_face = cv2.resize(sub_face, (args.img_size, args.img_size))
            sub_faces.append(sub_face)
            crop_faces.append(crop_face)
            matrix.append(M)
            no_face = 0
        except:
            if i == 0:
                crop_face = np.zeros((256, 256), dtype=np.uint8)
                crop_face = cv2.cvtColor(crop_face, cv2.COLOR_GRAY2RGB) / 255
                sub_face = crop_face[65 - (padY):241 - (padY), 62:194]
                sub_face = cv2.resize(sub_face, (args.img_size, args.img_size))
                M = np.float32([[1, 2, 3], [1, 2, 3]])
            sub_faces.append(sub_face)
            crop_faces.append(crop_face)
            matrix.append(M)
            no_face = -1
        face_error.append(no_face)
    return crop_faces, sub_faces, matrix, face_error


def datagen(frames, mels):
    img_batch, mel_batch, frame_batch = [], [], []
    for i, m in enumerate(mels):
        idx = 0 if args.static else i % len(frames)
        frame_to_save = frames[idx].copy()
        frame_batch.append(frame_to_save)
        img_batch.append(frames[idx])
        mel_batch.append(m)
        if len(img_batch) >= args.batch_size:
            img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)
            img_masked = img_batch.copy()
            img_masked[:, args.img_size // 2:] = 0
            img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
            mel_batch = np.reshape(mel_batch, [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1])
            yield img_batch, mel_batch, frame_batch
            img_batch, mel_batch, frame_batch = [], [], []
    # flush dernier batch incomplet
    if img_batch:
        img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)
        img_masked = img_batch.copy()
        img_masked[:, args.img_size // 2:] = 0
        img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
        mel_batch = np.reshape(mel_batch, [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1])
        yield img_batch, mel_batch, frame_batch


def main():
    if not os.path.exists('temp'):
        os.makedirs('temp')
    stream_frame_count = 0
    if args.stream_dir:
        os.makedirs(args.stream_dir, exist_ok=True)
        for f in os.listdir(args.stream_dir):
            if f.endswith('.jpg') or f == 'preview.jpg':
                os.remove(os.path.join(args.stream_dir, f))
        print(f"Streaming frames to: {args.stream_dir}")
    if args.hq_output:
        if not os.path.exists('hq_temp'):
            os.mkdir('hq_temp')
    blend = args.blending / 10
    static_face_mask = np.zeros((224, 224), dtype=np.uint8)
    static_face_mask = cv2.ellipse(static_face_mask, (112, 162), (62, 54), 0, 0, 360, (255, 255, 255), -1)
    static_face_mask = cv2.ellipse(static_face_mask, (112, 122), (46, 23), 0, 0, 360, (0, 0, 0), -1)
    static_face_mask = cv2.resize(static_face_mask, (256, 256))
    static_face_mask = cv2.rectangle(static_face_mask, (0, 246), (246, 246), (0, 0, 0), -1)
    static_face_mask = cv2.cvtColor(static_face_mask, cv2.COLOR_GRAY2RGB) / 255
    static_face_mask = cv2.GaussianBlur(static_face_mask, (19, 19), cv2.BORDER_DEFAULT)
    sub_face_mask = np.zeros((256, 256), dtype=np.uint8)
    sub_face_mask = cv2.rectangle(sub_face_mask, (42, 65 - padY), (214, 249), (255, 255, 255), -1)
    sub_face_mask = cv2.GaussianBlur(sub_face_mask.astype(np.uint8), (29, 29), cv2.BORDER_DEFAULT)
    sub_face_mask = cv2.cvtColor(sub_face_mask, cv2.COLOR_GRAY2RGB)
    sub_face_mask = sub_face_mask / 255
    if not os.path.isfile(args.face):
        raise ValueError('--face argument must be a valid path to video/image file')
    elif args.face.split('.')[1] in ['jpg', 'png', 'jpeg', 'bmp']:
        orig_frame = cv2.imread(args.face)
        orig_frame = cv2.resize(orig_frame, (orig_frame.shape[1] // args.resize_factor, orig_frame.shape[0] // args.resize_factor))
        orig_frames = [orig_frame]
        fps = args.fps
        h, w = orig_frame.shape[:-1]
        cropped_roi = orig_frame
        full_frames = [cropped_roi]
        orig_h, orig_w = cropped_roi.shape[:-1]
        target_id = select_specific_face(detector, cropped_roi, 256, crop_scale=1)
    elif args.cached_frames and os.path.isfile(args.cached_frames):
        # ── CACHE HIT : charge frames + face_detect pré-calculés ──────────────
        print(f'[CACHE] Chargement depuis {args.cached_frames}...')
        t_cache = time.time()
        cache = np.load(args.cached_frames, allow_pickle=True)
        full_frames  = list(cache['full_frames'])    # frames BGR originales
        orig_frames  = list(cache['orig_frames'])
        aligned_faces= list(cache['aligned_faces'])
        sub_faces    = list(cache['sub_faces'])
        matrix       = list(cache['matrix'])
        no_face      = list(cache['no_face'])
        fps          = float(cache['fps'])
        orig_h, orig_w = int(cache['orig_h']), int(cache['orig_w'])
        print(f'[CACHE] {len(full_frames)} frames chargées en {time.time()-t_cache:.2f}s (skip VideoCapture + face_detect)')
        # Recalcule les dimensions locales
        h, w = full_frames[0].shape[:-1]
        _cache_loaded = True
    else:
        _cache_loaded = False
        video_stream = cv2.VideoCapture(args.face)
        fps = video_stream.get(cv2.CAP_PROP_FPS)
        video_stream.set(1, args.cut_in)
        print('Reading video frames...')
        if args.cut_out == 0:
            args.cut_out = int(video_stream.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = int(video_stream.get(cv2.CAP_PROP_FRAME_COUNT)) - args.cut_in
        new_duration = args.cut_out - args.cut_in
        if args.static:
            new_duration = 1
        video_stream.set(1, args.cut_in)
        full_frames = []
        orig_frames = []
        for l in range(new_duration):
            still_reading, frame = video_stream.read()
            if not still_reading:
                video_stream.release()
                break
            if args.resize_factor > 1:
                frame = cv2.resize(frame, (frame.shape[1] // args.resize_factor, frame.shape[0] // args.resize_factor))
            if l == 0:
                h, w = frame.shape[:-1]
                cropped_roi = frame
                os.system('clear' if platform.system() != 'Windows' else 'cls')
                target_id = select_specific_face(detector, cropped_roi, 256, crop_scale=1)
                orig_h, orig_w = cropped_roi.shape[:-1]
                print("Reading frames....")
            print(f'\r{l}', end=' ', flush=True)
            full_frames.append(frame)
            orig_frames.append(frame)
    memory_usage_bytes = sum(frame.nbytes for frame in full_frames)
    memory_usage_mb = memory_usage_bytes / (1024 ** 2)
    print("Number of frames used for inference: " + str(len(full_frames)) + " / ~ " + str(int(memory_usage_mb)) + " mb memory usage")
    print('Extracting raw audio...')
    subprocess.run(['ffmpeg', '-y', '-i', args.audio, '-ac', '1', '-strict', '-2', 'temp/temp.wav'])
    os.system('clear' if platform.system() != 'Windows' else 'cls')
    print('Raw audio extracted')
    if args.denoise:
        print('Denoising audio...')
        wav, sr = librosa.load('temp/temp.wav', sr=int(os.environ.get('AUDIO_SAMPLE_RATE','44100')), mono=True)
        wav_denoised, new_sr = denoiser.denoise(wav, sr, batch_process_chunks=False)
        write('temp/temp.wav', new_sr, (wav_denoised * 32767).astype(np.int16))
        try:
            if hasattr(denoiser, 'session'):
                del denoiser.session
                gc.collect()
        except:
            pass
    wav = audio.load_wav('temp/temp.wav', 16000)
    mel = audio.melspectrogram(wav)
    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise ValueError('Mel contains nan! Using a TTS voice? Add a small epsilon noise to the wav file and try again')
    mel_chunks = []
    mel_idx_multiplier = 80. / fps
    i = 0
    while 1:
        start_idx = int(i * mel_idx_multiplier)
        if start_idx + mel_step_size > len(mel[0]):
            mel_chunks.append(mel[:, len(mel[0]) - mel_step_size:])
            break
        mel_chunks.append(mel[:, start_idx: start_idx + mel_step_size])
        i += 1
    print("Length of mel chunks: {}".format(len(mel_chunks)))
    full_frames = full_frames[:len(mel_chunks)]

    # ── face_detect : skipper si cache, sinon exécuter et sauvegarder ─────────
    if args.cached_frames and os.path.isfile(args.cached_frames):
        # Tronquer les listes cachées à la bonne longueur mel_chunks
        aligned_faces = aligned_faces[:len(mel_chunks)]
        sub_faces     = sub_faces[:len(mel_chunks)]
        matrix        = matrix[:len(mel_chunks)]
        no_face       = no_face[:len(mel_chunks)]
        orig_frames   = orig_frames[:len(mel_chunks)]
        print(f'[CACHE] face_detect skippé — {len(sub_faces)} faces utilisées')
    else:
        aligned_faces, sub_faces, matrix, no_face = face_detect(full_frames, target_id)
        # Sauvegarder le cache pour les prochains chunks
        cache_path = args.cached_frames if args.cached_frames else None
        if cache_path:
            print(f'[CACHE] Sauvegarde cache → {cache_path}')
            np.savez_compressed(
                cache_path,
                full_frames   = np.array(full_frames),
                orig_frames   = np.array(orig_frames),
                aligned_faces = np.array(aligned_faces),
                sub_faces     = np.array(sub_faces),
                matrix        = np.array(matrix),
                no_face       = np.array(no_face),
                fps           = np.array(fps),
                orig_h        = np.array(orig_h),
                orig_w        = np.array(orig_w),
            )
            print(f'[CACHE] Sauvegardé ({len(full_frames)} frames)')
    if args.pingpong:
        orig_frames = orig_frames + orig_frames[::-1]
        full_frames = full_frames + full_frames[::-1]
        aligned_faces = aligned_faces + aligned_faces[::-1]
        sub_faces = sub_faces + sub_faces[::-1]
        matrix = matrix + matrix[::-1]
        no_face = no_face + no_face[::-1]
    import time as _time
    _t_start = _time.time()
    gen = datagen(sub_faces.copy(), mel_chunks)
    fc = 0
    model = load_model(device)
    frame_h, frame_w = full_frames[0].shape[:-1]
    out = cv2.VideoWriter('temp/temp.mp4', cv2.VideoWriter_fourcc(*'mp4v'), fps, (orig_w, orig_h))
    os.system('clear' if platform.system() != 'Windows' else 'cls')
    print('Running on ' + onnxruntime.get_device())
    print('Checkpoint: ' + args.checkpoint_path)
    print('Resize factor: ' + str(args.resize_factor))
    if args.pingpong:
        print('Use pingpong')
    if args.enhancer != 'none':
        print('Use ' + args.enhancer)
    if args.face_mask:
        print('Use face mask')
    if args.face_occluder:
        print('Use occlusion mask')
    print('')
    fade_in = 11
    total_length = int(np.ceil(float(len(mel_chunks))))
    fade_out = total_length - 11
    for i, (img_batch, mel_batch, frames) in enumerate(tqdm(gen, total=int(np.ceil(float(len(mel_chunks) / args.batch_size))))):
        img_batch = img_batch.transpose((0, 3, 1, 2)).astype(np.float32)
        mel_batch = mel_batch.transpose((0, 3, 1, 2)).astype(np.float32)
        preds = model.run(None, {'mel_spectrogram': mel_batch, 'video_frames': img_batch})[0]
        for bi, (pred, f) in enumerate(zip(preds, frames)):
            if fc == len(full_frames):
                fc = 0
            face_err = no_face[fc]
            pred = pred.transpose(1, 2, 0) * 255
            pred = pred.astype(np.uint8)
            mat = matrix[fc]
            mat_rev = cv2.invertAffineTransform(mat)
            aligned_face = aligned_faces[fc]
            aligned_face_orig = aligned_face.copy()
            p_aligned = aligned_face.copy()
            full_frame = full_frames[fc]
            if not args.static:
                fc = fc + 1
            if args.face_mode == 0:
                pred = cv2.resize(pred, (132, 176))
            else:
                pred = cv2.resize(pred, (172, 176))
            if args.face_mode == 0:
                p_aligned[65 - (padY):241 - (padY), 62:194] = pred
            else:
                p_aligned[65 - (padY):241 - (padY), 42:214] = pred
            aligned_face = (sub_face_mask * p_aligned + (1 - sub_face_mask) * aligned_face_orig).astype(np.uint8)
            if face_err != 0:
                res = full_frame
                face_err = 0
            else:
                if args.enhancer != 'none':
                    aligned_face_enhanced = enhancer.enhance(aligned_face)
                    aligned_face_enhanced = cv2.resize(aligned_face_enhanced, (256, 256))
                    aligned_face = cv2.addWeighted(aligned_face_enhanced.astype(np.float32), blend, aligned_face.astype(np.float32), 1. - blend, 0.0)
                if args.face_mask:
                    seg_mask = masker.mask(aligned_face)
                    seg_mask = cv2.blur(seg_mask, (5, 5))
                    seg_mask = seg_mask / 255
                    mask = cv2.warpAffine(seg_mask, mat_rev, (frame_w, frame_h))
                if args.face_occluder:
                    try:
                        seg_mask = occluder.mask(aligned_face_orig)
                        seg_mask = cv2.cvtColor(seg_mask, cv2.COLOR_GRAY2RGB)
                        mask = cv2.warpAffine(seg_mask, mat_rev, (frame_w, frame_h))
                    except:
                        seg_mask = occluder.mask(aligned_face)
                        seg_mask = cv2.cvtColor(seg_mask, cv2.COLOR_GRAY2RGB)
                        mask = cv2.warpAffine(seg_mask, mat_rev, (frame_w, frame_h))
                if not args.face_mask and not args.face_occluder:
                    mask = cv2.warpAffine(static_face_mask, mat_rev, (frame_w, frame_h))
                if args.sharpen:
                    aligned_face = cv2.detailEnhance(aligned_face, sigma_s=1.3, sigma_r=0.15)
                dealigned_face = cv2.warpAffine(aligned_face, mat_rev, (frame_w, frame_h))
                res = (mask * dealigned_face + (1 - mask) * full_frame).astype(np.uint8)
            final = res
            frame_idx = i * args.batch_size + bi
            if args.frame_enhancer:
                final = frame_enhancer.enhance(final)
                final = cv2.resize(final, (orig_w, orig_h), interpolation=cv2.INTER_AREA)
            if frame_idx < 11 and args.fade:
                final = cv2.convertScaleAbs(final, alpha=0 + (0.1 * (frame_idx)), beta=0)
            if frame_idx > fade_out and args.fade:
                final = cv2.convertScaleAbs(final, alpha=1 - (0.1 * (frame_idx - fade_out)), beta=0)
            if args.hq_output:
                cv2.imwrite(os.path.join('./hq_temp', '{:0>7d}.png'.format(frame_idx)), final)
            else:
                out.write(final)
            if args.stream_dir and frame_idx % args.stream_interval == 0:
                preview_path = os.path.join(args.stream_dir, 'preview.jpg')
                _pw = int(os.environ.get('STREAM_PREVIEW_WIDTH','480'))
                _ph = int(os.environ.get('STREAM_PREVIEW_HEIGHT','270'))
                preview_frame = cv2.resize(final, (_pw, _ph))
                cv2.imwrite(preview_path, preview_frame, [cv2.IMWRITE_JPEG_QUALITY, int(os.environ.get('STREAM_JPEG_QUALITY','85'))])
                numbered_path = os.path.join(args.stream_dir, f'frame_{stream_frame_count:04d}.jpg')
                cv2.imwrite(numbered_path, preview_frame, [cv2.IMWRITE_JPEG_QUALITY, int(os.environ.get('STREAM_JPEG_QUALITY','85'))])
                stream_frame_count += 1
    out.release()
    print(f'[perf] inference: {_time.time()-_t_start:.1f}s ({len(mel_chunks)} frames)', flush=True)
    if args.hq_output:
        command = (
            f'ffmpeg -y -i "{args.audio}" -r {fps} -f image2'
            f' -i "./hq_temp/%07d.png" -shortest'
            f' -vcodec {os.environ.get("FFMPEG_CODEC","libx264")}'
            f' -pix_fmt {os.environ.get("FFMPEG_PIX_FMT","yuv420p")}'
            f' -crf {os.environ.get("FFMPEG_HQ_CRF","5")}'
            f' -preset {os.environ.get("FFMPEG_HQ_PRESET","faster")}'
            f' -acodec {os.environ.get("FFMPEG_AUDIO_CODEC","aac")}'
            f' -ac {os.environ.get("FFMPEG_AUDIO_CHANNELS","2")}'
            f' -ar {os.environ.get("FFMPEG_AUDIO_RATE","44100")}'
            f' -ab {os.environ.get("FFMPEG_AUDIO_BITRATE","128000")}'
            f' -strict -2 "{args.outfile}"'
        )
    else:
        command = (
            f'ffmpeg -y -i "{args.audio}" -i temp/temp.mp4 -shortest'
            f' -vcodec {os.environ.get("FFMPEG_CODEC","libx264")}'
            f' -pix_fmt {os.environ.get("FFMPEG_PIX_FMT","yuv420p")}'
            f' -profile:v baseline -level 3.0 -movflags +faststart'
            f' -crf {os.environ.get("FFMPEG_CRF","18")}'
            f' -preset {os.environ.get("FFMPEG_PRESET","faster")}'
            f' -acodec {os.environ.get("FFMPEG_AUDIO_CODEC","aac")}'
            f' -ac {os.environ.get("FFMPEG_AUDIO_CHANNELS","2")}'
            f' -ar {os.environ.get("FFMPEG_AUDIO_RATE","44100")}'
            f' -ab {os.environ.get("FFMPEG_AUDIO_BITRATE","128000")}'
            f' -strict -2 "{args.outfile}"'
        )
    subprocess.call(command, shell=platform.system() != 'Windows')
    if os.path.exists('temp/temp.mp4'):
        os.remove('temp/temp.mp4')
    if os.path.exists('temp/temp.wav'):
        os.remove('temp/temp.wav')
    if os.path.exists('hq_temp'):
        shutil.rmtree('hq_temp')


if __name__ == '__main__':
    main()

# ===============================
# CodeFormer enhancer
# ===============================

import torch
import sys

CODEFORMER_PATH = "/workspace/wav2lip-onnx-HQ/enhancers/CodeFormer"
sys.path.append(CODEFORMER_PATH)

codeformer_model = None

def load_codeformer():
    global codeformer_model
    if codeformer_model is not None:
        return codeformer_model

    try:
        from basicsr.archs.codeformer_arch import CodeFormer

        device = "cuda" if torch.cuda.is_available() else "cpu"

        model = CodeFormer(
            dim_embd=512,
            codebook_size=1024,
            n_head=8,
            n_layers=9,
            connect_list=['32','64','128','256']
        ).to(device)

        ckpt = torch.load(
            CODEFORMER_PATH + "/weights/codeformer.pth",
            map_location=device
        )

        model.load_state_dict(ckpt["params_ema"])
        model.eval()

        codeformer_model = model

        print("CodeFormer enhancer loaded")

        return model

    except Exception as e:
        print("CodeFormer load failed:", e)
        return None


def enhance_with_codeformer(frame):

    model = load_codeformer()

    if model is None:
        return frame

    device = "cuda" if torch.cuda.is_available() else "cpu"

    img = frame.astype("float32") / 255.0
    img = torch.from_numpy(img).permute(2,0,1).unsqueeze(0).to(device)

    with torch.no_grad():
        out = model(img)

    out = out.squeeze().permute(1,2,0).cpu().numpy()
    out = (out * 255).clip(0,255).astype("uint8")

    return out

