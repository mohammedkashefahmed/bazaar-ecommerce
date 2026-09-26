"""Tiny helpers shared by the API modules."""
from flask import jsonify, request


def error(message, status=400):
    """Every error response has the same shape: {"error": "..."}."""
    return jsonify({"error": message}), status


def get_json():
    """Return the request body as a dict, or {} if it is missing or not a JSON object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(value):
    """True for real integers. bool is a subclass of int in Python, so exclude it explicitly."""
    return isinstance(value, int) and not isinstance(value, bool)
