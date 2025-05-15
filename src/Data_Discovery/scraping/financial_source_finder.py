"""Main module for the Financial Sources Finder project."""

import json
import logging
import os
import sys
from pathlib import Path

import google.generativeai as genai
from model.result_validator import ResultValidator
from scraping.scraping_challenge import WebScraperModule

from Data_Discovery.model.prompt_tuner import PromptTuner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class FinancialSourcesFinder:
    """Classe principale che coordina il processo di ricerca delle fonti finanziarie."""

    def __init__(self, api_key=None, max_tuning_iterations=3, validation_threshold=80):
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
        self.prompt_tuner = PromptTuner()
        self.validator = ResultValidator()

        self.max_tuning_iterations = max_tuning_iterations
        self.validation_threshold = validation_threshold

    def find_financial_source(self, company_name, source_type="Annual Report"):
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

        # Perform initial scraping
        url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

        report_dir = os.path.join("reports", company_name)  #  # noqa: PTH118
        report_path = os.path.join(report_dir, "report_data.json")  # noqa: PTH118
        # Ensure the directory exists
        os.makedirs(report_dir, exist_ok=True)  # noqa: PTH103
        scraping_result = {"url": url, "year": year, "source_description": source_description, "confidence": confidence}

        # Save data as JSON
        with Path.open(report_path, "w") as f:
            # Prepare the data to save
            json.dump(scraping_result, f, indent=4)

        # Validate the result
        # validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # # Automatic tuning loop
        # iteration = 0
        # while (
        #     not validation_result.get("is_valid", False)
        #     or validation_result.get("validation_score", 0) < self.validation_threshold
        # ) and iteration < self.max_tuning_iterations:
        #     iteration += 1
        #     logger.info(f"Tuning iteration {iteration} for {company_name}")

        #     # Improve the prompt
        #     self.prompt_tuner.improve_prompt(company_name, source_type, scraping_result, validation_result)

        #     # Retry scraping
        #     url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

        #     # Update the result
        #     scraping_result = {
        #     "url": url,
        #     "year": year,
        #     "source_description": source_description,
        #     "confidence": confidence,
        #     }

        #     # Revalidate
        #     validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # # Prepare the final result
        # final_result = {
        #     "company_name": company_name,
        #     "source_type": source_type,
        #     "url": url,
        #     "year": year,
        #     "source_description": source_description,
        #     "confidence": confidence,
        #     "validation_score": validation_result.get("validation_score", 0),
        #     "is_valid": validation_result.get("is_valid", False),
        #     "tuning_iterations": iteration,
        #     "feedback": validation_result.get("feedback", ""),
        # }

        # logger.info(f"Search completed for {company_name}: {'VALID' if final_result['is_valid'] else 'NOT VALID'}")
        # return final_result
        return scraping_result

    def process_companies_batch(self, companies_batch, source_type):
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
        for company in companies_batch:
            result = self.find_financial_source(company, source_type)
            results.append(result)
        return results
