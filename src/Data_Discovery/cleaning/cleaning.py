"""Cleaning Utility for JSON files in a folder."""
import json
import os
from pathlib import Path


def clean_json_file(file_path):
    """Clean a JSON file by removing entries with "page_status" set to "Page not found"."""
    with Path(file_path).open(encoding="utf-8") as f:
        data = json.load(f)

        # Only clean if data is a list of dicts
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            cleaned_data = [item for item in data if item.get("page_status") != "Page not found"]
            with Path(file_path).open("w", encoding="utf-8") as f:
                json.dump(cleaned_data, f, indent=4)
            print(f"Cleaned: {file_path}")
        else:
            print(f"Skipped (not a list of dicts): {file_path}")


def clean_folder_recursive(folder_path):
    """Recursively clean all JSON files in a folder."""
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".json"):
                file_path = Path(root) / file
                clean_json_file(file_path)

if __name__ == "__main__":
    folder = "reports"
    clean_folder_recursive(folder)
