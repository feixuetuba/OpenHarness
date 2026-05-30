"""Simple web search tool."""

from __future__ import annotations

import html
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.utils.network_guard import NetworkGuardError, fetch_public_http_response


class WebSearchToolInput(BaseModel):
    """Arguments for a web search."""

    query: str = Field(description="Search query")
    max_results: int = Field(default=5, ge=1, le=10, description="Maximum number of results")
    search_url: str | None = Field(
        default=None,
        description="Optional override for the HTML search endpoint, useful for private search backends or testing.",
    )


class WebSearchTool(BaseTool):
    """Run a web search and return compact top results."""

    name = "web_search"
    description = "Search the web and return compact top results with titles, URLs, and snippets."
    input_model = WebSearchToolInput

    def is_read_only(self, arguments: WebSearchToolInput) -> bool:
        del arguments
        return True

    async def execute(
        self,
        arguments: WebSearchToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        del context
        endpoint = arguments.search_url or os.environ.get("OPENHARNESS_WEB_SEARCH_URL")
        
        if not endpoint:
            try:
                from openharness.config import load_settings
                settings = load_settings()
                search_config = settings.search_api
                
                if search_config.enabled:
                    provider = search_config.provider
                    base_url = search_config.base_url
                    
                    if provider == "tavily":
                        return await self._execute_tavily_search(arguments, search_config)
                    elif provider == "bing":
                        return await self._execute_bing_search(arguments, search_config)
                    elif provider == "google":
                        return await self._execute_google_search(arguments, search_config)
                    elif provider == "custom" and base_url:
                        endpoint = base_url
                    else:
                        endpoint = "https://html.duckduckgo.com/html/"
                else:
                    endpoint = "https://html.duckduckgo.com/html/"
            except Exception:
                endpoint = "https://html.duckduckgo.com/html/"
        
        try:
            response = await fetch_public_http_response(
                endpoint,
                params={"q": arguments.query},
                headers={"User-Agent": "OpenHarness/0.1"},
                timeout=20.0,
            )
            response.raise_for_status()
        except (httpx.HTTPError, NetworkGuardError) as exc:
            return ToolResult(output=f"web_search failed: {exc}", is_error=True)

        results = _parse_search_results(response.text, limit=arguments.max_results)
        if not results:
            return ToolResult(output="No search results found.", is_error=True)

        lines = [f"Search results for: {arguments.query}"]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            if result["snippet"]:
                lines.append(f"   {result['snippet']}")
        return ToolResult(output="\n".join(lines))

    async def _execute_tavily_search(
        self,
        arguments: WebSearchToolInput,
        search_config,
    ) -> ToolResult:
        api_key = search_config.api_key
        if not api_key:
            return ToolResult(output="web_search failed: Tavily API key not configured", is_error=True)
        
        use_sdk = getattr(search_config, 'use_sdk', True)
        
        if use_sdk:
            return await self._execute_tavily_with_sdk(arguments, api_key)
        else:
            return await self._execute_tavily_with_http(arguments, search_config)
    
    async def _execute_tavily_with_sdk(
        self,
        arguments: WebSearchToolInput,
        api_key: str,
    ) -> ToolResult:
        try:
            from tavily import TavilyClient
        except ImportError:
            return ToolResult(
                output="web_search failed: tavily-python SDK not installed. Install with: pip install tavily-python",
                is_error=True,
            )
        
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=arguments.query,
                max_results=arguments.max_results,
            )
        except Exception as exc:
            return ToolResult(output=f"web_search failed: {exc}", is_error=True)
        
        results = response.get("results", [])
        if not results:
            return ToolResult(output="No search results found.", is_error=True)
        
        lines = [f"Search results for: {arguments.query}"]
        for index, result in enumerate(results[:arguments.max_results], start=1):
            lines.append(f"{index}. {result.get('title', 'N/A')}")
            lines.append(f"   URL: {result.get('url', 'N/A')}")
            content = result.get("content", "")
            if content:
                lines.append(f"   {content[:300]}")
        return ToolResult(output="\n".join(lines))
    
    async def _execute_tavily_with_http(
        self,
        arguments: WebSearchToolInput,
        search_config,
    ) -> ToolResult:
        import httpx
        from openharness.utils.network_guard import NetworkGuardError
        
        api_key = search_config.api_key
        endpoint = search_config.base_url or "https://api.tavily.com/search"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    json={
                        "query": arguments.query,
                        "api_key": api_key,
                        "max_results": arguments.max_results,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=20.0,
                )
                response.raise_for_status()
        except (httpx.HTTPError, NetworkGuardError) as exc:
            return ToolResult(output=f"web_search failed: {exc}", is_error=True)
        
        data = response.json()
        results = data.get("results", [])
        if not results:
            return ToolResult(output="No search results found.", is_error=True)
        
        lines = [f"Search results for: {arguments.query}"]
        for index, result in enumerate(results[:arguments.max_results], start=1):
            lines.append(f"{index}. {result.get('title', 'N/A')}")
            lines.append(f"   URL: {result.get('url', 'N/A')}")
            content = result.get("content", "")
            if content:
                lines.append(f"   {content[:300]}")
        return ToolResult(output="\n".join(lines))

    async def _execute_bing_search(
        self,
        arguments: WebSearchToolInput,
        search_config,
    ) -> ToolResult:
        import httpx
        from openharness.utils.network_guard import NetworkGuardError
        
        api_key = search_config.api_key
        if not api_key:
            return ToolResult(output="web_search failed: Bing API key not configured", is_error=True)
        
        endpoint = search_config.base_url or "https://api.bing.microsoft.com/v7.0/search"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    endpoint,
                    params={"q": arguments.query, "count": arguments.max_results},
                    headers={"Ocp-Apim-Subscription-Key": api_key},
                    timeout=20.0,
                )
                response.raise_for_status()
        except (httpx.HTTPError, NetworkGuardError) as exc:
            return ToolResult(output=f"web_search failed: {exc}", is_error=True)
        
        data = response.json()
        web_pages = data.get("webPages", {})
        results = web_pages.get("value", [])
        if not results:
            return ToolResult(output="No search results found.", is_error=True)
        
        lines = [f"Search results for: {arguments.query}"]
        for index, result in enumerate(results[:arguments.max_results], start=1):
            lines.append(f"{index}. {result.get('name', 'N/A')}")
            lines.append(f"   URL: {result.get('url', 'N/A')}")
            snippet = result.get("snippet", "")
            if snippet:
                lines.append(f"   {snippet}")
        return ToolResult(output="\n".join(lines))

    async def _execute_google_search(
        self,
        arguments: WebSearchToolInput,
        search_config,
    ) -> ToolResult:
        import httpx
        from openharness.utils.network_guard import NetworkGuardError
        
        api_key = search_config.api_key
        if not api_key:
            return ToolResult(output="web_search failed: Google API key not configured", is_error=True)
        
        endpoint = search_config.base_url or "https://www.googleapis.com/customsearch/v1"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    endpoint,
                    params={
                        "q": arguments.query,
                        "key": api_key,
                        "cx": os.environ.get("GOOGLE_SEARCH_CX", ""),
                        "num": min(arguments.max_results, 10),
                    },
                    timeout=20.0,
                )
                response.raise_for_status()
        except (httpx.HTTPError, NetworkGuardError) as exc:
            return ToolResult(output=f"web_search failed: {exc}", is_error=True)
        
        data = response.json()
        results = data.get("items", [])
        if not results:
            return ToolResult(output="No search results found.", is_error=True)
        
        lines = [f"Search results for: {arguments.query}"]
        for index, result in enumerate(results[:arguments.max_results], start=1):
            lines.append(f"{index}. {result.get('title', 'N/A')}")
            lines.append(f"   URL: {result.get('link', 'N/A')}")
            snippet = result.get("snippet", "")
            if snippet:
                lines.append(f"   {snippet}")
        return ToolResult(output="\n".join(lines))


