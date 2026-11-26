# ACE-Step 1.5 score candidates, written to run on a Kaggle GPU session.
#
# This file is not imported by the pipeline. pipeline/providers/kaggle.py copies
# it to Kaggle with one line added at the top:  JOB_JSON = r'''{...}'''
#
# The job description holds:
#   music     caption, bpm, keyscale, duration_s, instrumental, seeds
#   settings  repo, config_path, inference_steps, time_budget_min
#
# ACE-Step is run without its language-model planner. The score is
# instrumental and the storyboard already fixes tempo, key and length, so the
# planner has nothing to decide, and leaving it out removes a 2 GB download
# and one way to fail.
#
# Like every remote job here: it never raises to the top and always ends by
# writing results.json.

import json
import os
import shutil
import subprocess
import sys
import time
import traceback

START = time.time()
JOB = json.loads(JOB_JSON)  # noqa: F821  (added by the builder)
SETTINGS = JOB.get("settings", {})
OUT = "/kaggle/working" if os.path.isdir("/kaggle/working") else os.path.abspath("job_out")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "job.log")
RESULTS = {"job": JOB.get("name"), "started": START, "tasks": [], "notes": [], "environment": {}}

# The generator runs inside ACE-Step's own environment (it needs Python 3.11 or 3.12).
GENERATOR = r'''
import inspect, json, os, sys, time, traceback

job = json.load(open(sys.argv[1]))
out_dir, results_path = sys.argv[2], sys.argv[3]
music, settings = job["music"], job.get("settings", {})
results = {"tasks": [], "notes": [], "environment": {}}

def supported(function, **wanted):
    """Pass only the arguments this version of the function accepts."""
    accepted = inspect.signature(function).parameters
    dropped = [name for name in wanted if name not in accepted]
    if dropped:
        results["notes"].append("%s ignored: %s" % (function.__name__, dropped))
    return {name: value for name, value in wanted.items() if name in accepted}

try:
    import torch
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    results["environment"] = {
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "initialize_service": str(inspect.signature(AceStepHandler.initialize_service)),
    }
    started = time.time()
    handler = AceStepHandler()
    handler.initialize_service(**supported(
        handler.initialize_service,
        project_root=os.getcwd(),
        config_path=settings.get("config_path", "acestep-v15-turbo"),
        device="cuda" if torch.cuda.is_available() else "cpu",
    ))
    results["environment"]["load_s"] = round(time.time() - started, 1)

    for seed in music["seeds"]:
        record = {"id": "cand_%d" % seed, "seed": seed, "status": "error"}
        started = time.time()
        try:
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            params = GenerationParams(**supported(
                GenerationParams,
                caption=music["caption"],
                lyrics="[Instrumental]" if music.get("instrumental", True) else "",
                instrumental=bool(music.get("instrumental", True)),
                bpm=int(music["bpm"]),
                keyscale=music["keyscale"],
                duration=float(music["duration_s"]),
                inference_steps=int(settings.get("inference_steps", 8)),
                seed=int(seed),
                thinking=False,
                use_cot_metas=False,
                use_cot_caption=False,
                use_cot_language=False,
            ))
            config = GenerationConfig(**supported(
                GenerationConfig, batch_size=1, use_random_seed=False, seeds=[int(seed)], audio_format="wav",
            ))
            result = generate_music(handler, None, params, config, save_dir=out_dir)
            record["seconds"] = round(time.time() - started, 1)
            if torch.cuda.is_available():
                record["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
            if getattr(result, "success", False) and result.audios:
                audio = result.audios[0]
                target = os.path.join(out_dir, "cand_%d.wav" % seed)
                os.replace(audio["path"], target)
                record.update(status="ok", output=os.path.basename(target),
                              sample_rate=audio.get("sample_rate"))
            else:
                record["error"] = str(getattr(result, "error", "no audio returned"))[:400]
        except Exception as exc:
            record["seconds"] = round(time.time() - started, 1)
            record["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
            record["traceback"] = traceback.format_exc()[-1500:]
        results["tasks"].append(record)
        json.dump(results, open(results_path, "w"), indent=2)
except Exception as exc:
    results["notes"].append("fatal: %s: %s" % (type(exc).__name__, str(exc)[:500]))
    results["fatal_traceback"] = traceback.format_exc()[-3000:]
finally:
    json.dump(results, open(results_path, "w"), indent=2)
'''


def log(message):
    line = "[%7.1fs] %s" % (time.time() - START, message)
    print(line, flush=True)
    with open(LOG_PATH, "a") as handle:
        handle.write(line + "\n")


