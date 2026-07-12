from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
import contextvars
import re

import httpx
from langchain_core.tools import tool

from app.core.config import settings

# Thread-local / Context-local tracking for the active city query
current_city_var: contextvars.ContextVar[str] = contextvars.ContextVar("current_city", default="")

def set_current_city(city_name: str) -> None:
    current_city_var.set(city_name)

def get_current_city() -> str:
    return current_city_var.get()

DEFAULT_LIMIT = 6
MAX_LIMIT = 10
MEDIA_API_TIMEOUT = 8  # seconds – fail fast on slow providers


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


_GENERIC_LOCATION_TERMS = frozenset({
    "beach", "city", "falls", "fort", "garden", "india", "lake", "museum",
    "national", "palace", "park", "river", "temple", "waterfall", "zoo",
})


def _asset_matches_place(asset: dict[str, Any], place_name: str) -> bool:
    """Reject provider search results that are clearly unrelated to the requested place."""
    title = str(asset.get("title") or "").lower()
    page_url = str(asset.get("page_url") or "").lower()
    creator = str(asset.get("creator") or "").lower()
    searchable_text = f"{title} {page_url} {creator}"
    
    place_lower = place_name.lower().strip()
    
    # 1. Custom guard for "Bee Falls"
    if "bee" in place_lower and "falls" in place_lower:
        words = set(re.findall(r"[a-z0-9]+", searchable_text))
        has_insect = any(w in words for w in ["bee", "bees", "beehive", "beehives", "honey", "apiary", "insect", "insects", "pasture", "wasp", "wasps", "hornet", "hornets"])
        has_falls = any(w in words for w in ["falls", "waterfall", "waterfalls", "cascade", "cascades", "pachmarhi"])
        if has_insect and not has_falls:
            return False

    # 2. Custom guard for "Jata Shankar Caves" / Caves
    if "caves" in place_lower or "cave" in place_lower or "shankar" in place_lower:
        words = set(re.findall(r"[a-z0-9]+", searchable_text))
        has_cave_theme = any(w in words for w in ["cave", "caves", "temple", "shankar", "shiva", "shiv", "rock", "stone", "deity", "pachmarhi", "jata"])
        if not has_cave_theme:
            return False

    place_terms = {
        term
        for term in re.findall(r"[a-z0-9]+", place_lower)
        if len(term) >= 3 and term not in _GENERIC_LOCATION_TERMS
    }
    if not place_terms:
        return True

    return any(term in searchable_text for term in place_terms)


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
def search_wikimedia_place_media(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search Wikimedia Commons for open-source travel photos and videos for a destination or place name.
    No API keys are required for this tool."""
    limit = _bounded_limit(limit)
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": place_name,
            "gsrlimit": limit,
            "gsrnamespace": 6,  # File namespace
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "format": "json"
        }
        headers = {
            "User-Agent": "VoyageurTravelVideoCreator/1.0 (contact@voyageur.ai)"
        }
        
        with httpx.Client(timeout=MEDIA_API_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
        pages = data.get("query", {}).get("pages", {})
        photos = []
        videos = []
        
        for page_id, page in pages.items():
            title = page.get("title", "")
            clean_title = title.replace("File:", "")
            page_url = f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}"
            
            imageinfo_list = page.get("imageinfo", [])
            if not imageinfo_list:
                continue
                
            imageinfo = imageinfo_list[0]
            file_url = imageinfo.get("url")
            mime = imageinfo.get("mime", "")
            
            if not file_url:
                continue
                
            extmetadata = imageinfo.get("extmetadata", {})
            artist_raw = extmetadata.get("Artist", {}).get("value", "")
            creator = re.sub(r"<[^>]*>", "", artist_raw).strip() if artist_raw else "Wikimedia Contributor"
            
            asset = {
                "id": page_id,
                "title": clean_title,
                "page_url": page_url,
                "creator": creator,
                "creator_url": page_url
            }
            
            is_video = mime.startswith("video/") or any(
                file_url.lower().endswith(ext)
                for ext in [".mp4", ".webm", ".ogv", ".ogg", ".mov", ".avi", ".mkv"]
            )
            
            if is_video:
                videos.append({
                    **asset,
                    "video_url": file_url,
                    "thumbnail_url": None,
                    "duration_seconds": None
                })
            else:
                photos.append({
                    **asset,
                    "image_url": file_url,
                    "thumbnail_url": file_url
                })
                
        return {
            "provider": "wikimedia",
            "place_name": place_name,
            "photos": photos,
            "videos": videos,
            "attribution": "Photos and videos provided by Wikimedia Commons under open licensing."
        }
    except Exception as e:
        return _api_error("wikimedia", place_name, f"Wikimedia Commons API error: {e}")


@tool
def search_all_place_media(place_name: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Search ALL media providers in parallel for a destination, using the query sanitization
    and selection pipeline (preferring videos, falling back to photos if needed)."""
    limit = _bounded_limit(limit)
    combined_photos: list[dict[str, Any]] = []
    combined_videos: list[dict[str, Any]] = []
    errors: list[str] = []

    # Query sanitization: strip the active city name from the search query to avoid bad search results
    search_query = place_name
    city = get_current_city()
    if city:
        city_pattern = re.compile(rf"\b{re.escape(city)}\b", re.IGNORECASE)
        search_query = city_pattern.sub("", place_name).strip()
        # Clean extra spaces
        search_query = re.sub(r"\s+", " ", search_query)
        if not search_query:
            search_query = place_name

    def _run_pexels():
        return search_pexels_place_media.invoke({"place_name": search_query, "limit": limit})

    def _run_pixabay():
        return search_pixabay_place_media.invoke({"place_name": search_query, "limit": limit})

    def _run_unsplash():
        return search_unsplash_place_photos.invoke({"place_name": search_query, "limit": limit})

    def _run_wikimedia():
        return search_wikimedia_place_media.invoke({"place_name": search_query, "limit": limit})

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Media Search] Starting parallel media search for query: '{search_query}' (original place name: '{place_name}')")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_run_pexels): "pexels",
            pool.submit(_run_pixabay): "pixabay",
            pool.submit(_run_unsplash): "unsplash",
            pool.submit(_run_wikimedia): "wikimedia",
        }
        for fut in as_completed(futures):
            provider = futures[fut]
            try:
                result = fut.result()
                if isinstance(result, dict):
                    if result.get("error"):
                        errors.append(result["error"])
                    combined_photos.extend(
                        [{**asset, "provider": provider} for asset in result.get("photos", [])]
                    )
                    combined_videos.extend(
                        [{**asset, "provider": provider} for asset in result.get("videos", [])]
                    )
            except Exception as e:
                errors.append(f"{provider}: {e}")

    # Keep results only when their own metadata supports the location
    matched_photos = [asset for asset in combined_photos if _asset_matches_place(asset, place_name)]
    matched_videos = [asset for asset in combined_videos if _asset_matches_place(asset, place_name)]
    
    rejected_count = len(combined_photos) + len(combined_videos) - len(matched_photos) - len(matched_videos)
    if rejected_count:
        logger.info("[Media Search] Rejected %s metadata-mismatched assets for '%s'.", rejected_count, place_name)

    # Separate matched actual videos by provider for prioritization
    pexels_vids = [v for v in matched_videos if v.get("provider") == "pexels"]
    pixabay_vids = [v for v in matched_videos if v.get("provider") == "pixabay"]
    wikimedia_vids = [v for v in matched_videos if v.get("provider") == "wikimedia"]
    
    # Priority ordered actual videos pool
    actual_videos_pool = []
    seen_vid_urls = set()
    for vid in (pexels_vids + pixabay_vids + wikimedia_vids):
        vurl = vid.get("video_url")
        if vurl and vurl not in seen_vid_urls:
            actual_videos_pool.append(vid)
            seen_vid_urls.add(vurl)

    # Separate matched photos by provider for prioritization
    pexels_pics = [p for p in matched_photos if p.get("provider") == "pexels"]
    pixabay_pics = [p for p in matched_photos if p.get("provider") == "pixabay"]
    wikimedia_pics = [p for p in matched_photos if p.get("provider") == "wikimedia"]
    unsplash_pics = [p for p in matched_photos if p.get("provider") == "unsplash"]
    
    # Priority ordered photos pool
    photos_pool = []
    seen_pic_urls = set()
    for pic in (pexels_pics + pixabay_pics + wikimedia_pics + unsplash_pics):
        purl = pic.get("image_url")
        if purl and purl not in seen_pic_urls:
            photos_pool.append(pic)
            seen_pic_urls.add(purl)

    final_videos = []
    final_photos = []
    used_photo_urls = set()

    # 1. Selection Pipeline - Video Clips (we want exactly 2)
    # First, take actual videos
    for vid in actual_videos_pool[:2]:
        final_videos.append(vid)

    # If not enough actual videos, fill using photos formatted as video clips
    if len(final_videos) < 2:
        for pic in photos_pool:
            purl = pic.get("image_url")
            if purl not in used_photo_urls:
                fake_vid = {
                    "id": pic.get("id"),
                    "title": pic.get("title"),
                    "page_url": pic.get("page_url"),
                    "video_url": purl,
                    "thumbnail_url": pic.get("thumbnail_url"),
                    "duration_seconds": 4.0,  # default duration for images
                    "creator": pic.get("creator"),
                    "creator_url": pic.get("creator_url"),
                    "provider": pic.get("provider")
                }
                final_videos.append(fake_vid)
                used_photo_urls.add(purl)
                if len(final_videos) >= 2:
                    break

    # 2. Selection Pipeline - Photos (we want exactly 3)
    for pic in photos_pool:
        purl = pic.get("image_url")
        if purl not in used_photo_urls:
            final_photos.append(pic)
            used_photo_urls.add(purl)
            if len(final_photos) >= 3:
                break

    rule_desc = f"Extracted {len(final_videos)} video clips (including {len(used_photo_urls)} photo fallbacks) and {len(final_photos)} photos"
    logger.info(
        f"[Media Search] '{place_name}' search finished. "
        f"Actual videos in pool: {len(actual_videos_pool)}, photos in pool: {len(photos_pool)}. "
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
        search_wikimedia_place_media,
    ]
