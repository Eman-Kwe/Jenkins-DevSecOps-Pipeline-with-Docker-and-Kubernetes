import os
from flask import Flask, jsonify

app = Flask(__name__)
APP_VERSION = os.environ.get("APP_VERSION", "dev")

@app.get("/")
def index():
    return jsonify(message="DevSecOps demo service", version=APP_VERSION)

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

@app.get("/version")
def version():
    return jsonify(version=APP_VERSION)

if __name__ == "__main__":
    # Local debugging only. In the container, gunicorn serves the app.
    app.run(host="127.0.0.1", port=8080)
