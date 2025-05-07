"""Main module for the Financial Sources Finder project."""

import logging
import sys

import google.generativeai as genai
from Data_Discovery.model.prompt_tuner import PromptTuner
from model.result_validator import ResultValidator
from scraping.claude_challenge_code import WebScraperModule

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
            dict: Final result with URL, year, and metadata.
        """
        logger.info(f"Starting search for {company_name} (type: {source_type})")

        # Perform initial scraping
        url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

        # Prepare the scraping result
        scraping_result = {"url": url, "year": year, "source_description": source_description, "confidence": confidence}

        # Validate the result
        validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # Automatic tuning loop
        iteration = 0
        while (
            not validation_result.get("is_valid", False)
            or validation_result.get("validation_score", 0) < self.validation_threshold
        ) and iteration < self.max_tuning_iterations:
            iteration += 1
            logger.info(f"Tuning iteration {iteration} for {company_name}")

            # Improve the prompt
            self.prompt_tuner.improve_prompt(company_name, source_type, scraping_result, validation_result)

            # Retry scraping
            url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

            # Update the result
            scraping_result = {
            "url": url,
            "year": year,
            "source_description": source_description,
            "confidence": confidence,
            }

            # Revalidate
            validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # Prepare the final result
        final_result = {
            "company_name": company_name,
            "source_type": source_type,
            "url": url,
            "year": year,
            "source_description": source_description,
            "confidence": confidence,
            "validation_score": validation_result.get("validation_score", 0),
            "is_valid": validation_result.get("is_valid", False),
            "tuning_iterations": iteration,
            "feedback": validation_result.get("feedback", ""),
        }

        logger.info(f"Search completed for {company_name}: {'VALID' if final_result['is_valid'] else 'NOT VALID'}")
        return final_result


    def process_companies_batch(self, companies_batch, source_type, finder):
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
        try:
            for company in companies_batch:
                result = finder.find_financial_source(company, source_type)
                results.append(result)
        except Exception:
            logger.exception("Error processing a company in the batch", extra={"batch": companies_batch})
            results.append(
                {"company_name": company, "source_type": source_type, "url": None, "year": None, "error": "Processing error"}
            )
        return results
