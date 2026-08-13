#!/usr/bin/env bash
# Datacrunch prelude — run BEFORE pod_sweep_setup.sh on a datacrunch pod.
#
# WHY THIS EXISTS. `cuda_12_6_pytorch_2_7` (the lambdalabs image the runbook pins) is
# **lambdalabs-only**: massedcompute rejects it, and datacrunch rejects it too
# (`HTTP 400: Provider Datacrunch is not supported for image CUDA_12_6_PYTORCH_2_7`).
# When lambdalabs is out of stock — `HTTP 503: Lambdalabs doesn't have gpu_1x_h100_pcie`,
# which happened 2026-08-13 — the fallback is datacrunch on its DEFAULT image
# `ubuntu_22_cuda_12` (omit `--image` entirely and the CLI picks it).
#
# That image is bare where the lambdalabs one is not:
#   * **no pip** (Python 3.10.12 and git and curl are present, pip is not)
#   * **no python3-dev** — and this one costs real money if you miss it. vLLM JIT-compiles at
#     engine start, so without the headers it dies with `fatal error: Python.h: No such file or
#     directory` buried under a `RuntimeError: Engine core initialization failed` that names no
#     cause. The pod bills the whole time. Measured 2026-08-13: ~$8.87 burned before diagnosis.
#     `apt-get install python3-dev` needs an `apt-get update` first on this image.
#   * no preinstalled torch — irrelevant, the pinned recipe installs its own anyway
#   * **SSH is on port 22**, not lambdalabs' 1234 — the ~/.ssh/config alias must match
#   * driver 580.126.09 (CUDA 13 capable). cu126 wheels are fine: NVIDIA drivers are
#     backward compatible with older CUDA runtimes, so the pinned torch 2.7.0+cu126 runs.
#
# Success marker: PRELUDE_OK
set -euo pipefail

if ! command -v pip3 >/dev/null 2>&1 && ! python3 -m pip --version >/dev/null 2>&1; then
  echo "== no pip on this image; bootstrapping"
  # Download THEN run. Never `curl … | python3 -` or `| sh -s` — the latter reads its script
  # from stdin, so a `< /dev/null` redirect hands it an empty program (bit this project twice).
  if ! curl -sSf https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py; then
    echo "== bootstrap.pypa.io unreachable; falling back to apt"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq python3-pip < /dev/null
  else
    python3 /tmp/get-pip.py --quiet < /dev/null
  fi
fi
# Build headers: vLLM compiles kernels at engine startup and fails opaquely without them.
if [ ! -f /usr/include/python3.10/Python.h ]; then
  echo "== installing python3-dev (vLLM needs Python.h at engine start)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq < /dev/null
  apt-get install -y python3-dev build-essential < /dev/null
fi
test -f /usr/include/python3.10/Python.h || { echo "NO PYTHON HEADERS — vllm will die"; exit 1; }

python3 -m pip --version
echo "PRELUDE_OK"
