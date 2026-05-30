"""CLI entry point for the OpenHarness Web Config server."""
import os
import argparse
import logging
import sys

import uvicorn

MY_DIR=os.path.dirname(os.path.abspath(__file__))
ROOT_DIR=os.path.realpath(MY_DIR+"/..")
HARNESS_DIR=os.path.join(ROOT_DIR, "src")
for path in (ROOT_DIR, HARNESS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="OpenHarness Web Config Manager")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8899, help="Port to bind to (default: 8899)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    host_label = args.host if args.host != "0.0.0.0" else "localhost"
    print(f"Starting OpenHarness Web Config Manager...")
    print(f"  URL: http://{host_label}:{args.port}")
    from openharness.config.paths import get_config_file_path

    print(f"  Settings: {get_config_file_path()}")
    print()

    uvicorn.run(
        "web_config.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
