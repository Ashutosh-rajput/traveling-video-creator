import os
import sys
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("traveling-vedio-fastapi-gemma")

# Add the project directory to sys.path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.agent import get_agent_service
from app.schemas.chat import ChatRequest
from app.services.media_tools import (
    search_pexels_place_media,
    search_pixabay_place_media,
    search_unsplash_place_photos,
)

@mcp.tool()
async def chat_with_agent(message: str, system_prompt: str | None = None) -> str:
    """
    Chat with the Gemma-powered travel agent.
    Ask for itineraries, travel planning, or general travel recommendations.
    This agent also has access to media search tools to find photos/videos.
    """
    agent_service = get_agent_service()
    payload = ChatRequest(message=message, system_prompt=system_prompt)
    response = await agent_service.invoke(payload)
    return response.answer

@mcp.tool()
def search_pexels(place_name: str, limit: int = 6) -> dict:
    """
    Search Pexels for photos and videos of a destination or place name.
    """
    # Call the tool function directly (stripping LangChain wrapper if necessary, or calling it)
    # The LangChain tool can be called directly or via its wrapped function
    fn = getattr(search_pexels_place_media, "func", search_pexels_place_media)
    return fn(place_name=place_name, limit=limit)

@mcp.tool()
def search_pixabay(place_name: str, limit: int = 6) -> dict:
    """
    Search Pixabay for photos and videos of a destination or place name.
    """
    fn = getattr(search_pixabay_place_media, "func", search_pixabay_place_media)
    return fn(place_name=place_name, limit=limit)

@mcp.tool()
def search_unsplash(place_name: str, limit: int = 6) -> dict:
    """
    Search Unsplash for high-quality photos of a destination or place name.
    """
    fn = getattr(search_unsplash_place_photos, "func", search_unsplash_place_photos)
    return fn(place_name=place_name, limit=limit)

if __name__ == "__main__":
    mcp.run(transport="stdio")
