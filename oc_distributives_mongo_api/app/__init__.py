from flask import Flask, Blueprint

mongo_api = Blueprint("mongo_api", __name__)
from .routes import *

def create_app(config_class):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.register_blueprint(mongo_api)
    return app
