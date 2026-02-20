from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import asyncio

URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

async def capture_bootstrap_session_async(url=URL, headless=True, timeout_ms=5000):
    """Async version: Captures the bootstrapSession URL by intercepting network requests."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        found = {"url": None}
        
        def on_request(req):
            u = req.url
            if "bootstrapSession/sessions/" in u:
                found["url"] = u
                print("FOUND bootstrapSession URL:\n", u, flush=True)

        page.on("request", on_request)
        
        # Start navigation but don't wait for full networkidle
        # Just wait for domcontentloaded and a bit for the bootstrap session to appear
        try:
            await asyncio.wait_for(
                page.goto(url, wait_until="domcontentloaded"),
                timeout=timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            print("Page load timed out (expected for heavy dashboard), continuing...", flush=True)
        except Exception as e:
            print(f"Navigation error: {e}", flush=True)
        
        # Wait a bit for the bootstrap session request to appear
        for i in range(10):
            if found["url"]:
                break
            await asyncio.sleep(0.2)
        
        # If still not found, try interacting with the page
        if not found["url"]:
            print("Bootstrap session not found yet, trying interaction...", flush=True)
            await page.mouse.move(800, 400)
            await page.wait_for_timeout(500)
            
            # Wait more for response
            for i in range(10):
                if found["url"]:
                    break
                await asyncio.sleep(0.2)

        await browser.close()

        if not found["url"]:
            raise RuntimeError("Did not capture bootstrapSession URL. Try headless=False to debug.")
        
        return found["url"]

def capture_bootstrap_session(url=URL, headless=True):
    """Sync wrapper for capture_bootstrap_session_async. Works in Jupyter notebooks."""
    try:
        # Try to get the running event loop (common in Jupyter)
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create one
        return asyncio.run(capture_bootstrap_session_async(url, headless))
    else:
        # Running loop exists (Jupyter), use nest_asyncio workaround or return coroutine
        # For Jupyter, we'll create a task
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.run(capture_bootstrap_session_async(url, headless))

def main():
    bootstrap_url = capture_bootstrap_session()
    print("Bootstrap URL captured:", bootstrap_url)

if __name__ == "__main__":
    main()