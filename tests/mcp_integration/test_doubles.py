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
        self.jobs = {}

    def add_job(self, job_name, job_data):
        """Add a job to the test double"""
        self.jobs[job_name] = {"data": job_data, "builds": {}}

    def add_build(self, job_name, build_number, build_data):
        """Add a build to a job"""
        if job_name in self.jobs:
            self.jobs[job_name]["builds"][build_number] = {"data": build_data, "log": ""}

    def add_console_log(self, job_name, build_number, log_content):
        """Add a console log to a build"""
        if job_name in self.jobs and build_number in self.jobs[job_name]["builds"]:
            self.jobs[job_name]["builds"][build_number]["log"] = log_content

    def add_sub_builds(self, parent_job_name, parent_build_number, sub_builds):
        """Associate sub-builds with a parent build"""
        if parent_job_name in self.jobs and parent_build_number in self.jobs[parent_job_name]["builds"]:
            self.jobs[parent_job_name]["builds"][parent_build_number]["data"]["sub_builds"] = sub_builds

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
        outer = self

        class JenkinsHandler(BaseHTTPRequestHandler):
            def _get_job_name_from_path(self, parts):
                """Extract job name from URL parts, handling nested jobs."""
                job_name_segments = []
                i = 0
                end_index = 0
                while i < len(parts):
                    if parts[i] == "job":
                        if i + 1 < len(parts):
                            # Check if the next part is a build number or api call
                            if parts[i + 1].isdigit() or parts[i + 1] in [
                                "api",
                                "build",
                                "buildWithParameters",
                            ]:
                                break
                            job_name_segments.append(parts[i + 1])
                            i += 2
                        else:
                            break  # trailing 'job'
                    else:
                        # This part of the path is not a job segment, so we stop.
                        break
                
                if not job_name_segments:
                    return None, -1

                job_name = "/".join(job_name_segments)
                
                # The end index is where the job name parsing stopped.
                # It's the sum of 'job' parts and name parts.
                end_index = len(job_name_segments) * 2
                
                # The above logic is too simple and fails for root-level jobs.
                # A more robust way is to check against known jobs.
                url_path = "/".join(parts)
                for j in outer.jobs:
                    # Construct the expected path for the job
                    expected_path_prefix = "job/" + j.replace("/", "/job/")
                    if url_path.startswith(expected_path_prefix):
                        # Found a match. The end index is the length of the prefix.
                        end_index = len(expected_path_prefix.split('/'))
                        return j, end_index

                return None, -1

            def do_GET(self):
                # Use the outer instance's jobs dictionary
                jobs = outer.jobs
                path = self.path.split("?")[0]
                parts = path.strip("/").split("/")

                # Generic info endpoints
                if path == "/api/json":
                    self._json_response({"description": "Test Jenkins Instance"})
                    return
                if path.startswith("/me/api/json"):
                    self._json_response({"id": "test_user", "fullName": "Test User"})
                    return
                if path.startswith("/crumbIssuer"):
                    self.send_response(404)
                    self.end_headers()
                    return

                # Job/build specific endpoints
                job_name, job_name_end_index = self._get_job_name_from_path(parts)

                if job_name and job_name in jobs:
                    job_data = jobs[job_name]
                    
                    # Check for build number
                    build_number = None
                    if job_name_end_index < len(parts) and parts[job_name_end_index].isdigit():
                        build_number = int(parts[job_name_end_index])

                    if build_number is not None:
                        # It's a build-specific URL
                        if build_number in job_data["builds"]:
                            build_data = job_data["builds"][build_number]
                            if path.endswith("/api/json"):
                                self._json_response(build_data["data"])
                                return
                            elif path.endswith("/consoleText"):
                                self.send_response(200)
                                self.send_header("Content-type", "text/plain")
                                self.end_headers()
                                self.wfile.write(build_data["log"].encode())
                                return
                    else:
                        # It's a job-specific URL
                        if path.endswith("/api/json"):
                            self._json_response(job_data["data"])
                            return

                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                """Handle build triggers."""
                jobs = outer.jobs
                path = self.path.split("?")[0]
                parts = path.strip("/").split("/")
                
                job_name, _ = self._get_job_name_from_path(parts)

                if job_name and (path.endswith("/build") or path.endswith("/buildWithParameters")):
                    if job_name in jobs:
                        # Simulate build triggering and updating the job info
                        job_data = jobs[job_name]
                        
                        # Find next build number
                        if "nextBuildNumber" in job_data["data"]:
                            build_number = job_data["data"]["nextBuildNumber"]
                            job_data["data"]["nextBuildNumber"] += 1
                        else:
                            # Fallback if not defined
                            build_number = len(job_data.get("builds", {})) + 1

                        # Add a mock build
                        # Add a mock build
                        new_build_data = {
                            "number": build_number,
                            "url": f"http://localhost:{self.server.server_port}/{job_name}/{build_number}/",
                            "result": "SUCCESS",
                            "building": False,
                            "actions": [
                                {"causes": [{"shortDescription": "Started by user"}]}
                            ],
                        }
                        outer.add_build(job_name, build_number, new_build_data)
                        outer.add_console_log(
                            job_name, build_number, "Build started...\nBuild finished."
                        )

                        # Update lastBuild
                        job_data["data"]["lastBuild"] = {"number": build_number}

                        self.send_response(201)  # Created
                        self.send_header(
                            "Location",
                            f"http://localhost:{self.server.server_port}/queue/item/1/",
                        )
                        self.end_headers()
                    else:
                        self.send_response(404)  # Not Found
                        self.end_headers()
                    return

                self.send_response(400)
                self.end_headers()

            def _json_response(self, payload, status_code=200):
                self.send_response(status_code)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, format, *args):
                # Suppress log messages for cleaner test output
                pass


        return JenkinsHandler


class QdrantTestDouble:
    """Simple Qdrant test double for integration testing"""

    def __init__(self, port=6333):
        self.port = port
        self.server = None
        self.thread = None
        self.collections = set()

    def start(self):
        """Start the test double server"""
        handler = self._create_handler()
        self.server = HTTPServer(("localhost", self.port), handler)
        self.server.allow_reuse_address = True
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
        outer = self

        class QdrantHandler(BaseHTTPRequestHandler):
            def _json_response(self, payload, status_code=200):
                self.send_response(status_code)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def do_GET(self):
                path = self.path.split("?", 1)[0]

                if path == "/health":
                    self._json_response({"status": "ok", "time": 0})
                elif path == "/collections":
                    response = {
                        "result": {
                            "collections": [
                                {"name": name} for name in sorted(list(outer.collections))
                            ]
                        }
                    }
                    self._json_response(response)
                elif path.startswith("/collections/"):
                    name = path.split("/")[2]
                    if name in outer.collections:
                        response = {
                            "result": {"status": "ok"},
                            "status": "ok",
                            "time": 0,
                        }
                        self._json_response(response)
                    else:
                        response = {
                            "status": "error",
                            "result": {"status": "error", "error": "Collection not found"},
                            "time": 0,
                        }
                        self._json_response(response, status_code=404)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                # Handle search or miscellaneous endpoints
                response = {"result": {"status": "ok"}, "status": "ok", "time": 0}
                self._json_response(response)

            def do_PUT(self):
                path = self.path.split("?", 1)[0]

                if path.startswith("/collections/"):
                    parts = path.split("/")
                    if len(parts) >= 3:
                        collection_name = parts[2]
                        outer.collections.add(collection_name)

                response = {"result": True, "status": "ok", "time": 0}
                self._json_response(response)

            def log_message(self, format, *args):
                # Suppress log messages
                pass

        return QdrantHandler
