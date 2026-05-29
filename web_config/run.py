#!/usr/bin/env python3
"""Start the OpenHarness Web Configuration Manager."""

import argparse
import sys
from pathlib import Path

# Add project root to path so we can import openharness
project_root = Path(__file__).parent.parent / "src"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def main():
    parser = argparse.ArgumentParser(description="OpenHarness Web Config Manager")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8899, help="Port to bind to (default: 8899)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required. Install with: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    print(f"Starting OpenHarness Web Config Manager...")
    print(f"  URL: http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}")
    print()

    uvicorn.run(
        "web_config.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
