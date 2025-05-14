"""Data preparation and submission module for the Data Discovery project."""


import json
import os

import pandas as pd
from utils import load_config_yaml


class DataDiscoverySubmission:
    def __init__(self):
        self.config = load_config_yaml("src\Data_Discovery\config\data_preparation_config\config.yaml")
        self.original_data_path = self.config.get("original_data_path")
        self.reports_path = self.config.get("reports_path")
        self.submission_path = self.config.get("submission_path")
        self.dataset = pd.read_csv(self.original_data_path, sep=";")
    
    def prepare_data(self, company_name):
        folder_path = os.path.join(self.reports_path, company_name)
        
        for file in os.listdir(folder_path):
           with open(os.path.join(folder_path, file), 'r') as f:
              data = json.load(f)
              if data.get("rl") and data.get("year"):
                    return data["rl"], data["year"]
        return None , None
    
    
    def popoluate_data(self):
        df_submission = self.dataset.copy()
        for idx, row in self.dataset.iterrows():
            if pd.isna(row["SRC"]) and pd.isna(row["REFYEAR"]) and row["TYPE"] == "FIN_REP":
                src, year =self.prepare_data(row["NAME"])
            if src and year:
                df_submission.at[idx, "SRC"] = src
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
        
        
def main():
    submission = DataDiscoverySubmission()
    submission.run()
    