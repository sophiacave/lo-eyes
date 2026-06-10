"""lo-eyes MCP Server -- Visual frontend accessibility inspector.

Tools:
  eyes_screenshot  -- viewport screenshot at any device preset
  eyes_scan        -- auto-chunk full page into readable pieces
  eyes_audit       -- responsive + a11y audit across all viewports
  eyes_compare     -- visual regression: pixel-diff vs saved baseline
  eyes_devices     -- list available device presets
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lo-eyes")

BASE_URL = os.environ.get("LO_EYES_BASE_URL", "")
SCREENSHOT_DIR = Path(os.environ.get("LO_EYES_SCREENSHOT_DIR", "./screenshots"))
SCREENSHOT_DIR.mkdir(exist_ok=True)
BASELINE_DIR = Path(os.environ.get("LO_EYES_BASELINE_DIR", "./baselines"))

DEVICES = {
    "iphone-se": {"width": 375, "height": 667, "scale": 1, "mobile": True},
    "iphone-14": {"width": 390, "height": 844, "scale": 1, "mobile": True},
    "ipad": {"width": 768, "height": 1024, "scale": 1, "mobile": True},
    "laptop": {"width": 1280, "height": 800, "scale": 1, "mobile": False},
    "desktop": {"width": 1440, "height": 900, "scale": 1, "mobile": False},
}


def _get_playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _slug(url: str) -> str:
    if url.startswith(("http://", "https://")):
        path = urlparse(url).path
    else:
        path = url if url.startswith("/") else f"/{url.lstrip('/')}"
    return "home" if path.strip("/") == "" else path.strip("/").replace("/", "-")


def _url(path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path.rstrip("/") + "/" if not path.endswith("/") else path
    if not BASE_URL:
        raise ValueError("Set LO_EYES_BASE_URL env var or pass full URLs")
    p = path if path.startswith("/") else f"/{path.lstrip('/')}"
    return f"{BASE_URL}{p}"


def _run_audit_js():
    """JavaScript audit code injected into pages. 9 WCAG checks."""
    return """() => {
        const vw = window.innerWidth;
        const issues = [];

        // === RESPONSIVE CHECKS ===

        // 1. Overflow (skip elements clipped by scroll parents)
        document.querySelectorAll('*').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.right > vw + 1 && rect.width > 0) {
                let parent = el.parentElement, clipped = false;
                while (parent) {
                    const ov = getComputedStyle(parent).overflowX;
                    if (ov === 'auto' || ov === 'hidden' || ov === 'scroll') {
                        const pr = parent.getBoundingClientRect();
                        if (pr.right <= vw + 1) { clipped = true; break; }
                    }
                    parent = parent.parentElement;
                }
                if (!clipped) {
                    const tag = el.tagName.toLowerCase();
                    const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                    issues.push({ type: 'overflow', severity: 'high',
                        detail: `${tag}${cls} overflows by ${Math.round(rect.right - vw)}px` });
                }
            }
        });

        // 2. Small fonts (leaf text nodes only)
        document.querySelectorAll('p, span, a, li, td, th, label, button').forEach(el => {
            const size = parseFloat(getComputedStyle(el).fontSize);
            if (size < 12 && el.textContent.trim().length > 0 && el.children.length === 0) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                issues.push({ type: 'small-font', severity: 'medium',
                    detail: `${tag}${cls} ${size}px (min 12px)` });
            }
        });

        // 3. Touch targets < 44px (skip inline text links and range/hidden inputs)
        document.querySelectorAll('button, input, select, textarea, [role=button], a[class]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.height > 0 && rect.height < 44 && rect.width > 0) {
                const display = getComputedStyle(el).display;
                if (el.tagName === 'A' && display === 'inline') return;
                if (el.tagName === 'INPUT' && (el.type === 'range' || el.type === 'hidden')) return;
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                const text = el.textContent.trim().substring(0, 25);
                issues.push({ type: 'touch-target', severity: 'medium',
                    detail: `${tag}${cls} "${text}" ${Math.round(rect.height)}px (min 44px)` });
            }
        });

        // === WCAG STRUCTURE CHECKS ===

        // 4. Heading hierarchy
        const headings = [];
        document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(el => {
            headings.push(parseInt(el.tagName[1]));
        });
        for (let i = 1; i < headings.length; i++) {
            if (headings[i] > headings[i-1] + 1) {
                issues.push({ type: 'heading-skip', severity: 'medium',
                    detail: `h${headings[i-1]} -> h${headings[i]} (skips level)` });
            }
        }

        // 5. Missing lang attribute (WCAG 3.1.1)
        if (!document.documentElement.lang) {
            issues.push({ type: 'missing-lang', severity: 'high',
                detail: 'html element missing lang attribute' });
        }

        // 6. Missing landmarks (WCAG 1.3.1)
        if (!document.querySelector('main, [role=main]')) {
            issues.push({ type: 'missing-landmark', severity: 'medium',
                detail: 'no <main> landmark found' });
        }

        // 7. Images missing alt text (WCAG 1.1.1)
        document.querySelectorAll('img').forEach(el => {
            if (!el.hasAttribute('alt') && !el.getAttribute('role')?.includes('presentation')) {
                const src = el.src ? el.src.split('/').pop().substring(0, 30) : 'unknown';
                issues.push({ type: 'missing-alt', severity: 'high',
                    detail: `img "${src}" missing alt attribute` });
            }
        });

        // 8. Buttons/links without accessible name (WCAG 4.1.2)
        document.querySelectorAll('button, a[href], [role=button]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;
            const text = el.textContent.trim();
            const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || '';
            const title = el.getAttribute('title') || '';
            const imgAlt = el.querySelector('img[alt]')?.alt || '';
            if (!text && !aria && !title && !imgAlt) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                issues.push({ type: 'missing-name', severity: 'high',
                    detail: `${tag}${cls} has no accessible name` });
            }
        });

        // 9. Contrast ratio (WCAG 1.4.3)
        function srgbToLinear(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
        function luminance(r, g, b) {
            return 0.2126 * srgbToLinear(r/255) + 0.7152 * srgbToLinear(g/255) + 0.0722 * srgbToLinear(b/255);
        }
        function parseColor(str) {
            const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
            if (!m) return null;
            return { r: +m[1], g: +m[2], b: +m[3], a: str.includes('rgba') ? parseFloat(str.split(',')[3]) : 1 };
        }
        function getEffectiveBg(el) {
            let layers = [];
            let node = el;
            while (node && node !== document.documentElement) {
                const bg = getComputedStyle(node).backgroundColor;
                const c = parseColor(bg);
                if (c && c.a > 0.01) layers.push(c);
                if (c && c.a >= 0.99) break;
                node = node.parentElement;
            }
            let bg = { r: 0, g: 0, b: 0 };
            for (let i = layers.length - 1; i >= 0; i--) {
                const l = layers[i];
                bg.r = Math.round(l.a * l.r + (1 - l.a) * bg.r);
                bg.g = Math.round(l.a * l.g + (1 - l.a) * bg.g);
                bg.b = Math.round(l.a * l.b + (1 - l.a) * bg.b);
            }
            return bg;
        }
        function contrastRatio(fg, bg) {
            const l1 = luminance(fg.r, fg.g, fg.b);
            const l2 = luminance(bg.r, bg.g, bg.b);
            const lighter = Math.max(l1, l2);
            const darker = Math.min(l1, l2);
            return (lighter + 0.05) / (darker + 0.05);
        }

        const textEls = Array.from(document.querySelectorAll('h1,h2,h3,p,span,a,li,label,button'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && el.textContent.trim().length > 0 && el.children.length === 0;
            }).slice(0, 20);

        textEls.forEach(el => {
            const cs = getComputedStyle(el);
            const fg = parseColor(cs.color);
            if (!fg) return;
            const bg = getEffectiveBg(el);
            const ratio = contrastRatio(fg, bg);
            const size = parseFloat(cs.fontSize);
            const bold = parseInt(cs.fontWeight) >= 700;
            const isLarge = size >= 18 || (size >= 14 && bold);
            const minRatio = isLarge ? 3 : 4.5;
            if (ratio < minRatio) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                const text = el.textContent.trim().substring(0, 20);
                issues.push({ type: 'low-contrast', severity: 'high',
                    detail: `${tag}${cls} "${text}" ratio ${ratio.toFixed(1)}:1 (min ${minRatio}:1)` });
            }
        });

        // Deduplicate
        const seen = new Set();
        return issues.filter(i => {
            const k = i.type + ':' + i.detail;
            if (seen.has(k)) return false;
            seen.add(k); return true;
        }).slice(0, 25);
    }"""


@mcp.tool()
def eyes_screenshot(
    url: str = "/",
    device: str = "iphone-14",
) -> str:
    """Take a viewport-sized screenshot of a page.

    Args:
        url: Full URL or path (requires LO_EYES_BASE_URL env var for paths)
        device: Device preset -- iphone-se, iphone-14, ipad, laptop, desktop
    """
    if device not in DEVICES:
        return f"Unknown device '{device}'. Choose: {', '.join(DEVICES.keys())}"

    config = DEVICES[device]
    slug = _slug(url)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    sync_pw = _get_playwright()
    with sync_pw() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": config["width"], "height": config["height"]},
            device_scale_factor=1,
            is_mobile=config.get("mobile", False),
        )
        page = context.new_page()
        page.goto(_url(url), wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(500)

        filename = f"{slug}_{device}_{ts}.png"
        filepath = SCREENSHOT_DIR / filename
        page.screenshot(path=str(filepath), full_page=False)

        context.close()
        browser.close()

    return json.dumps({
        "status": "ok",
        "file": str(filepath),
        "device": device,
        "viewport": f"{config['width']}x{config['height']}",
        "url": url,
    })


@mcp.tool()
def eyes_scan(
    url: str = "/",
    device: str = "iphone-14",
    overlap: int = 60,
) -> str:
    """Auto-chunk a full page into viewport-sized readable screenshots.

    Captures the entire page as sequential viewport-sized chunks with overlap.

    Args:
        url: Full URL or path to scan
        device: Device preset
        overlap: Pixel overlap between chunks
    """
    if device not in DEVICES:
        return f"Unknown device '{device}'. Choose: {', '.join(DEVICES.keys())}"

    config = DEVICES[device]
    slug = _slug(url)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    scan_dir = SCREENSHOT_DIR / f"{slug}_{device}_{ts}"
    scan_dir.mkdir(parents=True, exist_ok=True)

    sync_pw = _get_playwright()
    with sync_pw() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": config["width"], "height": config["height"]},
            device_scale_factor=1,
            is_mobile=config.get("mobile", False),
        )
        page = context.new_page()
        page.goto(_url(url), wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(800)

        page_height = page.evaluate("() => document.body.scrollHeight")
        vh = config["height"]
        step = vh - overlap
        folds = max(1, (page_height + step - 1) // step)

        manifest = {
            "url": url,
            "device": device,
            "viewport": f"{config['width']}x{config['height']}",
            "page_height": page_height,
            "folds": folds,
            "timestamp": ts,
            "directory": str(scan_dir),
            "chunks": [],
        }

        for i in range(folds):
            y = i * step
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(300)

            filename = f"chunk_{i+1:02d}.png"
            filepath = scan_dir / filename
            page.screenshot(path=str(filepath), full_page=False)

            manifest["chunks"].append({
                "file": str(filepath),
                "fold": i + 1,
                "scroll_y": y,
                "viewport_top": y,
                "viewport_bottom": min(y + vh, page_height),
            })

        manifest_path = scan_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        context.close()
        browser.close()

    return json.dumps(manifest, indent=2)


@mcp.tool()
def eyes_audit(
    url: str = "/",
    devices: Optional[str] = None,
) -> str:
    """Run responsive + accessibility audit across viewports.

    Checks: overflow, small fonts, touch targets, heading hierarchy,
    lang attr, landmarks, alt text, accessible names, contrast ratio.
    Returns a grade (S+ to F) and detailed issues.

    Args:
        url: Full URL or path to audit
        devices: Comma-separated device list (default: all)
    """
    device_list = DEVICES.keys() if not devices else [d.strip() for d in devices.split(",")]
    all_issues = []

    sync_pw = _get_playwright()
    with sync_pw() as p:
        browser = p.chromium.launch(headless=True)

        for dev_name in device_list:
            if dev_name not in DEVICES:
                continue
            config = DEVICES[dev_name]
            context = browser.new_context(
                viewport={"width": config["width"], "height": config["height"]},
                device_scale_factor=1,
                is_mobile=config.get("mobile", False),
            )
            page = context.new_page()
            page.goto(_url(url), wait_until="networkidle", timeout=15000)

            found = page.evaluate(_run_audit_js())

            for issue in found:
                all_issues.append({"device": dev_name, **issue})

            context.close()

        browser.close()

    high = sum(1 for i in all_issues if i.get("severity") == "high")
    med = sum(1 for i in all_issues if i.get("severity") == "medium")
    total = len(all_issues)

    if total == 0:
        grade = "S+"
    elif high > 5:
        grade = "F"
    elif high > 2:
        grade = "D"
    elif high > 0:
        grade = "C"
    elif med > 5:
        grade = "B"
    elif med > 0:
        grade = "A"
    else:
        grade = "S+"

    result = {
        "url": url,
        "grade": grade,
        "summary": {"high": high, "medium": med, "total": total},
        "issues": all_issues,
        "devices_checked": list(device_list),
    }

    return json.dumps(result, indent=2)


@mcp.tool()
def eyes_compare(
    url: str = "/",
    device: str = "laptop",
    save_baseline: bool = False,
    threshold: float = 0.5,
) -> str:
    """Visual regression: pixel-diff a page against its saved baseline.

    First call with save_baseline=true to capture a baseline. Later calls
    capture the page again and report the percentage of changed pixels
    (anti-alias tolerant). Above threshold, writes a red-highlight diff
    image showing exactly what changed.

    Args:
        url: Full URL or path to compare
        device: Device preset -- iphone-se, iphone-14, ipad, laptop, desktop
        save_baseline: Capture/overwrite the baseline instead of comparing
        threshold: Max percent of changed pixels considered a match (default 0.5)
    """
    if device not in DEVICES:
        return f"Unknown device '{device}'. Choose: {', '.join(DEVICES.keys())}"
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return json.dumps({"status": "error", "error": "Pillow not installed (pip install pillow)"})

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    config = DEVICES[device]
    slug = _slug(url)
    baseline_path = BASELINE_DIR / f"{slug}_{device}.png"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    current_path = SCREENSHOT_DIR / f"{slug}_{device}_{ts}_compare.png"

    sync_pw = _get_playwright()
    with sync_pw() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": config["width"], "height": config["height"]},
            device_scale_factor=1,
            is_mobile=config.get("mobile", False),
        )
        page = context.new_page()
        page.goto(_url(url), wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(800)
        target = baseline_path if save_baseline else current_path
        page.screenshot(path=str(target), full_page=True)
        context.close()
        browser.close()

    if save_baseline:
        return json.dumps({"status": "baseline_saved", "baseline": str(baseline_path), "url": url, "device": device})

    if not baseline_path.exists():
        return json.dumps({"status": "no_baseline", "hint": f"Run eyes_compare with save_baseline=true first", "expected": str(baseline_path)})

    base = Image.open(baseline_path).convert("RGB")
    curr = Image.open(current_path).convert("RGB")

    dimensions_changed = base.size != curr.size
    if dimensions_changed:
        w, h = min(base.size[0], curr.size[0]), min(base.size[1], curr.size[1])
        base, curr = base.crop((0, 0, w, h)), curr.crop((0, 0, w, h))

    diff = ImageChops.difference(base, curr)
    # changed pixel = any channel differs by more than 16 (anti-alias tolerance)
    mask = diff.convert("L").point(lambda v: 255 if v > 16 else 0)
    changed = mask.histogram()[255]
    total = mask.size[0] * mask.size[1]
    pct = 100.0 * changed / total if total else 0.0

    result = {
        "url": url,
        "device": device,
        "changed_pixels_pct": round(pct, 2),
        "threshold_pct": threshold,
        "dimensions_changed": dimensions_changed,
        "baseline": str(baseline_path),
    }

    if pct <= threshold:
        result["status"] = "match"
        current_path.unlink(missing_ok=True)
    else:
        overlay = curr.copy()
        red = Image.new("RGB", overlay.size, (255, 0, 0))
        overlay = Image.composite(red, overlay, mask)
        diff_path = SCREENSHOT_DIR / f"{slug}_{device}_{ts}_diff.png"
        overlay.save(diff_path)
        result["status"] = "changed"
        result["current"] = str(current_path)
        result["diff_image"] = str(diff_path)

    return json.dumps(result, indent=2)


@mcp.tool()
def eyes_devices() -> str:
    """List available device presets with their viewport dimensions."""
    return json.dumps({
        name: {
            "viewport": f"{d['width']}x{d['height']}",
            "mobile": d["mobile"],
        }
        for name, d in DEVICES.items()
    }, indent=2)


def main():
    """Entry point for the lo-eyes MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
