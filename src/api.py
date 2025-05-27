"""
implements web api code
"""

from flask import Flask, jsonify, request, send_file, after_this_request
import threading
import logging
import asyncio
from node import Node
import traceback
import tempfile
import os
import utils.functions as f

class FlaskInterface:
    "flask web api"

    def __init__(self, node: Node, http_port: int = None, l = None):
        self.node = node
        self.http_port = 10000
        self.event_loop = l or asyncio.get_event_loop()
        # create app
        self.app = Flask(__name__)
        self.app.json.sort_keys = False
        self.setup_routes()


    def setup_routes(self):
        "prepare routes"

        @self.app.route("/", methods=["GET"])
        def home():
            return jsonify({
                "endpoints": {
                    "POST /evaluation": "submit for evaluation ( JUST URLS FOR NOW )",
                    "GET /evaluation": "List all evaluations",
                    "GET /evaluation/<id>": "Get evaluation status",
                    "GET /stats": "Get node stats",
                    "GET /network": "Get network info",
                    "temp":f"{self.node.address}"
                }
            }), 200

        @self.app.route("/evaluation", methods=["POST"])
        def submit_evaluation_url():
            # print(request.content_type)
            if request.content_type == 'application/json':
                try:
                    data = request.get_json()
                    if not data:
                        return jsonify({"error": "Invalid JSON data"}), 400

                    # extract info
                    urls = data.get('projects')
                    token = data.get('auth_token')

                    if not urls:
                        return jsonify({"error": "URL is required"}), 400

                    # If loop is running, use run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(
                        self.node.submit_evaluation_url(urls, token),
                        self.event_loop
                    )
                    eval_id = future.result()


                    return jsonify({
                        "status": "submitted",
                        "eval_id": eval_id,
                    }), 200

                except Exception as e:
                    logging.error(f"Error submitting evaluation: {e}")
                    return jsonify({"error": str(e)}), 500

            elif request.content_type.startswith('multipart/form-data'):
                # download file and unzip it in a temp folder

                if 'file' not in request.files:
                    return jsonify({"error": "No file part in the request"}), 400

                file = request.files['file']
                if not file.filename or file.filename == '':
                    return jsonify({"error": "No selected file"}), 400

                # store zip inside a temp folder
                file_dir = tempfile.mkdtemp(prefix="evaluation_")
                file_path = os.path.join(file_dir, file.filename)
                file.save(file_path)

                # submit evaluation
                future = asyncio.run_coroutine_threadsafe(
                    self.node.submit_evaluation(file_dir, file.filename),
                    self.event_loop
                )
                eval_id = future.result()

                if not eval_id:
                    return jsonify({"error": "Failed to submit evaluation"}), 500

                return jsonify({
                    "status": "submitted",
                    "eval_id": eval_id,
                }), 200

            return jsonify({"error": "Invalid content type"}), 400

        @self.app.route("/evaluation", methods=["GET"])
        def list_evaluations():
            evals = self.node.get_all_evaluations()

            return jsonify(evals), 200

        @self.app.route("/evaluation/<id>", methods=["GET"])
        def get_evaluation(id):
            # get info for a
            eval_info = self.node.get_evaluation_status(id)

            if not eval_info:
                return jsonify({"error": "Evaluation not found"}), 404

            return jsonify(eval_info), 200

        @self.app.route("/stats", methods=["GET"])
        def get_stats():
            # get node status
            status = self.node.get_status()
            return jsonify(status), 200

        @self.app.route("/file/<file_id>", methods=["GET"])
        def get_file(file_id):

            if file_id in self.node.urls:
                # return the url instead
                jsonify({"url": self.node.urls[file_id]})

            # Check if file exists in current directory
            if os.path.isdir(file_id):
                # zip the directory and send it
                zip_file = f.folder2zip(file_id)
                @after_this_request
                def remove_file(response):
                    try:
                        os.remove(zip_file)
                    except Exception:
                        pass
                    return response
                return send_file(zip_file, as_attachment=True, download_name=f"{file_id}.zip")
            else:
                return jsonify({"error": "File not found"}), 404

        @self.app.route("/task", methods=["POST"])
        def submit_task_result():
            """receive task result from anothere node via http post using json"""
            # ensure content type is application/json
            if request.content_type != 'application/json':
                return jsonify({"error": "Invalid content type"}), 400

            try:
                data = request.get_json()
                if not data:
                    return jsonify({"error": "Invalid JSON data"}), 400

                # extract info
                task_id = data.get('task_id')

                if not task_id or not data:
                    return jsonify({"error": "Task ID and result are required"}), 400

                # process the task result
                future = asyncio.run_coroutine_threadsafe(
                    self.node._handle_task_result(task_id, data),
                    self.event_loop
                )
                success = future.result()

                if not success:
                    return jsonify({"error": "Failed to process task result"}), 500

                return jsonify({"status": "success"}), 200
            except Exception as e:
                logging.info(f"Error processing task result: {traceback.format_exc()}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/network", methods=["GET"])
        def get_network():

            res = self.node.get_network_schema()

            return jsonify(res), 200

    def start(self):
        """Start the Flask server in a separate thread"""
        thread = threading.Thread(
            target=self.app.run,
            kwargs={
                'host': self.node.address[0],
                'port': self.http_port,
                'debug': False,
                'use_reloader': False  # cuz of threaded mode
            }
        )
        thread.daemon = True
        thread.start()

        logging.info(f"Flask API server started on http://{self.node.address[0]}:{self.http_port}")
        return thread
