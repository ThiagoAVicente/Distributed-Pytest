def run_flask_server(node):
    """
    run http server using flask
    """
    
    # imports
    from flask import Flask, request, jsonify, send_from_directory
    import os
    import logging
        
    app = Flask(__name__)
    
    @app.route("/", methods=["GET"])
    def home():
        return jsonify({
            "message": "Bem-vindo à API de Avaliação de Testes!",
            "endpoints": {
                "POST /evaluation": "Submeter um projeto para avaliação (ZIP ou URLs do GitHub)",
                "GET /evaluation": "Listar todas as avaliações",
                "GET /evaluation/<id>": "Obter detalhes de uma avaliação específica",
                "GET /stats": "Estatísticas do sistema",
                "GET /network": "Informações da rede"
            }
        }), 200

    @app.route("/evaluation", methods=["POST"])
    def submit_evaluation():
        evaluation_id = str(uuid.uuid4())
        data = load_data()
        data[evaluation_id] = {"status": "pending"}
        save_data(data)
    
        logging.debug(f"Headers recebidos: {request.headers}")
        logging.debug(f"Files recebidos: {request.files}")
        logging.debug(f"Form data: {request.form}")
    
        project_dir = os.path.join(PROJECTS_DIR, evaluation_id)
    
        if "file" in request.files:
            file = request.files["file"]
            if file.filename == '':
                return jsonify({"error": "Nenhum arquivo enviado"}), 400
            zip_path = os.path.join(PROJECTS_DIR, f"{evaluation_id}.zip")
            file.save(zip_path)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(project_dir)
            os.remove(zip_path)
            subdirs = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
            if not subdirs:
                return jsonify({"error": "Nenhum subdiretório encontrado no ZIP"}), 400
            test_dir = os.path.join(project_dir, subdirs[0])
        elif request.is_json:
            token = request.json.get("auth_token")
            projects = request.json.get("projects", [])
            os.makedirs(project_dir, exist_ok=True)
            for url in projects:
                try:
                    dest = os.path.join(project_dir, url.split("/")[-1])
                    functions.downloadFromGithub(token, url, dest)
                except Exception as e:
                    return jsonify({"error": f"Erro ao baixar {url}: {str(e)}"}), 400
            test_dir = project_dir
        else:
            return jsonify({"error": "Tipo de conteúdo não suportado"}), 400
    
        threading.Thread(target=run_tests, args=(evaluation_id, test_dir)).start()
        return jsonify({"evaluation_id": evaluation_id}), 202
    
    
    
    @app.route("/evaluation", methods=["GET"])
    def list_evaluations():
        data = load_data()
        return jsonify(list(data.keys())), 200
    
    
    
    @app.route("/evaluation/<id>", methods=["GET"])
    def get_evaluation(id):
        data = load_data()
        if id in data:
            return jsonify(data[id]), 200
        return jsonify({"error": "Avaliação não encontrada"}), 404
    
    
    
    @app.route("/stats", methods=["GET"])
    def get_stats():
        data = load_data()
        total_evals = len(data)
        completed = sum(1 for eval in data.values() if eval["status"] == "completed")
        stats = {
            "total_evaluations": total_evals,
            "completed_evaluations": completed,
            "pending_evaluations": total_evals - completed
        }
        return jsonify(stats), 200
    
    
    
    @app.route("/network", methods=["GET"])
    def get_network():
        return jsonify({"network": "Sistema centralizado"}), 200