"""Plays held-out seasons with a model behind an OpenAI-compatible endpoint, or with the reference planner, and
writes per-season results. Seasons are the Harbor task's own scenario, or generated ones with SCENARIOS=generated.

    python evaluate.py reference 1 31 results/reference-task.json
    python evaluate.py http://127.0.0.1:8000/v1 Qwen/Qwen3-4B-Instruct-2507 1 31 results/base-task.json
    python evaluate.py hf Qwen/Qwen3-4B-Instruct-2507 1 31 results/base-task.json          # transformers, on this GPU
    python evaluate.py hf Qwen/Qwen3-4B-Instruct-2507+out/lora 1 31 results/tuned-task.json   # with a LoRA adapter
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from statistics import mean

from policy import SYSTEM, play, play_batch, server, sim
from reference import decide


def chat(base_url: str, model: str):
    def policy(observation: str) -> str:
        body = {"model": model, "temperature": 0, "max_tokens": int(os.environ.get("MAX_TOKENS", "200")),
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": observation}]}
        req = urllib.request.Request(f"{base_url}/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {os.environ.get('API_KEY', 'none')}"})
        for attempt in range(8):  # back off on rate limits and transient server errors
            try:
                return json.load(urllib.request.urlopen(req, timeout=1800))["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503) or attempt == 7:
                    raise
                time.sleep(2 ** attempt)
    return policy


def hf_generate(spec: str):
    """Batched greedy generation with transformers; `spec` is a model id, optionally +path/to/lora."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    name, _, lora = spec.partition("+")
    tok = AutoTokenizer.from_pretrained(name, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.bfloat16, device_map="cuda")
    if lora:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, lora)

    def generate(observations: list[str]) -> list[str]:
        texts = [tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": o}],
                                         tokenize=False, add_generation_prompt=True) for o in observations]
        enc = tok(texts, return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=int(os.environ.get("MAX_TOKENS", "400")), do_sample=False)
        return [tok.decode(o[enc.input_ids.shape[1]:], skip_special_tokens=True) for o in out]
    return generate


def scenario(seed: int) -> sim.Scenario:
    return sim.random_scenario(seed) if os.environ.get("SCENARIOS") == "generated" else sim.TASK


def reference_season(seed: int) -> dict:
    # The planner reads the full brief and status; play() hands policies only the text, so step the market here.
    from optimum import do_nothing, optimum
    sc = scenario(seed)
    m = sim.Market(seed, sc)
    while not m.over:
        accepts, bids = decide(server.brief(m), server.status(m))
        for a in accepts:
            m.accept(a)
        for leg, b in bids.items():
            m.place_bids(leg, [(x["price"], x["tons"]) for x in b])
        m.advance()
    best, base = optimum(seed, sc), do_nothing(sc)
    return {"seed": seed, "cash": m.cash, "reward": (m.cash - base) / (best - base), "errors": 0}


if __name__ == "__main__":
    if sys.argv[1] == "hf":
        spec, lo, hi, out = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
        results = play_batch(list(range(lo, hi)), hf_generate(spec), scenario)
    elif sys.argv[1] == "reference":
        lo, hi, out = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        run = reference_season
    else:
        base_url, model, lo, hi, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
        policy = chat(base_url, model)
        run = lambda seed: play(seed, policy, scenario(seed))  # noqa: E731
    if sys.argv[1] != "hf":
        with ThreadPoolExecutor(32) as pool:  # all seasons at once: larger decode batches
            results = sorted(pool.map(run, range(lo, hi)), key=lambda r: r["seed"])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump({"mean_reward": mean(r["reward"] for r in results), "mean_cash": mean(r["cash"] for r in results),
                   "refused_moves": sum(r["errors"] for r in results), "seasons": results}, f, indent=1)
    print(f"{out}: mean reward {mean(r['reward'] for r in results):.3f}, mean cash {mean(r['cash'] for r in results):,.0f}, "
          f"refused moves {sum(r['errors'] for r in results)}")
