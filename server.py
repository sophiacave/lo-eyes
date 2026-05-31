#!/usr/bin/env python3
"""lo-eyes MCP Server — Visual frontend inspector for likeone.ai

Tools:
  eyes_screenshot  — viewport screenshot at any device preset
  eyes_scan        — auto-chunk full page into readable pieces
  eyes_audit       — responsive + a11y audit across all viewports
  eyes_compare     — visual diff between two screenshots
"""

import sys
import json
import base64
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

# Activate venv
VENV = Path(__file__).parent / ".venv"
if VENV.exists():
    site_packages = list((VENV / "lib").glob("python*/site-packages"))
    if site_packages:
        sys.path.insert(0, str(site_packages[0]))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lo-eyes")

BASE_URL = "https://likeone.ai"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

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
    path = url if url.startswith("/") else f"/{url.lstrip('/')}"
    return "home" if path == "/" else path.strip("/").replace("/", "-")


def _url(path: str) -> str:
    p = path if path.startswith("/") else f"/{path.lstrip('/')}"
    return f"{BASE_URL}{p}"


def _run_audit_js():
    """JavaScript audit code injected into pages."""
    return """() => {
        const vw = window.innerWidth;
        const issues = [];

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

        // 3. Touch targets < 44px (buttons and block-level links only, not inline text links)
        document.querySelectorAll('button, input, select, textarea, [role=button], a[class]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.height > 0 && rect.height < 44 && rect.width > 0) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                const text = el.textContent.trim().substring(0, 25);
                issues.push({ type: 'touch-target', severity: 'medium',
                    detail: `${tag}${cls} "${text}" ${Math.round(rect.height)}px (min 44px)` });
            }
        });

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

        // Deduplicate
        const seen = new Set();
        return issues.filter(i => {
            const k = i.type + ':' + i.detail;
            if (seen.has(k)) return false;
            seen.add(k); return true;
        }).slice(0, 15);
    }"""


@mcp.tool()
def eyes_screenshot(
    url: str = "/",
    device: str = "iphone-14",
) -> str:
    """Take a viewport-sized screenshot of a likeone.ai page.

    Args:
        url: URL path (e.g. "/" or "/blog/claude-custom-instructions-guide/")
        device: Device preset — iphone-se, iphone-14, ipad, laptop, desktop
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
    Each chunk is readable at full detail. Outputs a manifest for RAG indexing.

    Args:
        url: URL path to scan
        device: Device preset
        overlap: Pixel overlap between chunks (prevents missing content at fold boundaries)
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

    Checks for: overflow, small fonts (<12px), touch targets (<44px), heading hierarchy.
    Returns a grade (S+ to F) and detailed issues.

    Args:
        url: URL path to audit
        devices: Comma-separated device list (default: all). E.g. "iphone-14,desktop"
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
def eyes_devices() -> str:
    """List available device presets with their viewport dimensions."""
    return json.dumps({
        name: {
            "viewport": f"{d['width']}x{d['height']}",
            "mobile": d["mobile"],
        }
        for name, d in DEVICES.items()
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
