"""CLI entry point for the OpenHarness Web Config server."""
import os
import argparse
import sys
from pathlib import Path

import uvicorn

MY_DIR=os.path.dirname(os.path.abspath(__file__))
HARNESS_DIR=os.path.realpath(MY_DIR+"/../src")
sys.path.insert(0,HARNESS_DIR)

# Ensure config directory is writable (use project-local .openharness if home is read-only)
config_dir = os.environ.get("OPENHARNESS_CONFIG_DIR")
if config_dir is None:
    project_config = Path(MY_DIR).parent / ".openharness"
    try:
        project_config.mkdir(parents=True, exist_ok=True)
        test_file = project_config / ".write_test"
        test_file.touch()
        test_file.unlink()
        os.environ["OPENHARNESS_CONFIG_DIR"] = str(project_config)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description="OpenHarness Web Config Manager")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8899, help="Port to bind to (default: 8899)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    host_label = args.host if args.host != "0.0.0.0" else "localhost"
    print(f"Starting OpenHarness Web Config Manager...")
    print(f"  URL: http://{host_label}:{args.port}")
    print()

    uvicorn.run(
        "web_config.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
