#!/usr/bin/env python3
"""Run v2 Machine Flinch tests on a curated set of models."""
import os, sys, time

# Load .env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

sys.path.insert(0, os.path.dirname(__file__))
import model_cope

# Curated list: mix of providers/sizes to get interesting spread
MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.5-pro-preview-03-25",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1",
    "cohere/command-r-plus-08-2024",
    "amazon/nova-lite-v1",
    "anthropic/claude-3.7-sonnet",
]

print(f"Starting v2 batch test: {len(MODELS)} models")
print("=" * 60)

for i, model in enumerate(MODELS):
    print(f"\n[{i+1}/{len(MODELS)}] Testing {model}...")
    t0 = time.time()
    try:
        result = model_cope.test_model_straico(model, tested_by="batch-v2")
        dt = time.time() - t0
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  Score: {result.get('machine_cope_score', '?')}/100 | "
                  f"Speed: {result.get('speed_to_horror', '?')}/10 | "
                  f"Flinch: {result.get('depth_of_flinch', '?')}/10 | "
                  f"Turns: {result.get('num_turns', '?')} | "
                  f"{dt:.0f}s")
            if result.get('flinch_quote'):
                print(f"  Flinch: {result['flinch_quote'][:120]}")
    except Exception as e:
        print(f"  FAILED: {e}")

    # Small delay between models to be nice to Straico
    if i < len(MODELS) - 1:
        time.sleep(3)

print("\n" + "=" * 60)
print("Batch complete!")
