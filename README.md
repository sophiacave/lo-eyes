# lo-eyes

[![CI](https://github.com/sophiacave/lo-eyes/actions/workflows/ci.yml/badge.svg)](https://github.com/sophiacave/lo-eyes/actions/workflows/ci.yml)


<!-- mcp-name: io.github.sophiacave/lo-eyes -->

[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange.svg)](https://modelcontextprotocol.io)

**Visual frontend accessibility inspector MCP server.** WCAG contrast checking, touch target validation, heading hierarchy audits, responsive screenshots, and S+ grading across mobile and desktop viewports.

Built by [Like One Foundation](https://likeone.ai) (501(c)(3) nonprofit). Works with any site by changing `BASE_URL`.

## Tools

| Tool | Description |
|------|-------------|
| `eyes_screenshot` | Viewport-sized screenshot at any device preset |
| `eyes_scan` | Auto-chunk full page into readable viewport pieces with RAG manifest |
| `eyes_audit` | Responsive + accessibility audit with S+ grading |
| `eyes_devices` | List available device presets |

## Device Presets

| Name | Viewport | Type |
|------|----------|------|
| `iphone-se` | 375x667 | Mobile |
| `iphone-14` | 390x844 | Mobile |
| `ipad` | 768x1024 | Tablet |
| `laptop` | 1280x800 | Desktop |
| `desktop` | 1440x900 | Desktop |

## Audit Checks

- **Overflow**: Elements exceeding viewport width (respects scroll parents)
- **Font size**: Text below 12px minimum
- **Touch targets**: Interactive elements below Apple HIG 44px minimum
- **Heading hierarchy**: Skipped heading levels (h1 -> h3)

## Grading

| Grade | Criteria |
|-------|----------|
| S+ | Zero issues |
| A | 1-5 medium, zero high |
| B | 6+ medium, zero high |
| C | 1-2 high |
| D | 3-5 high |
| F | 6+ high |

## Setup

```bash
cd lo-eyes
python3 -m venv .venv
source .venv/bin/activate
pip install playwright mcp
python3 -m playwright install chromium
```

## Usage

### As MCP Server (Claude Code)

Add to `.mcp.json`:
```json
{
  "mcpServers": {
    "lo-eyes": {
      "command": "/path/to/lo-eyes/.venv/bin/python3",
      "args": ["/path/to/lo-eyes/server.py"]
    }
  }
}
```

### As CLI

```bash
./lo-eyes audit /                           # Audit homepage
./lo-eyes screenshot /blog/ --device ipad   # iPad screenshot
./lo-eyes scan / --device iphone-14         # Full-page chunked scan
./lo-eyes responsive /academy/              # All 5 viewports
```

## Stack

- Python 3
- [Playwright](https://playwright.dev/) (headless Chromium)
- [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) (FastMCP, stdio transport)

## License

MIT

---

Built with love by [Like One](https://likeone.ai).
