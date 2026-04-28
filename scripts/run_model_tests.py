#!/usr/bin/env python3
"""
Machine Flinch Index — batch test runner.
Usage:
    python3 scripts/run_model_tests.py --model "anthropic/claude-3-haiku"
    python3 scripts/run_model_tests.py --all-untested
    python3 scripts/run_model_tests.py --list-available

Cron (disabled by default):
# 0 6 * * * cd /home/ben/infra/copecheck && venv/bin/python3 scripts/run_model_tests.py --all-untested >> logs/model_tests.log 2>&1
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import model_cope

def main():
    parser = argparse.ArgumentParser(description="Machine Flinch Index test runner")
    parser.add_argument("--model", type=str, help="Test a specific model")
    parser.add_argument("--all-untested", action="store_true", help="Test next batch of untested models (max 5)")
    parser.add_argument("--list-available", action="store_true", help="List available Straico models")
    parser.add_argument("--max-batch", type=int, default=5, help="Max models in batch mode")
    args = parser.parse_args()

    model_cope.init_model_cope()

    if args.list_available:
        models = model_cope.get_straico_models()
        print(f"Found {len(models)} chat models on Straico:")
        for m in models:
            name = m.get("model") or m.get("name") or str(m)
            print(f"  - {name}")
        return

    if args.model:
        print(f"Testing model: {args.model}")
        try:
            result = model_cope.test_model_straico(args.model, tested_by="admin")
            print(f"  Speed to Horror: {result['speed_to_horror']}/10")
            print(f"  Depth of Flinch: {result['depth_of_flinch']}/10")
            print(f"  Machine Cope Score: {result['machine_cope_score']}/100")
            print(f"  Flinch Quote: {result.get('flinch_quote', '(none)')[:200]}")
            print(f"  Turns: {result['num_turns']}")
        except Exception as e:
            print(f"  FAILED: {e}")
        return

    if args.all_untested:
        models = model_cope.get_straico_models()
        untested = model_cope.get_untested_straico_models(models, limit=args.max_batch)
        if not untested:
            print("All available models have been tested.")
            return
        print(f"Testing {len(untested)} untested models...")
        for name in untested:
            print(f"\n--- Testing: {name} ---")
            try:
                result = model_cope.test_model_straico(name, tested_by="auto")
                print(f"  Cope Score: {result['machine_cope_score']}/100 (Speed: {result['speed_to_horror']}, Flinch: {result['depth_of_flinch']})")
            except Exception as e:
                print(f"  FAILED: {e}")
            time.sleep(5)
        print("\nBatch complete.")
        return

    parser.print_help()

if __name__ == "__main__":
    main()
