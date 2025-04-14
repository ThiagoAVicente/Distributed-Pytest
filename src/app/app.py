from flask import Flask, request, jsonify
"""
Flask web api
"""

ip:str = '127.0.0.1'
port:int = 5000

app = Flask(__name__)

@app.route("/", methods = ['GET'] )
def handleHome():
    return jsonify("/"), 200

@app.route("/stats", methods = ['GET'])
def handleStatsGet():
    return jsonify("/stats"), 200

@app.route("/network", methods = ['GET'])
def handleNetworkGet():
    return jsonify("/network"), 200

@app.route("/evaluation/<id>", methods = ['GET'])
def handleEvaluationIdGet(id):
    return jsonify("/evaluationIdGet" + id), 200

@app.route("/evaluation ", methods = ['GET'])
def handleEvaluationGet():
    return jsonify("/evaluationGet"), 200

@app.route("/evaluation", methods = ['POST'])
def handleEvaluationPost():
    content_type:str = request.headers.get('Content-Type')

    if content_type == 'application/json':
        # url list
        return jsonify("/evaluationPostJSON"), 200

    elif content_type == "multipart/form-data":
        # zip
        return jsonify("/evaluationPostZIP"), 200

    return jsonify("content type not allowed"), 400
