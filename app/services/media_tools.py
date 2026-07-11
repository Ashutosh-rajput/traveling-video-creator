from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from langchain_core.tools import tool

from app.core.config import settings

DEFAULT_LIMIT = 4
MAX_LIMIT = 8
MEDIA_API_TIMEOUT = 8  # seconds – fail fast on slow providers


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def _missing_key(provider: str, env_name: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "error": f"{env_name} is missing. Add it to .env to enable this media tool.",
        "photos": [],
        "videos": [],
    }


def _api_error(provider: str, place_name: str, error: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "place_name": place_name,
        "error": error,
        "photos": [],
        "videos": [],
    }


def _request_json(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=MEDIA_API_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _pexels_photos(place_name: str, limit: int) -> list[dict[str, Any]]:
    data = _request_json(
        "https://api.pexels.com/v1/search",
        params={"query": place_name, "per_page": limit, "orientation": "landscape"},
        headers={"Authorization": settings.pexels_api_key},
    )
    photos = []
    for item in data.get("photos", []):
        src = item.get("src", {})
        photos.append(
            {
                "id": item.get("id"),
                "title": item.get("alt") or place_name,
                "page_url": item.get("url"),
                "image_url": src.get("large2x") or src.get("large") or src.get("original"),
                "thumbnail_url": src.get("tiny") or src.get("small"),
                "creator": item.get("photographer"),
                "creator_url": item.get("photographer_url"),
            }
        )
    return photos


def _pexels_videos(place_name: str, limit: int) -> list[dict[str, Any]]:
    data = _request_json(
        "https://api.pexels.com/v1/videos/search",
        params={"query": place_name, "per_page": limit, "orientation": "landscape"},
        headers={"Authorization": settings.pexels_api_key},
    )
    videos = []
    for item in data.get("videos", []):
        files = sorted(
            item.get("video_files", []),
            key=lambda video: video.get("width") or 0,
            reverse=True,
        )
        best_file = next((video for video in files if video.get("link")), {})
        pictures = item.get("video_pictures", [])
        videos.append(
            {
                "id": item.get("id"),
                "title": item.get("url"),
                "page_url": item.get("url"),
                "video_url": best_file.get("link"),
                "thumbnail_url": pictures[0].get("picture") if pictures else None,
                "duration_seconds": item.get("duration"),
                "creator": item.get("user", {}).get("name"),
                "creator_url": item.get("user", {}).get("url"),
            }
        )
    return videos


@tool
def search_pexels_place_media(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search Pexels for travel photos and videos for a destination or place name."""
    if not settings.pexels_api_key:
        return _missing_key("pexels", "PEXELS_API_KEY")

    limit = _bounded_limit(limit)
    try:
        return {
            "provider": "pexels",
            "place_name": place_name,
            "photos": _pexels_photos(place_name, limit),
            "videos": _pexels_videos(place_name, limit),
            "attribution": "Photos and videos provided by Pexels. Credit creators when possible.",
        }
    except Exception as e:
        return _api_error("pexels", place_name, f"Pexels API error: {e}")


@tool
def search_pixabay_place_media(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search Pixabay for travel photos and videos for a destination or place name."""
    if not settings.pixabay_api_key:
        return _missing_key("pixabay", "PIXABAY_API_KEY")

    limit = _bounded_limit(limit)
    try:
        common_params = {
            "key": settings.pixabay_api_key,
            "q": place_name,
            "per_page": max(3, limit),
            "category": "travel",
            "safesearch": "true",
            "order": "popular",
        }
        photo_data = _request_json(
            "https://pixabay.com/api/",
            params={**common_params, "image_type": "photo", "orientation": "horizontal"},
        )
        video_data = _request_json("https://pixabay.com/api/videos/", params=common_params)

        photos = [
            {
                "id": item.get("id"),
                "title": item.get("tags"),
                "page_url": item.get("pageURL"),
                "image_url": item.get("largeImageURL") or item.get("webformatURL"),
                "thumbnail_url": item.get("previewURL"),
                "creator": item.get("user"),
                "creator_url": (
                    f"https://pixabay.com/users/{item.get('user')}-{item.get('user_id')}/"
                    if item.get("user") and item.get("user_id")
                    else None
                ),
            }
            for item in photo_data.get("hits", [])[:limit]
        ]
        videos = []
        for item in video_data.get("hits", [])[:limit]:
            renditions = item.get("videos", {})
            best_video = (
                renditions.get("large")
                or renditions.get("medium")
                or renditions.get("small")
                or renditions.get("tiny")
                or {}
            )
            videos.append(
                {
                    "id": item.get("id"),
                    "title": item.get("tags"),
                    "page_url": item.get("pageURL"),
                    "video_url": best_video.get("url"),
                    "thumbnail_url": best_video.get("thumbnail"),
                    "duration_seconds": item.get("duration"),
                    "creator": item.get("user"),
                    "creator_url": (
                        f"https://pixabay.com/users/{item.get('user')}-{item.get('user_id')}/"
                        if item.get("user") and item.get("user_id")
                        else None
                    ),
                }
            )

        return {
            "provider": "pixabay",
            "place_name": place_name,
            "photos": photos,
            "videos": videos,
            "attribution": "Images and videos provided by Pixabay.",
        }
    except Exception as e:
        return _api_error("pixabay", place_name, f"Pixabay API error: {e}")


@tool
def search_unsplash_place_photos(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search Unsplash for high-quality travel photos for a destination or place name."""
    if not settings.unsplash_access_key:
        return _missing_key("unsplash", "UNSPLASH_ACCESS_KEY")

    limit = _bounded_limit(limit)
    try:
        data = _request_json(
            "https://api.unsplash.com/search/photos",
            params={
                "query": place_name,
                "per_page": limit,
                "orientation": "landscape",
                "content_filter": "high",
            },
            headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
        )
        photos = []
        for item in data.get("results", []):
            user = item.get("user", {})
            urls = item.get("urls", {})
            links = item.get("links", {})
            photos.append(
                {
                    "id": item.get("id"),
                    "title": item.get("alt_description") or item.get("description") or place_name,
                    "page_url": links.get("html"),
                    "image_url": urls.get("regular") or urls.get("full"),
                    "thumbnail_url": urls.get("thumb") or urls.get("small"),
                    "download_location": links.get("download_location"),
                    "creator": user.get("name"),
                    "creator_url": user.get("links", {}).get("html"),
                }
            )

        return {
            "provider": "unsplash",
            "place_name": place_name,
            "photos": photos,
            "videos": [],
            "attribution": "Photos provided by Unsplash. Trigger download tracking before production downloads.",
        }
    except Exception as e:
        return _api_error("unsplash", place_name, f"Unsplash API error: {e}")


@tool
def search_all_place_media(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search ALL media providers (Pexels, Pixabay, Unsplash) in parallel for a destination.
    Use this instead of calling each provider separately to save time."""
    limit = _bounded_limit(limit)
    combined_photos: list[dict[str, Any]] = []
    combined_videos: list[dict[str, Any]] = []
    errors: list[str] = []

    def _run_pexels():
        return search_pexels_place_media.invoke({"place_name": place_name, "limit": limit})

    def _run_pixabay():
        return search_pixabay_place_media.invoke({"place_name": place_name, "limit": limit})

    def _run_unsplash():
        return search_unsplash_place_photos.invoke({"place_name": place_name, "limit": limit})

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Media Search] Starting parallel media search for: '{place_name}'")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_run_pexels): "pexels",
            pool.submit(_run_pixabay): "pixabay",
            pool.submit(_run_unsplash): "unsplash",
        }
        for fut in as_completed(futures):
            provider = futures[fut]
            try:
                result = fut.result()
                if isinstance(result, dict):
                    if result.get("error"):
                        errors.append(result["error"])
                    combined_photos.extend(result.get("photos", []))
                    combined_videos.extend(result.get("videos", []))
            except Exception as e:
                errors.append(f"{provider}: {e}")

    # Deduplicate videos (matching by video_url)
    unique_videos = []
    seen_video_urls = set()
    for vid in combined_videos:
        url = vid.get("video_url")
        if url and url not in seen_video_urls:
            unique_videos.append(vid)
            seen_video_urls.add(url)

    # Deduplicate photos (matching by image_url)
    unique_photos = []
    seen_photo_urls = set()
    for pic in combined_photos:
        url = pic.get("image_url")
        if url and url not in seen_photo_urls:
            unique_photos.append(pic)
            seen_photo_urls.add(url)

    final_videos = []
    final_photos = []

    # Filtering rules:
    # - If >= 2 clips found: keep 2 clips, 0 photos.
    # - If exactly 1 clip found: keep 1 clip, 2 photos.
    # - If 0 clips found: keep 0 clips, 4 photos.
    num_clips_found = len(unique_videos)
    if num_clips_found >= 2:
        final_videos = unique_videos[:2]
        final_photos = []
        rule_desc = "Kept 2 clips, 0 photos (2+ clips found)"
    elif num_clips_found == 1:
        final_videos = unique_videos[:1]
        final_photos = unique_photos[:2]
        rule_desc = "Kept 1 clip, 2 photos (1 clip found)"
    else:
        final_videos = []
        final_photos = unique_photos[:4]
        rule_desc = "Kept 0 clips, 4 photos (0 clips found)"

    logger.info(
        f"[Media Search] '{place_name}' search finished. "
        f"Found {num_clips_found} unique clips, {len(unique_photos)} unique photos. "
        f"Rule applied: {rule_desc}"
    )

    return {
        "provider": "combined",
        "place_name": place_name,
        "photos": final_photos,
        "videos": final_videos,
        "errors": errors if errors else None,
    }


def get_media_tools() -> list[Any]:
    return [
        search_all_place_media,
    ]

