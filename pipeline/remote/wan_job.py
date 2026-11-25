# Wan 2.2 TI2V-5B image-to-video, written to run on a Kaggle session with two T4 GPUs.
#
# This file is not imported by the pipeline. pipeline/providers/kaggle.py copies
# it to Kaggle with one line added at the top:  JOB_JSON = r'''{...}'''
#
# The job description holds:
#   inputs    files to fetch: {"name", "b64"} or {"name", "url"}
#   tasks     one clip each: id, image, prompt, seed, width, height, num_frames,
#             steps, guidance, precision ("fp16" or "fp32")
#   settings  model, negative_prompt, time_budget_min, fps
#
# Rules this script follows, because nothing can be watched while it runs:
#   - It never raises to the top. Every task's error is caught and recorded.
#   - It stops starting new tasks when the time budget is nearly spent.
#   - Each clip is written the moment it is finished.
#   - It always ends by writing results.json.
#
# Memory plan for 2 x T4 (16 GB each) and about 30 GB of RAM:
#   1. Encode every prompt once on the CPU, then free the 11 GB text encoder.
#   2. Load one pipeline per GPU without a text encoder.
#   3. One thread per GPU works through its share of the tasks.

import base64
import gc
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

START = time.time()
JOB = json.loads(JOB_JSON)  # noqa: F821  (added by the builder)
SETTINGS = JOB.get("settings", {})
OUT = "/kaggle/working" if os.path.isdir("/kaggle/working") else os.path.abspath("job_out")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "job.log")
RESULTS = {"job": JOB.get("name"), "started": START, "tasks": [], "notes": [], "environment": {}}
LOCK = threading.Lock()


def log(message):
    line = "[%7.1fs] %s" % (time.time() - START, message)
    print(line, flush=True)
    with LOCK:
        with open(LOG_PATH, "a") as handle:
            handle.write(line + "\n")


def save_results():
    with LOCK:
        RESULTS["elapsed_s"] = round(time.time() - START, 1)
        with open(os.path.join(OUT, "results.json"), "w") as handle:
            json.dump(RESULTS, handle, indent=2)


def minutes_left():
    return SETTINGS.get("time_budget_min", 120) - (time.time() - START) / 60.0


def scratch_dir():
    """The roomiest place that is not saved as job output (the model is about 30 GB)."""
    best, best_free = "/tmp", 0
    for candidate in ("/kaggle/temp", "/tmp", "/root"):
        try:
            os.makedirs(candidate, exist_ok=True)
            free = shutil.disk_usage(candidate).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = candidate, free
    log("scratch dir %s with %.0f GB free" % (best, best_free / 1e9))
    return best


def pip_install():
    packages = ["diffusers", "transformers", "accelerate", "ftfy", "imageio", "imageio-ffmpeg", "sentencepiece", "psutil"]
    started = time.time()
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", *packages],
                            capture_output=True, text=True)
    log("pip install finished in %.0fs (exit %d)" % (time.time() - started, result.returncode))
    if result.returncode != 0:
        log("pip stderr: " + result.stderr[-800:])
        RESULTS["notes"].append("pip install failed: " + result.stderr[-300:])


def fetch_inputs(folder):
    os.makedirs(folder, exist_ok=True)
    for item in JOB.get("inputs", []):
        target = os.path.join(folder, item["name"])
        if "b64" in item:
            with open(target, "wb") as handle:
                handle.write(base64.b64decode(item["b64"]))
        else:
            urllib.request.urlretrieve(item["url"], target)
        log("input %s (%d bytes)" % (item["name"], os.path.getsize(target)))


def ram_gb():
    try:
        import psutil
        memory = psutil.virtual_memory()
        return round(memory.used / 1e9, 1), round(memory.total / 1e9, 1)
    except Exception:
        return None, None


