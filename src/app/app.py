from flask import Flask, request, jsonify, send_from_directory
import os
import uuid
import json
import threading
import zipfile
import shutil
import functions
import logging

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
DATA_FILE = "evaluations.json"
PROJECTS_DIR = "projects"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def run_tests(evaluation_id, test_dir):
    data = load_data()
    data[evaluation_id]["status"] = "running"
    save_data(data)

    try:
        logging.debug(f"Diretório de testes: {test_dir}")
        tests = functions.getAllTests(test_dir)
        logging.debug(f"Testes encontrados: {tests}")
        total_tests = len(tests)
        passed = 0
        failed = 0

        for test in tests:
            # Remove o prefixo test_dir do caminho retornado
            relative_test = test.replace(test_dir, '').lstrip(os.path.sep)
            test_file = relative_test.split("::")[0]  
            test_path = os.path.join(test_dir, test_file)
            logging.debug(f"Tentando executar teste em: {test_path}")
            if os.path.exists(test_path):
                passed_count = functions.unitTest(test_path)
                if passed_count >= 0:
                    passed += passed_count
                    failed += 1 - passed_count
                else:
                    failed += 1
            else:
                logging.error(f"Arquivo de teste não encontrado: {test_path}")
                failed += 1

        percentage_passed = (passed / total_tests * 100) if total_tests > 0 else 0
        score = percentage_passed / 5

        data = load_data()
        data[evaluation_id].update({
            "status": "completed",
            "results": {
                "passed": passed,
                "failed": failed,
                "percentage_passed": round(percentage_passed, 2),
                "score": round(score, 2)
            }
        })
        save_data(data)
    except Exception as e:
        data = load_data()
        data[evaluation_id]["status"] = "error"
        data[evaluation_id]["error"] = str(e)
        save_data(data)

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

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

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

if __name__ == "__main__":
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR)
    app.run(host="0.0.0.0", port=5000, debug=True)