"""Test doubles for MCP integration testing"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class JenkinsTestDouble:
    """Simple Jenkins test double for integration testing"""

    def __init__(self, port=18083):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Start the test double server"""
        handler = self._create_handler()
        self.server = HTTPServer(("localhost", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        # Give server time to start
        time.sleep(0.1)

    def stop(self):
        """Stop the test double server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def _create_handler(self):
        """Create request handler for the test double"""

        class JenkinsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/json":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    response = {
                        "description": "Test Jenkins Instance",
                        "mode": "NORMAL",
                        "nodeDescription": "the master Jenkins node",
                    }
                    self.wfile.write(json.dumps(response).encode())
                elif self.path == "/me/api/json":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    response = {"id": "test_user", "fullName": "Test User"}
                    self.wfile.write(json.dumps(response).encode())
                elif self.path == "/job/sample-job/api/json":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    response = {"name": "sample-job", "nextBuildNumber": 42}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                # Suppress log messages
                pass

        return JenkinsHandler


class QdrantTestDouble:
    """Simple Qdrant test double for integration testing"""

    def __init__(self, port=6333):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Start the test double server"""
        handler = self._create_handler()
        self.server = HTTPServer(("localhost", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        # Give server time to start
        time.sleep(0.1)

    def stop(self):
        """Stop the test double server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def _create_handler(self):
        """Create request handler for the test double"""

        class QdrantHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    response = {"status": "ok"}
                    self.wfile.write(json.dumps(response).encode())
                elif self.path.startswith("/collections"):
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    response = {"result": {"collections": []}}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                # Handle collection creation and search requests
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                response = {"result": {"status": "ok"}}
                self.wfile.write(json.dumps(response).encode())

            def do_PUT(self):
                # Handle vector insertions
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                response = {"result": {"status": "ok"}}
                self.wfile.write(json.dumps(response).encode())

            def log_message(self, format, *args):
                # Suppress log messages
                pass

        return QdrantHandler
