"""Data preparation and submission module for the Data Discovery project."""


import json
import os

import pandas as pd
from utils import load_config_yaml


class DataDiscoverySubmission:
    def __init__(self):
        self.config = load_config_yaml("src/Data_Discovery/config/data_preparation_config/config.yaml")
        self.original_data_path = self.config.get("original_data_path")
        self.reports_path = self.config.get("reports_path")
        self.submission_path = self.config.get("submission_path")
        self.dataset = pd.read_csv(self.original_data_path, sep=";")
    
    def prepare_data(self):
        """Returns a dict mapping company names to (rl, year)."""
        company_data = {}
        for file in os.listdir(self.reports_path):
            with open(os.path.join(self.reports_path , f"{file}/report_data.json"), 'r') as f:
                data = json.load(f)
                name = file # Adjust depending on your JSON structure
                rl = data.get("url")
                year = data.get("year")
                if name and rl and year:
                    company_data[name] = (rl, year)
        return company_data
    
    def popoluate_data(self):
        df_submission = self.dataset.copy()
        company_data = self.prepare_data()
        
        for idx, row in df_submission.iterrows():
            name = row["NAME"]
            if row["TYPE"] == "FIN_REP" and (pd.isna(row["SRC"]) or pd.isna(row["REFYEAR"])):
                if name in company_data:
                    rl, year = company_data[name]
                    df_submission.at[idx, "SRC"] = rl
                    df_submission.at[idx, "REFYEAR"] = year
                    
        return df_submission

    def save_submission(self, df_submission):
        os.makedirs(self.submission_path, exist_ok=True)
        submission_path = os.path.join(self.submission_path, "submission.csv")
        df_submission.to_csv(submission_path, index=False, sep=";")
        print(f"Submission file saved at {submission_path}")
        
    def run(self):
        df_submission = self.popoluate_data()
        self.save_submission(df_submission)
