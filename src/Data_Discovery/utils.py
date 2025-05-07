"""Utility functions for data discovery and configuration management."""

from pathlib import Path

import yaml


def laod_config_yaml(config_path: str) -> dict:
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