def save_results():
    RESULTS["elapsed_s"] = round(time.time() - START, 1)
    with open(os.path.join(OUT, "results.json"), "w") as handle:
        json.dump(RESULTS, handle, indent=2)


def sh(command, cwd=None, timeout=3600):
    started = time.time()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    log("%s -> exit %d in %.0fs" % (" ".join(command)[:90], result.returncode, time.time() - started))
    if result.returncode != 0:
        log("stderr tail: " + result.stderr[-1200:])
    return result


def scratch_dir():
    best, best_free = "/tmp", 0
    for candidate in ("/kaggle/temp", "/tmp", "/root"):
        try:
            os.makedirs(candidate, exist_ok=True)
            free = shutil.disk_usage(candidate).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = candidate, free
    return best



def preflight():
    """Fail in seconds, not after a 14-minute pip timeout, when Kaggle gave the session
    no network or no GPU (both happen when the account is not phone-verified)."""
    import shutil
    import socket
    ok = True
    try:
        socket.getaddrinfo("pypi.org", 443)
    except OSError as exc:
        RESULTS["notes"].append("no internet in this session (%s); is the Kaggle account phone-verified?" % exc)
        ok = False
    if SETTINGS.get("require_gpu", True) and shutil.which("nvidia-smi") is None:
        RESULTS["notes"].append("no GPU in this session (nvidia-smi missing); is the Kaggle account phone-verified and is GPU quota left?")
        ok = False
    RESULTS["environment"]["preflight_ok"] = ok
    return ok


def main():
    scratch = scratch_dir()
    repo_dir = os.path.join(scratch, "ACE-Step-1.5")
    repo_url = SETTINGS.get("repo", "https://github.com/ACE-Step/ACE-Step-1.5")

    if not preflight():
        save_results()
        return
    sh([sys.executable, "-m", "pip", "install", "-q", "-U", "uv"])
    if sh(["git", "clone", "--depth", "1", repo_url, repo_dir]).returncode != 0:
        RESULTS["notes"].append("git clone failed")
        return
    commit = sh(["git", "rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()
    RESULTS["environment"]["acestep_commit"] = commit

    uv = [sys.executable, "-m", "uv"]
    sync = sh(uv + ["sync"], cwd=repo_dir, timeout=2400)
    if sync.returncode != 0:
        RESULTS["notes"].append("uv sync failed: " + sync.stderr[-400:])
        return
    save_results()

    job_path = os.path.join(scratch, "job.json")
    generator_path = os.path.join(repo_dir, "heritage_generate.py")
    inner_results = os.path.join(scratch, "inner_results.json")
    with open(job_path, "w") as handle:
        json.dump(JOB, handle)
    with open(generator_path, "w") as handle:
        handle.write(GENERATOR)

    env = dict(os.environ, ACESTEP_CHECKPOINTS_DIR=os.path.join(scratch, "acestep_checkpoints"),
               ACESTEP_INIT_LLM="false", HF_HOME=os.path.join(scratch, "hf"))
    budget_s = int(SETTINGS.get("time_budget_min", 60) * 60 - (time.time() - START))
    started = time.time()
    try:
        run = subprocess.run(uv + ["run", "python", generator_path, job_path, OUT, inner_results],
                             cwd=repo_dir, env=env, capture_output=True, text=True, timeout=max(300, budget_s))
        log("generator exit %d in %.0fs" % (run.returncode, time.time() - started))
        log("generator stdout tail: " + run.stdout[-1500:])
        if run.returncode != 0:
            log("generator stderr tail: " + run.stderr[-2500:])
    except subprocess.TimeoutExpired:
        RESULTS["notes"].append("generator stopped at the time budget")
        log("generator timed out")

    if os.path.exists(inner_results):
        inner = json.load(open(inner_results))
        RESULTS["tasks"] = inner.get("tasks", [])
        RESULTS["notes"] += inner.get("notes", [])
        RESULTS["environment"].update(inner.get("environment", {}))
        if "fatal_traceback" in inner:
            RESULTS["fatal_traceback"] = inner["fatal_traceback"]
    else:
        RESULTS["notes"].append("the generator wrote no results")


try:
    main()
except BaseException as exc:  # recorded, never raised: the job must end cleanly
    RESULTS["notes"].append("fatal: %s: %s" % (type(exc).__name__, str(exc)[:500]))
    RESULTS["fatal_traceback"] = traceback.format_exc()[-3000:]
    log("FATAL " + traceback.format_exc()[-1500:])
finally:
    RESULTS["finished"] = time.time()
    save_results()
    log("done: %d candidate record(s)" % len(RESULTS["tasks"]))
