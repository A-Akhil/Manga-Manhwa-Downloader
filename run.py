"""Main entry point — run CLI or start the web server."""

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        import uvicorn
        from backend.config import config

        host = config["server"]["host"]
        port = config["server"]["port"]
        print(f"Starting Manga Downloader API at http://{host}:{port}")
        print(f"Frontend: http://localhost:{port}")
        print(f"API docs: http://localhost:{port}/docs")
        uvicorn.run("backend.api:app", host=host, port=port, reload=True)
    else:
        from cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
