#!/usr/bin/env python3
"""Generate Straico AI portraits for all CopeCheck figures."""
import json
import os
import requests
import time
import yaml
from pathlib import Path

STRAICO_API_KEY = os.environ.get("STRAICO_API_KEY", "ya-e9gJ18QpnfkSQLBgMxImEAqKyn0JFQvQH5u474GZctpNUvm0")
STRAICO_URL = "https://api.straico.com/v1/image/generation"
FIGURES_PATH = Path(__file__).parent / "figures.yaml"
PHOTOS_DIR = Path(__file__).parent / "static" / "photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "openai/dall-e-3"

def load_figures():
    with open(FIGURES_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("figures", [])

def generate_portrait(name, title, figure_id):
    outfile = PHOTOS_DIR / f"{figure_id}.png"
    if outfile.exists() and outfile.stat().st_size > 10000:
        print(f"  SKIP {figure_id} (already exists)")
        return True

    prompt = (
        f"Dark, stylised editorial portrait illustration of {name}, {title}. "
        f"Dramatic chiaroscuro lighting, deep black background, slightly desaturated colors. "
        f"Sharp-focused face with intense expression. Modern digital art style with painterly textures. "
        f"Professional headshot composition, shoulders and head visible. "
        f"High contrast, moody atmosphere, editorial magazine quality."
    )
    print(f"  Generating portrait for {name}...")
    try:
        resp = requests.post(
            STRAICO_URL,
            headers={
                "Authorization": f"Bearer {STRAICO_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "description": prompt,
                "size": "square",
                "variations": 1,
            },
            timeout=120,
        )
        if resp.status_code not in (200, 201):
            print(f"  ERROR: API returned {resp.status_code}: {resp.text[:200]}")
            return False
        data = resp.json()
        if not data.get("success") or not data.get("data", {}).get("images"):
            # Try alternate response structure
            images = data.get("data", {}).get("images", [])
            if not images:
                print(f"  ERROR: No images in response: {json.dumps(data)[:300]}")
                return False
        image_url = data["data"]["images"][0]
        coins = data.get("data", {}).get("price", {}).get("total", "?")
        print(f"  Downloading image ({coins} coins)...")
        img_resp = requests.get(image_url, timeout=60)
        if img_resp.status_code == 200:
            outfile.write_bytes(img_resp.content)
            print(f"  OK: {outfile} ({len(img_resp.content)//1024}KB)")
            return True
        else:
            print(f"  ERROR: Download failed {img_resp.status_code}")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def update_figures_yaml(figures):
    """Update figures.yaml to use local photo paths."""
    for fig in figures:
        fig["photo_url"] = f"/static/photos/{fig['id']}.png"
    with open(FIGURES_PATH, "w") as f:
        f.write("# CopeCheck — Tracked Figures for the Cope Index\nfigures:\n")
        for fig in figures:
            f.write(f"  - id: {fig['id']}\n")
            f.write(f"    name: {fig['name']}\n")
            f.write(f"    title: \"{fig.get('title', '')}\"\n")
            f.write(f"    category: {fig.get('category', '')}\n")
            f.write(f"    photo_url: {fig['photo_url']}\n")
            if fig.get('cope_bias'):
                f.write(f"    cope_bias: \"{fig['cope_bias']}\"\n")
            else:
                f.write(f"    cope_bias: null\n")
            f.write(f"    search_queries:\n")
            for q in fig.get("search_queries", []):
                f.write(f"      - \"{q}\"\n")
            f.write("\n")
    print(f"Updated figures.yaml with local photo paths")

def main():
    figures = load_figures()
    print(f"Generating portraits for {len(figures)} figures using {MODEL}...")
    
    success = 0
    failed = []
    for fig in figures:
        ok = generate_portrait(fig["name"], fig.get("title", ""), fig["id"])
        if ok:
            success += 1
        else:
            failed.append(fig["id"])
        time.sleep(3)  # Rate limiting
    
    print(f"\nResults: {success}/{len(figures)} generated")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    
    # Update YAML to point to local paths
    update_figures_yaml(figures)
    
    # Also update the DB
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import db
    db.init()
    for fig in figures:
        db.upsert_figure(
            fig["id"], fig["name"], fig.get("title"),
            fig.get("category"), fig["photo_url"],
            fig.get("cope_bias"),
        )
    print("Updated DB with local photo URLs")

if __name__ == "__main__":
    main()