def _parse_search_results(body: str, *, limit: int) -> list[dict[str, str]]:
    snippets = [
        _clean_html(match.group("snippet"))
        for match in re.finditer(
            r'<(?:a|div|span)[^>]+class="[^"]*(?:result__snippet|result-snippet)[^"]*"[^>]*>(?P<snippet>.*?)</(?:a|div|span)>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]

    results: list[dict[str, str]] = []
    anchor_matches = re.finditer(
        r"<a(?P<attrs>[^>]+)>(?P<title>.*?)</a>",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for index, match in enumerate(anchor_matches):
        attrs = match.group("attrs")
        class_match = re.search(r'class="(?P<class>[^"]+)"', attrs, flags=re.IGNORECASE)
        if class_match is None:
            continue
        class_names = class_match.group("class")
        if "result__a" not in class_names and "result-link" not in class_names:
            continue
        href_match = re.search(r'href="(?P<href>[^"]+)"', attrs, flags=re.IGNORECASE)
        if href_match is None:
            continue
        title = _clean_html(match.group("title"))
        url = _normalize_result_url(href_match.group("href"))
        snippet = snippets[index] if index < len(snippets) else ""
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _normalize_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else raw_url
    return raw_url


def _clean_html(fragment: str) -> str:
    text = re.sub(r"(?s)<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
