"""Utility functions for data discovery and configuration management."""

import json
from pathlib import Path
from typing import Any

import yaml


def load_config_yaml(config_path: str) -> dict[str, Any]:
    """
    Load a YAML configuration file.

    Args:
        config_path (str): Path to the YAML configuration file.

    Returns
    -------
        dict: Configuration data as a dictionary.
    """
    with Path.open(config_path, "r") as file:
        return yaml.safe_load(file)


def load_json_obj(file_path: str) -> dict:
    """Load a JSON object from a file."""
    with Path.open(file_path, "r") as f:
        return json.load(f)


def save_json_obj(obj: dict, file_path: str) -> None:
    """
    Save a dictionary object to a YAML file.

    Args:
        obj (dict): The object to save.
        file_path (str): The path to the file where the object will be saved.
    """
    with Path.open(file_path, "w") as f:
        # Prepare the data to save
        json.dump(obj, f, indent=4)


def save_code(code: str, file_path: str) -> None:
    """
    Save a code snippet to a file.

    Args:
        code (str): The code to save.
        file_path (str): The path to the file where the code will be saved.
    """
    with Path(file_path).open("w", encoding="utf-8") as f:
        f.write(code)