def encode_prompts(model, tasks, scratch):
    """Encode every distinct prompt once on the CPU and free the text encoder."""
    import torch
    from diffusers import WanImageToVideoPipeline

    started = time.time()
    negative = SETTINGS.get("negative_prompt", "")
    prompts = sorted({task["prompt"] for task in tasks})
    log("encoding %d prompt(s) on CPU" % len(prompts))

    # Half precision first (11 GB of RAM); full precision (23 GB) only if that fails.
    last_error = None
    for label, dtype in (("bfloat16", torch.bfloat16), ("float32", torch.float32)):
        pipe = None
        try:
            pipe = WanImageToVideoPipeline.from_pretrained(
                model, transformer=None, vae=None, torch_dtype=dtype, cache_dir=scratch,
            )
            log("text encoder loaded as %s; RAM used/total GB: %s" % (label, ram_gb()))
            embeds = {}
            with torch.no_grad():
                for prompt in prompts:
                    positive, negative_embeds = pipe.encode_prompt(
                        prompt=prompt, negative_prompt=negative, do_classifier_free_guidance=True,
                        num_videos_per_prompt=1, max_sequence_length=512, device=torch.device("cpu"),
                    )
                    if not (torch.isfinite(positive).all() and torch.isfinite(negative_embeds).all()):
                        raise RuntimeError("text encoder produced non-finite values")
                    embeds[prompt] = (positive.float().cpu(), negative_embeds.float().cpu())
            log("prompts encoded as %s in %.0fs" % (label, time.time() - started))
            RESULTS["environment"]["encode_prompts_s"] = round(time.time() - started, 1)
            RESULTS["environment"]["text_encoder_dtype"] = label
            return embeds
        except Exception as exc:
            last_error = exc
            log("text encoding as %s failed: %s: %s" % (label, type(exc).__name__, str(exc)[:300]))
            RESULTS["notes"].append("text encoding as %s failed: %s" % (label, str(exc)[:200]))
        finally:
            del pipe
            gc.collect()
    raise RuntimeError("could not encode prompts: %s" % last_error)


def load_pipeline(model, gpu, precision, scratch):
    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline

    started = time.time()
    dtype = torch.float16 if precision == "fp16" else torch.float32
    vae = AutoencoderKLWan.from_pretrained(model, subfolder="vae", torch_dtype=torch.float32, cache_dir=scratch)
    pipe = WanImageToVideoPipeline.from_pretrained(
        model, vae=vae, text_encoder=None, tokenizer=None, torch_dtype=dtype, cache_dir=scratch,
    )
    if precision == "fp16":
        pipe.enable_model_cpu_offload(gpu_id=gpu)
    else:
        pipe.enable_sequential_cpu_offload(gpu_id=gpu)  # 20 GB of weights do not fit a T4
    tiling = "off"
    try:
        pipe.vae.enable_tiling()
        tiling = "on"
    except Exception as exc:
        tiling = "unsupported (%s)" % type(exc).__name__
    log("pipeline for GPU %d (%s) loaded in %.0fs; VAE tiling %s; RAM %s"
        % (gpu, precision, time.time() - started, tiling, ram_gb()))
    return pipe, round(time.time() - started, 1), tiling


def frame_stats(frames):
    """Numbers that expose a black or broken clip without a human looking at it."""
    import numpy as np

    array = np.asarray(frames, dtype="float32")
    finite = bool(np.isfinite(array).all())
    mean = float(np.nan_to_num(array).mean())
    spread = float(np.nan_to_num(array).std())
    motion = float(np.abs(np.nan_to_num(array[-1]) - np.nan_to_num(array[0])).mean())
    return {
        "finite": finite,
        "mean": round(mean, 4),
        "std": round(spread, 4),
        "first_last_diff": round(motion, 4),
        "black": (not finite) or mean < 0.02 or spread < 0.01,
        "frozen": motion < 0.002,
    }


