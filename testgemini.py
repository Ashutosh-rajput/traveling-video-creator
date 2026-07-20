"""
Test script for Gemini image generation.

NOTE: As of mid-2026, Google is retiring the Imagen 4 endpoints
(imagen-4.0-generate-001 etc.) for new API accounts. They are fully
shutting down Aug 17, 2026. The recommended replacement is
Gemini 3.1 Flash Image ("Nano Banana 2"), which uses the
generateContent API instead of generateImages.

This script tries the new Gemini image models first, and falls back
to older Imagen 3 models (still available) if those aren't enabled
on your account/quota.

Setup:
    pip install google-genai --break-system-packages
    export GEMINI_API_KEY="your-api-key-here"   # from Google AI Studio

Usage:
    python test_imagen4.py                       # default (Gemini 3.1 Flash Image)
    python test_imagen4.py --variant nano2        # Nano Banana 2 (Gemini 3.1 Flash Image)
    python test_imagen4.py --variant nano2lite    # Nano Banana 2 Lite
    python test_imagen4.py --variant nanopro      # Nano Banana Pro (Gemini 3 Pro Image)
    python test_imagen4.py --variant imagen3      # Imagen 3.0 (older, still active)
    python test_imagen4.py --prompt "a red fox in snow, watercolor style"
"""

import argparse
import os
import sys
import time
from datetime import datetime

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Missing dependency. Run: pip install google-genai --break-system-packages")
    sys.exit(1)

# Gemini native image-gen models use generateContent (chat-style)
GEMINI_IMAGE_MODELS = {
    "flash25": "gemini-2.5-flash-image",
    "nano2": "gemini-3.1-flash-image",
    "nano2lite": "gemini-3.1-flash-lite-image",
    "nanopro": "gemini-3-pro-image",
    "nanoprepreview": "nano-banana-pro-preview",
}

# Older Imagen models still use generateImages and are not yet retired
IMAGEN_MODELS = {
    "imagen3": "imagen-3.0-generate-002",
    "imagen3fast": "imagen-3.0-fast-generate-001",
}


def get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable first.")
        print('  export GEMINI_API_KEY="your-key-here"')
        sys.exit(1)
    return genai.Client(api_key=api_key)


def test_generate_imagen(client: genai.Client, model_id: str, prompt: str, out_dir: str) -> None:
    """For older Imagen 3.x models using the generateImages API."""
    print(f"\n--- Testing model: {model_id} (generateImages API) ---")
    print(f"Prompt: {prompt}")
    start = time.time()

    try:
        response = client.models.generate_images(
            model=model_id,
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
    except Exception as e:
        print(f"FAILED after {time.time() - start:.1f}s")
        print(f"Error: {e}")
        return

    elapsed = time.time() - start
    os.makedirs(out_dir, exist_ok=True)

    if not response.generated_images:
        print(f"No images returned (took {elapsed:.1f}s). Response: {response}")
        return

    for i, img in enumerate(response.generated_images):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"{model_id}_{ts}_{i}.png")
        img.image.save(out_path)
        print(f"Saved: {out_path}")

    print(f"SUCCESS in {elapsed:.1f}s — {len(response.generated_images)} image(s) generated")


def test_generate_gemini_image(client: genai.Client, model_id: str, prompt: str, out_dir: str) -> None:
    """For Gemini native image models (Nano Banana family) using generateContent API."""
    print(f"\n--- Testing model: {model_id} (generateContent API) ---")
    print(f"Prompt: {prompt}")
    start = time.time()

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
    except Exception as e:
        print(f"FAILED after {time.time() - start:.1f}s")
        print(f"Error: {e}")
        return

    elapsed = time.time() - start
    os.makedirs(out_dir, exist_ok=True)

    saved_any = False
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(out_dir, f"{model_id}_{ts}.png")
            with open(out_path, "wb") as f:
                f.write(part.inline_data.data)
            print(f"Saved: {out_path}")
            saved_any = True
        elif getattr(part, "text", None):
            print(f"Model text response: {part.text}")

    if saved_any:
        print(f"SUCCESS in {elapsed:.1f}s")
    else:
        print(f"No image returned (took {elapsed:.1f}s). Full response: {response}")


def list_available_models(client: genai.Client) -> None:
    print("Models available to your API key that support image generation:\n")
    found_any = False
    for model in client.models.list():
        actions = getattr(model, "supported_actions", None) or []
        if any("generateImages" in a or "generateContent" in a for a in actions):
            # only show ones likely relevant to images
            name = model.name
            if "image" in name.lower() or "imagen" in name.lower() or "nano" in name.lower():
                found_any = True
                print(f"  {name}  (actions: {actions})")
    if not found_any:
        print("  No image-capable models found — printing ALL models instead:\n")
        for model in client.models.list():
            print(f"  {model.name}")


def main():
    all_choices = list(GEMINI_IMAGE_MODELS.keys()) + list(IMAGEN_MODELS.keys())

    parser = argparse.ArgumentParser(description="Test Gemini/Imagen image generation")
    parser.add_argument(
        "--variant",
        choices=all_choices,
        default="flash25",
        help="Which model to test (default: flash25 = Gemini 2.5 Flash Image)",
    )
    parser.add_argument(
        "--prompt",
        default="A minimalist logo of a mountain, flat design, vector style",
        help="Text prompt for image generation",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test every available model in sequence (uses up quota faster)",
    )
    parser.add_argument(
        "--out-dir",
        default="./image_test_output",
        help="Directory to save generated images",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List models actually available to your API key, then exit",
    )
    args = parser.parse_args()

    client = get_client()

    if args.list:
        list_available_models(client)
        return

    def run(variant: str) -> None:
        if variant in GEMINI_IMAGE_MODELS:
            test_generate_gemini_image(client, GEMINI_IMAGE_MODELS[variant], args.prompt, args.out_dir)
        else:
            test_generate_imagen(client, IMAGEN_MODELS[variant], args.prompt, args.out_dir)

    if args.all:
        for variant in all_choices:
            run(variant)
    else:
        run(args.variant)


if __name__ == "__main__":
    main()