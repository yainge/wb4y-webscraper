import asyncio
from playwright.async_api import async_playwright
import json

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

async def scrape_with_playwright_async() -> list:
    """
    Extract data by hovering over the Tableau visualization and capturing tooltips.
    """
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        
        print("Loading Tableau dashboard...")
        await page.goto(VIEW_URL, wait_until="domcontentloaded", timeout=30000)
        
        print("Waiting for visualization to render...")
        try:
            await page.wait_for_selector("#svg-spinner", state="hidden", timeout=60000)
            print("[OK] Visualization loaded")
        except:
            print("[WARN] Spinner timeout, proceeding...")
        
        await page.wait_for_timeout(5000)
        
        # Get viewport dimensions
        viewport = page.viewport_size
        print(f"Viewport: {viewport['width']}x{viewport['height']}")
        
        # Scan the main content area where the chart should be
        # Typical Tableau public layout: chart is centered in the main viewing area
        x_start = 100
        x_end = viewport['width'] - 100
        y_start = 150
        y_end = viewport['height'] - 150
        
        x_step = 40
        y_step = 30
        
        print(f"Scanning visualization area: ({x_start},{y_start}) to ({x_end},{y_end})")
        
        scan_count = 0
        unique_contents = set()
        
        for y in range(int(y_start), int(y_end), int(y_step)):
            for x in range(int(x_start), int(x_end), int(x_step)):
                scan_count += 1
                
                try:
                    # Hover over position
                    await page.mouse.move(x, y)
                    await page.wait_for_timeout(800)
                    
                    # Extract visible text/tooltip content
                    content = await page.evaluate(f"""
                        () => {{
                            // First try to find tooltip
                            const tooltip = document.querySelector('[role="tooltip"]');
                            if (tooltip) {{
                                const text = tooltip.innerText || tooltip.textContent;
                                if (text && text.length > 20) {{
                                    return text.trim();
                                }}
                            }}
                            
                            // Otherwise get visible SVG text around this area
                            const elements = document.querySelectorAll('text, tspan, [class*="text"]');
                            const texts = [];
                            elements.forEach(el => {{
                                const txt = el.textContent.trim();
                                if (txt && txt.length > 2 && txt.length < 150 && !txt.includes('&') && !txt.includes('<')) {{
                                    texts.push(txt);
                                }}
                            }});
                            
                            if (texts.length > 0) {{
                                return texts.slice(0, 5).join(' | ');
                            }}
                            return '';
                        }}
                    """)
                    
                    if content and len(content) > 15:
                        content_hash = hash(content) % 100000
                        
                        # Only record unique contents
                        if content_hash not in unique_contents:
                            unique_contents.add(content_hash)
                            results.append({
                                "x": x,
                                "y": y,
                                "content": content
                            })
                            print(f"[{len(results)}] ({x},{y}): {content[:70]}...")
                    
                    if scan_count % 100 == 0:
                        print(f"  Progress: {scan_count} scans, {len(results)} unique data points found")
                
                except Exception as e:
                    pass
        
        await browser.close()
    
    print(f"\n[OK] Completed {scan_count} scans")
    print(f"[OK] Found {len(results)} unique data points")
    
    return results

def main():
    print("Launching Tableau data extractor...\n")
    results = asyncio.run(scrape_with_playwright_async())
    
    if results:
        # Save to JSON
        with open("extracted_data.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to extracted_data.json")
        
        # Show unique contents
        print("\nUnique data points found:")
        for i, r in enumerate(results[:10], 1):
            print(f"  {i}. {r['content'][:80]}")
    else:
        print("\nNo data points extracted")
    
    return results

if __name__ == "__main__":
    main()