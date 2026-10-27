# RunPod + Qwen3.6-27B: Complete Deployment Guide

> Hardware-tested on RTX PRO 6000 Blackwell (~$1.89–1.91/hr on RunPod)

---

## Prerequisites

Before anything, make sure you have:
- A **RunPod account** with credits loaded → [runpod.io](https://runpod.io)
- An **SSH key pair** on your machine
- A **Hugging Face account** + read token (speeds up downloads, avoids rate limits)

---

## VRAM Reality Check

| Model format | Approx. VRAM needed |
|---|---|
| Qwen3.6-27B full BF16 | ~54 GB |
| Qwen3.6-27B Q4_K_XL GGUF (quantized) | ~17 GB on disk, ~20 GB VRAM |

**Recommended GPU:** RTX 4090 (24 GB, tight), RTX A6000 (48 GB), or **RTX PRO 6000 Blackwell (96 GB)** — the 96 GB option gives the most headroom and is confirmed working.

**Other available GPU options on RunPod:**

| GPU | VRAM | Price (On-Demand) | Notes |
|---|---|---|---|
| RTX 3090 | 24 GB | ~$0.22–0.34/hr spot | Cheapest, works fine for inference |
| RTX 4090 | 24 GB | ~$0.69/hr | Best budget option |
| A40 | 48 GB | ~$0.39–0.78/hr | Good value, widely available |
| RTX 6000 Ada | 48 GB | ~$0.79/hr | Solid with headroom |
| L40S | 48 GB | ~$1.14/hr | Data center grade, reliable |
| A100 80GB | 80 GB | ~$1.99/hr | Fast HBM memory |

> GPU availability varies by region. If your preferred GPU isn't available, switch regions — RunPod operates across 31 global regions.

---

## Step 1 — Register Your SSH Key with RunPod

On your machine, get your public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

If nothing prints, generate one first:

```bash
ssh-keygen -t ed25519 -C "runpod" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

In RunPod dashboard:
> **Settings → SSH Public Keys → Paste key → Update public key**

---

## Step 2 — Deploy a GPU Pod

In RunPod dashboard: **Pods → Deploy → GPU Pod**

Configure as follows:

| Setting | Value |
|---|---|
| GPU | RTX PRO 6000 (96 GB VRAM) or RTX A6000 (48 GB) |
| Template | `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` |
| Container disk | 100 GB |
| Volume disk | **150 GB** (critical — leave headroom beyond the 17 GB model) |
| Volume mount path | `/workspace` |
| Expose HTTP Ports | `8888, 8000` |

> ⚠️ **Critical:** expose port `8000` at creation time. You cannot add it to a running pod later without recreating it. Port `8888` is Jupyter, `8000` is the Ollama API.

Click **Deploy On-Demand**. Pod takes ~2 minutes to come up.

---

## Step 3 — Open a Terminal on the Pod

In RunPod → your pod → **Connect → Jupyter Lab**

Then in JupyterLab: **File → New → Terminal**

Verify everything looks good:

```bash
nvidia-smi          # Should show your GPU with 0 MiB used
df -h /workspace    # Should show ~150 GB free
```

---

## Step 4 — Install Dependencies & Download the Model

In the pod terminal:

```bash
cd /workspace
export HF_HOME=/workspace/huggingface
export HF_HUB_ENABLE_HF_TRANSFER=1
export HF_TOKEN=hf_your_token_here   # Replace with your real HF token

pip install -q -U huggingface_hub hf_transfer
```

Now download the **Q4_K_XL quantized GGUF** (~17 GB, takes ~1 min on RunPod's fast network):

```bash
hf download unsloth/Qwen3.6-27B-GGUF \
  --include "*UD-Q4_K_XL*" \
  --local-dir /workspace/gguf
```

Verify it downloaded:

```bash
ls -lh /workspace/gguf/
# You should see: Qwen3.6-27B-UD-Q4_K_XL.gguf  (~17G)
```

---

## Step 5 — Install Ollama

> **Why Ollama and not vLLM or llama.cpp?**
> - vLLM's prebuilt CUDA kernels don't yet support Blackwell's `sm_120` for Qwen3.6 (causes PTX errors)
> - llama.cpp works for basic inference but breaks tool-calling in recent client versions
> - Ollama handles both Blackwell GPUs and tool-calling cleanly

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Safe to ignore** these warnings inside RunPod containers:
- `"systemd is not running"`
- `"Unable to detect NVIDIA GPU"`

Ollama auto-detects the GPU at runtime — these are harmless.

---

## Step 6 — Start the Ollama Server

Run Ollama on port 8000, storing models on your persistent volume:

```bash
OLLAMA_MODELS=/workspace/ollama-models \
OLLAMA_HOST=0.0.0.0:8000 \
nohup ollama serve > /workspace/ollama.log 2>&1 &
```

Wait 2 seconds, then verify it's running:

```bash
sleep 2
curl http://localhost:8000/api/tags
# Expected output: {"models":[]}
```

---

## Step 7 — Pull Qwen3.6-27B via Ollama

> **Important:** Do NOT do `ollama create` from the local GGUF file. The resulting model won't advertise tool-calling capability and clients will reject it. Pull the official Ollama build instead — it includes the correct chat template with tool calling.

```bash
OLLAMA_HOST=0.0.0.0:8000 ollama pull qwen3.6:27b
```

This downloads ~17 GB and takes 1–2 minutes. Once done, verify capabilities:

```bash
OLLAMA_HOST=0.0.0.0:8000 ollama show qwen3.6:27b
```

Under `Capabilities` you must see: **completion, vision, tools, thinking**

If `tools` is missing, tool-calling clients will fail. If all four are present, you're good.

Now you can free up the earlier GGUF download:

```bash
rm -rf /workspace/gguf
```

---

## Step 8 — Test the Model Locally on the Pod

Run a quick inference to confirm it's working:

```bash
OLLAMA_HOST=0.0.0.0:8000 ollama run qwen3.6:27b "Say hello and tell me today's date"
```

You should get a response from the model.

---

## Step 9 — Call the API from Python

> Uses `requests` only — no `openai` package needed.

**Simple single call:**
```python
import requests

response = requests.post(
    "http://localhost:8000/v1/chat/completions",
    headers={"Content-Type": "application/json"},
    json={
        "model": "qwen3.6:27b",
        "messages": [
            {"role": "user", "content": "Hello, who are you?"}
        ]
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

**Multi-turn chat with system prompt:**
```python
import requests

url = "http://localhost:8000/v1/chat/completions"
headers = {"Content-Type": "application/json"}

system_prompt = "You are a helpful coding assistant. Always respond with clean, commented code. Be concise."

history = [
    {"role": "system", "content": system_prompt}
]

while True:
    user_input = input("You: ")
    if user_input.lower() in ("exit", "quit"):
        break

    history.append({"role": "user", "content": user_input})

    response = requests.post(url, headers=headers, json={
        "model": "qwen3.6:27b",
        "messages": history
    })

    reply = response.json()["choices"][0]["message"]["content"]
    history.append({"role": "assistant", "content": reply})
    print(f"Qwen: {reply}\n")
```

---

## Step 10 — Access the API from Outside the Pod

**Via public URL (recommended — if you exposed port 8000 at pod creation):**

RunPod dashboard → your pod → **Connect → HTTP Service**. You'll see:
```
https://<pod-id>-8000.proxy.runpod.net
```

Use it directly in your Python script:
```python
url = "https://<pod-id>-8000.proxy.runpod.net/v1/chat/completions"
```

No SSH needed — works from anywhere, any machine, any browser.

**Via SSH tunnel (fallback — if port 8000 was not exposed):**

```bash
ssh -N -L 8000:localhost:8000 root@<IP> -p <PORT> -i ~/.ssh/id_ed25519
```

Keep terminal open. API is now at `http://localhost:8000` on your local machine.

> ⚠️ The public proxy URL has no authentication by default. Keep it private — recreate the pod to rotate the URL if needed.

---

## Scripts for Easy Reuse

> Since RunPod's container disk is wiped on every restart, these scripts saved to `/workspace` let you rebuild the environment with a single command each time.

### `setup.sh` — Run once on a fresh pod
> Installs system packages, Ollama, and pulls the model to `/workspace`. Takes ~5 minutes. Never needs to run again as long as your volume persists.

```bash
cat > /workspace/setup.sh << 'EOF'
#!/bin/bash

echo ">>> Installing system packages..."
apt-get update -qq
apt-get install -y zstd python3-venv

echo ">>> Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

echo ">>> Starting Ollama temporarily to pull model..."
OLLAMA_MODELS=/workspace/ollama-models \
OLLAMA_HOST=0.0.0.0:8000 \
nohup ollama serve > /workspace/ollama.log 2>&1 &

sleep 5

echo ">>> Pulling qwen3.6:27b (this may take a few minutes)..."
OLLAMA_HOST=0.0.0.0:8000 ollama pull qwen3.6:27b

echo ">>> Setup done! Run 'bash /workspace/start.sh' to start Ollama."
EOF

chmod +x /workspace/setup.sh
```

### `setup_python.sh` — Run once if you need Python
> Creates a venv under `/workspace/venv` so pip packages also survive restarts.

```bash
cat > /workspace/setup_python.sh << 'EOF'
#!/bin/bash

echo ">>> Creating Python venv at /workspace/venv..."
python3 -m venv /workspace/venv

echo ">>> Installing packages..."
/workspace/venv/bin/pip install --upgrade pip
/workspace/venv/bin/pip install requests

echo ">>> Saving requirements..."
/workspace/venv/bin/pip freeze > /workspace/requirements.txt

echo ">>> Done! Activate with: source /workspace/venv/bin/activate"
EOF

chmod +x /workspace/setup_python.sh
```

### `start.sh` — Run every time the pod restarts
> Reinstalls Ollama (wiped on restart) and starts the server. Model is already in `/workspace` so no re-download needed — starts in seconds.

```bash
cat > /workspace/start.sh << 'EOF'
#!/bin/bash

echo ">>> Installing system packages..."
apt-get update -qq
apt-get install -y zstd

echo ">>> Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

echo ">>> Starting Ollama server on port 8000..."
OLLAMA_MODELS=/workspace/ollama-models \
OLLAMA_HOST=0.0.0.0:8000 \
nohup ollama serve > /workspace/ollama.log 2>&1 &

echo ">>> Waiting for server to be ready..."
sleep 5

echo ">>> Verifying loaded models..."
curl http://localhost:8000/api/tags

echo ""
echo ">>> Ollama is running on port 8000."
echo "    Public URL: https://<pod-id>-8000.proxy.runpod.net"
echo "    Internal:   http://localhost:8000"
EOF

chmod +x /workspace/start.sh
```

---

## Every Restart Cheatsheet

```bash
bash /workspace/start.sh                   # always — starts Ollama
source /workspace/venv/bin/activate        # only if you need Python
```

---

## Storage Cheatsheet

| What | Where | Survives restart? |
|---|---|---|
| Ollama binary | `/usr/local/bin/ollama` | ❌ reinstalled by start.sh |
| Model weights | `/workspace/ollama-models/` | ✅ |
| Python venv | `/workspace/venv/` | ✅ |
| Your scripts | `/workspace/` | ✅ |
| System packages | container disk | ❌ reinstalled by start.sh |

> Golden rule: **if it's not under `/workspace`, assume it's gone after a restart.**

---

## Common Gotchas

| Problem | Fix |
|---|---|
| "CUDA PTX error" with vLLM | Use Ollama instead (vLLM doesn't support Blackwell sm_120 yet for Qwen3.6) |
| `tools` missing in `ollama show` | You created from GGUF directly. Delete and `ollama pull qwen3.6:27b` properly |
| Pod terminal shows "Unable to detect NVIDIA GPU" | Harmless in containers — GPU is detected at runtime |
| Volume full mid-download | Set volume to at least 150 GB during pod creation |
| SSH connection refused | Make sure you exposed TCP port 22 when creating the pod |
| Port 8000 not accessible publicly | You forgot to expose HTTP port 8000 at pod creation — recreate the pod |
| Everything gone after restart | Ollama/packages were on container disk. Use start.sh to rebuild, model is safe in /workspace |
