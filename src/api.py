"""
implements web api code
"""

from flask import Flask, jsonify, request
import threading
import logging
import asyncio
from node import Node


class FlaskInterface:
    "flask web api"

    def __init__(self, node: Node, http_port: int = None, l = None):
        self.node = node
        self.http_port = http_port or node.address[1]
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
                        self.node.submit_evalution_url(urls, token),
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
            
            # elif request.content_type == 'multipart/form-data':
                
            return jsonify({"message": "TODO"}), 200

        @self.app.route("/evaluation", methods=["GET"])
        def list_evaluations():
            evals = self.node.get_all_evaluations()

            evaluations = []
            for eval_id, eval_info in evals.items():
                evaluations.append({
                    "id": eval_id,
                    "url": eval_info.get("url"),
                    "status": eval_info.get("status"),
                    "timestamp": eval_info.get("timestamp")
                })

            return jsonify(evaluations), 200

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
            # TODO: add info about other nodes 
            return jsonify(status), 200

        @self.app.route("/network", methods=["GET"])
        def get_network():
            
            res:dict = {
                f"{self.node.address[0]}:{self.node.address[1]}": [
                    f"{n[0]}:{n[1]}" for n in self.node.peers 
                ]
            }
            
            # TODO: add info about other nodes
            
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
