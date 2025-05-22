"""Main module for the Financial Sources Finder project."""

import json
import logging
import os
import sys
from pathlib import Path
from time import time
from typing import Any

import google.generativeai as genai
from scraping.scraping_challenge import WebScraperModule
from tqdm import tqdm
from utils import save_json_obj

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class FinancialSourcesFinder:
    """Classe principale che coordina il processo di ricerca delle fonti finanziarie."""

    def __init__(self, api_key: str | None = None, max_tuning_iterations: int = 3, validation_threshold: int = 80):
        """
        Initialize the finder with the necessary configurations.

        Args:
            api_key (str): API key for Gemini (optional if already configured)
            max_tuning_iterations (int): Maximum number of tuning iterations
            validation_threshold (int): Validation threshold (0-100)
        """
        if api_key:
            genai.configure(api_key=api_key)

        self.scraper = WebScraperModule()
        self.max_tuning_iterations = max_tuning_iterations
        self.validation_threshold = validation_threshold

    def _load_existing_report(self, report_path: Path) -> dict[str, Any]:
        """
        Load an existing report from the specified path.

        Args:
            report_path (Path): Path to the report file.

        Returns
        -------
            dict: Loaded report data.
        """
        with report_path.open("r") as f:
            try:
                data = json.load(f)
                if not isinstance(data, list):
                    data = [data]  # Wrap single dict into a list
            except json.JSONDecodeError:
                data = []
        return data

    def find_financial_source(self, company_name: str, source_type: str = "Annual Report") -> dict[str, Any]:
        """
        Find the financial source for a company with automatic tuning.

        Args:
            company_name (str): Name of the company.
            source_type (str): Type of financial source.

        Returns
        -------
            dict: Final result with URL, yaear, and metadata.
        """
        logger.info("Starting search for %s (type: %s)", company_name, source_type)

        report_dir = Path("reports") / company_name
        report_path = report_dir / "report_data.json"
        # Check if the report already exists, Comment the following line for a full run
        # genereate_code_path = Path("generated_code") / f"{company_name}_Annual Report.py"
        # if genereate_code_path.exists():
        #     logger.info("Report already exists for %s, loading existing report", company_name)
        #     return self._load_existing_report(report_path)

        if report_path.exists():
            logger.info("Report already exists for %s, loading existing report", company_name)
            self._load_existing_report(report_path)
            data = self._load_existing_report(report_path)
            if len(data) > 5:
                logging.info("Report already exists for %s, loading existing report", company_name)
                return data
        url, year, confidence, source_description, page_status = self.scraper.scrape_financial_sources(company_name, source_type)

        # Ensure the directory exists
        os.makedirs(report_dir, exist_ok=True)  # noqa: PTH103
        scraping_result = {
            "url": url,
            "year": year,
            "source_description": source_description,
            "confidence": confidence,
            "page_status": page_status,
        }

        if Path(report_path).exists():
            with Path(report_path).open("r") as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = [data]  # Wrap single dict into a list
                except json.JSONDecodeError:
                    data = []
        else:
            data = []

        # Append the new result
        data.append(scraping_result)

        # Save the updated data
        save_json_obj(data, report_path)
        return scraping_result

    def process_companies_batch(self, companies_batch: list[Any], source_type: str = "Annual Report") -> list[Any]:
        """
        Process a batch of companies in parallel.

        Args:
        companies_batch (list): List of company names.
        source_type (str): Type of financial source.
        finder (FinancialSourcesFinder): Instance of the finder.

        Returns
        -------
        list: Results for the batch.
        """
        results = []
        start_time = time()
        for company in tqdm(companies_batch, desc="Processing companies", colour="green"):
            result = self.find_financial_source(company, source_type)
            results.append(result)
        logger.info("Batch processing completed in %.2f seconds", time() - start_time)
        return results
