"""Data preparation and submission module for the Data Discovery project."""  # noqa: INP001

import json
import logging
import os
from pathlib import Path

import pandas as pd
from utils import load_config_yaml

CONFIDENCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class DataDiscoverySubmission:
    """Handles data preparation and submission for the Data Discovery project."""

    def __init__(self):
        self.config = load_config_yaml("src/Data_Discovery/config/submission_config/config.yaml")
        self.original_data_path = self.config.get("original_data_path")
        self.reports_path = self.config.get("reports_path")
        self.submission_path = self.config.get("submission_path")
        self.dataset = pd.read_csv(self.original_data_path, sep=";")

    def prepare_data(self):
        """Return a dict mapping company names to a sorted list of up to 5 (url, year) entries."""
        company_data = {}
        for file in os.listdir(self.reports_path):
            json_path = Path(self.reports_path) / file / "report_data.json"
            if not json_path.is_file():
                continue
            with Path.open(json_path, "r") as f:
                data = json.load(f)

            # Filter and sort relevant entries
            found_entries = [item for item in data if item.get("page_status") == "Page found"]
            found_entries.sort(key=lambda x: (-int(x.get("year") or 0), -CONFIDENCE_ORDER.get(x.get("confidence", "").upper(), -1)))
            company_data[file] = found_entries[:5]  # limit to top 5

        return company_data

    def popoluate_data(self):
        """Populate the dataset with up to 5 rows per company using sorted report entries."""
        df_submission = self.dataset.copy()
        company_data = self.prepare_data()

        new_rows = []

        for _idx, row in df_submission.iterrows():
            name = row["NAME"]
            if row["TYPE"] == "FIN_REP" and name in company_data:
                entries = company_data[name]
                for entry in entries:
                    new_row = row.copy()
                    new_row["SRC"] = entry.get("url")
                    new_row["REFYEAR"] = entry.get("year")
                    new_rows.append(new_row)
            else:
                new_rows.append(row)

        return pd.DataFrame(new_rows)

    def save_submission(self, df_submission):
        """Save the prepared submission DataFrame to a CSV file."""
        os.makedirs(self.submission_path, exist_ok=True)  # noqa: PTH103
        submission_path = os.path.join(self.submission_path, "submission.csv")  # noqa: PTH118
        df_submission.to_csv(submission_path, index=False, sep=";")
        logging.info(f"Submission file saved at {submission_path}")  # noqa: G004

    def run(self):
        """Run the data preparation and submission process."""
        df_submission = self.popoluate_data()
        self.save_submission(df_submission)
