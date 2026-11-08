import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8080
DIRECTORY = Path(__file__).parent

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

def main():
    print("=" * 65)
    print(" AI-POWERED DOCUMENT INTELLIGENCE SYSTEM - STANDALONE PREVIEW")
    print("=" * 65)
    print(f" Serving dashboard from: {DIRECTORY}")
    print(f" Local URL: http://localhost:{PORT}/preview.html")
    print(" Press Ctrl+C to terminate.")
    print("=" * 65)

    webbrowser.open(f"http://localhost:{PORT}/preview.html")
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down preview server.")

if __name__ == "__main__":
    main()
