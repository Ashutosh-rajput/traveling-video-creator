"""
Test script for Cloudflare Workers AI image generation.

Free-tier alternative to Google Gemini/Imagen (which currently has
0 free-tier quota for image models). Calls the Workers AI REST API
directly - no worker deployment or MCP server needed.

Setup:
    1. Create a free Cloudflare account: https://dash.cloudflare.com/sign-up
    2. Get your Account ID from the dashboard sidebar (Workers & Pages page)
    3. Create an API token: My Profile > API Tokens > Create Token
       -> use the "Workers AI" template, or a custom token with
          "Workers AI: Read" and "Workers AI: Edit" permissions
    4. Set env vars:
        export CLOUDFLARE_ACCOUNT_ID="your_account_id"
        export CLOUDFLARE_API_TOKEN="your_api_token"

Usage:
    python test_cloudflare_image.py
    python test_cloudflare_image.py --model sdxl
    python test_cloudflare_image.py --prompt "a red fox in snow, watercolor style"
    python test_cloudflare_image.py --list-models
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime

import requests

MODELS = {
    "flux": "@cf/black-forest-labs/flux-1-schnell",
    "flux2-klein": "@cf/black-forest-labs/flux-2-klein-9b",
    "leonardo": "@cf/leonardo/phoenix-1.0",
}


def get_credentials():
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not api_token:
        print("ERROR: Set both CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN env vars first.")
        print('  export CLOUDFLARE_ACCOUNT_ID="your_account_id"')
        print('  export CLOUDFLARE_API_TOKEN="your_api_token"')
        sys.exit(1)
    return account_id, api_token


# Models that require multipart/form-data instead of a plain JSON body
MULTIPART_MODELS = {
    "@cf/black-forest-labs/flux-2-dev",
    "@cf/black-forest-labs/flux-2-klein-4b",
    "@cf/black-forest-labs/flux-2-klein-9b",
}


def generate_image(account_id, api_token, model_id, prompt, out_dir):
    print(f"\n--- Testing model: {model_id} ---")
    print(f"Prompt: {prompt}")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_id}"
    start = time.time()

    try:
        if model_id in MULTIPART_MODELS:
            headers = {"Authorization": f"Bearer {api_token}"}
            # requests sets the multipart boundary automatically when 'files' is used
            form_data = {"prompt": (None, prompt), "width": (None, "1024"), "height": (None, "1024")}
            resp = requests.post(url, headers=headers, files=form_data, timeout=90)
        else:
            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }
            resp = requests.post(url, headers=headers, json={"prompt": prompt}, timeout=60)
    except requests.RequestException as e:
        print(f"FAILED (network error) after {time.time() - start:.1f}s: {e}")
        return

    elapsed = time.time() - start

    if resp.status_code != 200:
        print(f"FAILED after {elapsed:.1f}s — HTTP {resp.status_code}")
        print(f"Response: {resp.text[:1000]}")
        return

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_slug = model_id.split("/")[-1]
    out_path = os.path.join(out_dir, f"{model_slug}_{ts}.png")

    content_type = resp.headers.get("Content-Type", "")

    if "image" in content_type:
        # Some Workers AI models return raw image bytes directly
        with open(out_path, "wb") as f:
            f.write(resp.content)
        print(f"SUCCESS in {elapsed:.1f}s — saved {out_path} (raw image response)")
        return

    # Otherwise it's the JSON-wrapped format: {"result": {"image": "<base64>"}, "success": true}
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"FAILED — could not parse response as image or JSON. Raw: {resp.text[:500]}")
        return

    if not data.get("success", False):
        print(f"FAILED after {elapsed:.1f}s — API returned success=false")
        print(f"Errors: {data.get('errors')}")
        return

    image_b64 = data.get("result", {}).get("image")
    if not image_b64:
        print(f"No image in response. Full JSON: {json.dumps(data)[:1000]}")
        return

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(image_b64))
    print(f"SUCCESS in {elapsed:.1f}s — saved {out_path}")


def list_models():
    print("Configured model shortcuts:\n")
    for key, model_id in MODELS.items():
        print(f"  --model {key:<15} -> {model_id}")
    print("\nFull catalog: https://developers.cloudflare.com/workers-ai/models/?task=text-to-image")


def list_remote_models(account_id, api_token):
    print("Querying Cloudflare for text-to-image models available to your account...\n")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"task": "Text-to-Image"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return

    if resp.status_code != 200:
        print(f"FAILED — HTTP {resp.status_code}")
        print(resp.text[:1000])
        return

    data = resp.json()
    if not data.get("success", False):
        print(f"API returned success=false. Errors: {data.get('errors')}")
        return

    results = data.get("result", [])
    if not results:
        print("No text-to-image models returned.")
        return

    for model in results:
        name = model.get("name", "unknown")
        description = model.get("description", "")
        print(f"  {name}")
        if description:
            print(f"      {description[:100]}")
    print(f"\nTotal: {len(results)} model(s)")


def main():
    parser = argparse.ArgumentParser(description="Test Cloudflare Workers AI image generation")
    parser.add_argument("--model", choices=list(MODELS.keys()), default="flux", help="Model to test (default: flux)")
    parser.add_argument(
        "--prompt",
        default="Create a modern travel banner design with a dark navy blue background featuring torn/ripped paper edge effect at top and bottom. On the left side, bold stacked typography reads 'TOP PLACES TO VISIT IN GOA' — 'TOP' in golden yellow, 'PLACES' in smaller yellow text, 'TO VISIT IN' in white, and 'GOA' in large bright cyan/turquoise letters, all in a bold condensed sans-serif font. Include a small yellow arrow icon pointing toward the images. On the right side, display three vertical rounded-rectangle (pill-shaped) photo frames with white borders, slightly overlapping each other and tilted, each containing a different tropical destination photo: a historic red-brick church/fort, a bright blue sky over a tropical beach with palm trees, and a rocky turquoise coastline with palm trees. Add decorative white cloud illustrations overlapping the top and bottom edges of the photo frames. Include white dashed/dotted curved lines flowing through the design connecting the elements, small yellow dot/x patterns in the corners, and a small circular gold-and-black logo badge in the top right corner. Style: clean, modern travel/tourism marketing banner, 3:2 aspect ratio, high contrast, vibrant tropical colors against dark background.",
        help="Text prompt for image generation",
    )
    parser.add_argument("--all", action="store_true", help="Test all configured models in sequence")
    parser.add_argument("--out-dir", default="./cloudflare_image_output", help="Directory to save generated images")
    parser.add_argument("--list-models", action="store_true", help="List configured model shortcuts and exit")
    parser.add_argument(
        "--list-remote",
        action="store_true",
        help="Query Cloudflare API for all text-to-image models available to your account, then exit",
    )
    args = parser.parse_args()

    if args.list_models:
        list_models()
        return

    account_id, api_token = get_credentials()

    if args.list_remote:
        list_remote_models(account_id, api_token)
        return

    if args.all:
        for model_id in MODELS.values():
            generate_image(account_id, api_token, model_id, args.prompt, args.out_dir)
    else:
        generate_image(account_id, api_token, MODELS[args.model], args.prompt, args.out_dir)


if __name__ == "__main__":
    main()