def run_task(pipe, task, gpu, embeds, inputs, load_info):
    import torch
    from diffusers.utils import export_to_video, load_image
    from PIL import Image, ImageOps

    record = {
        "id": task["id"], "status": "error", "gpu": gpu, "width": task["width"], "height": task["height"],
        "num_frames": task["num_frames"], "steps": task["steps"], "guidance": task["guidance"],
        "precision": task.get("precision", "fp16"), "seed": task["seed"], "prompt": task["prompt"],
        "image": task["image"], "load_s": load_info[0], "vae_tiling": load_info[1],
    }
    started = time.time()
    try:
        torch.cuda.reset_peak_memory_stats(gpu)
        image = load_image(os.path.join(inputs, task["image"])).convert("RGB")
        # Crop to the clip's shape around the focus point, then resize. Never stretch.
        focus = (task.get("focus_x", 0.5), task.get("focus_y", 0.5))
        image = ImageOps.fit(image, (task["width"], task["height"]), Image.LANCZOS, centering=focus)
        positive, negative = embeds[task["prompt"]]
        dtype = torch.float16 if record["precision"] == "fp16" else torch.float32
        generator = torch.Generator(device="cpu").manual_seed(int(task["seed"]))
        output = pipe(
            image=image,
            prompt_embeds=positive.to(dtype),
            negative_prompt_embeds=negative.to(dtype),
            height=task["height"], width=task["width"], num_frames=task["num_frames"],
            num_inference_steps=task["steps"], guidance_scale=task["guidance"],
            generator=generator,
        )
        frames = output.frames[0]
        record["seconds"] = round(time.time() - started, 1)
        record["seconds_per_step"] = round(record["seconds"] / task["steps"], 2)
        record["peak_vram_gb"] = round(torch.cuda.max_memory_allocated(gpu) / 1e9, 2)
        record.update(frame_stats(frames))

        name = task["id"]
        export_to_video(frames, os.path.join(OUT, name + ".mp4"), fps=SETTINGS.get("fps", 24))
        for label, index in (("first", 0), ("mid", len(frames) // 2), ("last", len(frames) - 1)):
            frame = (frames[index] * 255).clip(0, 255).astype("uint8")
            Image.fromarray(frame).save(os.path.join(OUT, "%s_%s.jpg" % (name, label)), quality=88)
        record["output"] = name + ".mp4"
        record["status"] = "black" if record["black"] else "ok"
    except Exception as exc:
        record["seconds"] = round(time.time() - started, 1)
        record["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
        record["traceback"] = traceback.format_exc()[-1500:]
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
    log("task %s on GPU %d: %s in %.0fs" % (task["id"], gpu, record["status"], record["seconds"]))
    with LOCK:
        RESULTS["tasks"].append(record)
    save_results()


def worker(gpu, tasks, embeds, inputs, model, scratch, load_lock):
    current_precision, pipe, load_info = None, None, (None, None)
    for task in tasks:
        estimate = task.get("estimate_min", 0)
        if minutes_left() < max(4, estimate):
            with LOCK:
                RESULTS["tasks"].append({"id": task["id"], "status": "skipped", "gpu": gpu,
                                         "error": "time budget reached before this task started"})
            save_results()
            log("task %s skipped: %.1f min left" % (task["id"], minutes_left()))
            continue
        precision = task.get("precision", "fp16")
        if precision != current_precision:
            try:
                pipe = None
                gc.collect()
                with load_lock:  # load one pipeline at a time to keep RAM down
                    pipe, seconds, tiling = load_pipeline(model, gpu, precision, scratch)
                load_info, current_precision = (seconds, tiling), precision
            except Exception as exc:
                with LOCK:
                    RESULTS["tasks"].append({"id": task["id"], "status": "error", "gpu": gpu,
                                             "error": "pipeline load failed: %s: %s" % (type(exc).__name__, str(exc)[:300]),
                                             "traceback": traceback.format_exc()[-1500:]})
                save_results()
                log("pipeline load failed on GPU %d: %s" % (gpu, exc))
                current_precision = None
                continue
        run_task(pipe, task, gpu, embeds, inputs, load_info)


def main():
    scratch = scratch_dir()
    os.environ["HF_HOME"] = os.path.join(scratch, "hf")
    pip_install()

    import torch
    gpus = torch.cuda.device_count()
    RESULTS["environment"].update({
        "torch": torch.__version__,
        "gpu_count": gpus,
        "gpus": [torch.cuda.get_device_name(i) for i in range(gpus)],
        "python": sys.version.split()[0],
        "ram_total_gb": ram_gb()[1],
    })
    try:
        import diffusers
        RESULTS["environment"]["diffusers"] = diffusers.__version__
    except Exception as exc:
        RESULTS["notes"].append("diffusers import failed: %s" % exc)
    log("environment: %s" % json.dumps(RESULTS["environment"]))
    save_results()
    if gpus == 0:
        RESULTS["notes"].append("no GPU in this session")
        return

    inputs = os.path.join(scratch, "inputs")
    fetch_inputs(inputs)
    tasks = JOB["tasks"]
    model = SETTINGS["model"]

    embeds = encode_prompts(model, tasks, os.environ["HF_HOME"])
    save_results()

    load_lock = threading.Lock()
    shares = [tasks[index::gpus] for index in range(gpus)]
    threads = [
        threading.Thread(target=worker, args=(gpu, share, embeds, inputs, model, os.environ["HF_HOME"], load_lock))
        for gpu, share in enumerate(shares) if share
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


try:
    main()
except BaseException as exc:  # recorded, never raised: the job must end cleanly
    RESULTS["notes"].append("fatal: %s: %s" % (type(exc).__name__, str(exc)[:500]))
    RESULTS["fatal_traceback"] = traceback.format_exc()[-3000:]
    log("FATAL " + traceback.format_exc()[-1500:])
finally:
    RESULTS["finished"] = time.time()
    save_results()
    log("done: %d task record(s)" % len(RESULTS["tasks"]))
