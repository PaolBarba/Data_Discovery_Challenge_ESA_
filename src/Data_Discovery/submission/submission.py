"""Data preparation and submission module for the Data Discovery project."""

import logging
import os
from pathlib import Path

import pandas as pd
from utils import load_config_yaml, load_json_obj

CONFIDENCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class DataDiscoverySubmission:
    """Handles data preparation and submission for the Data Discovery project."""

    def __init__(self):
        self.config = load_config_yaml("src/Data_Discovery/config/submission_config/config.yaml")
        self.original_data_path = self.config.get("original_data_path")
        self.reports_path = self.config.get("reports_path")
        self.submission_path = self.config.get("submission_path")
        self.dataset = pd.read_csv(self.original_data_path, sep=";")

    def prepare_data(self) -> dict:
        """Return a dict mapping company names to a sorted list of up to 5 (url, year) entries."""
        company_data = {}
        for file in os.listdir(self.reports_path):
            json_path = Path(self.reports_path) / file / "report_data.json"
            if not json_path.is_file():
                continue
            data = load_json_obj(json_path)

            # Filter and sort relevant entries
            found_entries = [item for item in data if item.get("page_status") == "Page found"]
            found_entries.sort(
                key=lambda x: (
                    -int(x.get("year")) if isinstance(x.get("year"), str) and x.get("year").isdigit() else -1,
                    -CONFIDENCE_ORDER.get(x.get("confidence", "").upper(), -1),
                )
            )
            company_data[file] = found_entries[:5]  # limit to top 5

            urls = set()
            unique_entries = []
            for entry in found_entries:
                url = entry.get("url")
                if url and url not in urls:
                    urls.add(url)
                    unique_entries.append(entry)

            company_data[file] = unique_entries[:5]

        return company_data

    def populate_data(self) -> pd.DataFrame:
        """Replace FIN_REP rows with discovered URLs, keeping only first record as FIN_REP, and preserve original order."""
        df_submission = self.dataset.copy()
        company_data = self.prepare_data()
        
        seen = set()
        final_rows = []

        for idx, row in df_submission.iterrows():
            name = row['NAME']
            if name in seen:
                continue
            seen.add(name)
            group = df_submission[df_submission['NAME'] == name]
            
            discovered_urls = company_data.get(name, [])
            num_urls_to_add = min(5, len(discovered_urls))

            if num_urls_to_add == 0:
                final_rows.append(group)
                continue

            finrep_rows = group[group['TYPE'] == 'FIN_REP']
            other_rows = group[group['TYPE'] != 'FIN_REP']

            new_rows = []
            for i in range(num_urls_to_add):
                template = finrep_rows.iloc[0] if len(finrep_rows) > 0 else group.iloc[0]
                new_row = template.copy()
                entry = discovered_urls[i]
                new_row['SRC'] = entry.get('url')
                new_row['REFYEAR'] = entry.get('year')
                new_row['TYPE'] = 'FIN_REP' if i == 0 else 'OTHER'
                new_rows.append(new_row.to_frame().T)

            new_rows_df = pd.concat(new_rows) if new_rows else pd.DataFrame()
            max_other_rows = len(group) - num_urls_to_add
            kept_other_rows = other_rows.head(max_other_rows)

            company_df = pd.concat([new_rows_df, kept_other_rows])
            final_rows.append(company_df)

        if final_rows:
            result_df = pd.concat(final_rows)
            return result_df[df_submission.columns]
        return pd.DataFrame(columns=df_submission.columns)


    def save_submission(self, df_submission: pd.DataFrame) -> None:
        """Save the prepared submission DataFrame to a CSV file."""
        Path(self.submission_path).mkdir(parents=True, exist_ok=True)
        submission_path = Path(self.submission_path) / "submission.csv"
        df_submission.to_csv(submission_path, index=False, sep=";")
        logging.info("Submission file saved at %s", submission_path)

    def run(self) -> None:
        """Run the data preparation and submission process."""
        df_submission = self.populate_data()
        self.save_submission(df_submission)
