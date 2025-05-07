"""Prompt Tuner Module."""

import logging
import os
import sys
from datetime import datetime

import google.generativeai as genai
from dotenv import load_dotenv
from prompts.base_prompt import base_prompt_improving
from prompts.prompt_improving import improving_prompt
from utils import laod_config_yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Configurare l'API di Google Gemini
load_dotenv(dotenv_path="src/Data_Discovery/config/model_config/.env")
API_KEY = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=API_KEY)


# TODO: The saving must be done in a specific folder, consider creating a folder for the results


class PromptTuner:
    """Module for automatic prompt optimization based on feedback."""

    def __init__(self, initial_prompt_template: str | None = None):
        """Initialize the PromptTuner with a default prompt template.

        Args:
            initial_prompt_template (str): Template for the initial prompt.
        """
        self.current_prompt = initial_prompt_template or base_prompt_improving
        self.config = laod_config_yaml("src/Data_Discovery/config/model_config/config.yaml")

        self.tuning_history = []
        self.model = genai.GenerativeModel(self.config["model_name"])

    def generate_prompt(self, company_name: str, source_type: str) -> str:
        """
        Generate the full prompt for the given company and source type.

        Args:
            company_name (str): Company name
            source_type (str): Type of financial source

        Returns
        -------
            str: The full prompt with the company name and source type filled in
        """
        return self.current_prompt.format(company_name=company_name, source_type=source_type)

    def improve_prompt(self, company_name, source_type, scraping_result, validation_result):
        """Improves the current prompt using feedback from Gemini.

        Args:
            company_name (str): Name of the company
            source_type (str): Type of financial source
            scraping_result (dict): Result of the web scraping
            validation_result (dict): Result of the validation

        Returns
        -------
            str: New improved prompt
        """
        # Improves the current prompt using feedback from Gemini
        improvement_prompt = improving_prompt(
            company_name=company_name,
            current_prompt=self.current_prompt,
            source_type=source_type,
            scraping_result=scraping_result,
            validation_result=validation_result,
        )

        try:
            response = self.model.generate_content(improvement_prompt)
            new_prompt = response.text.strip()

            # Save the tuning history
            self.tuning_history.append(
                {
                    "company": company_name,
                    "old_prompt": self.current_prompt,
                    "new_prompt": new_prompt,
                    "scraping_result": scraping_result,
                    "validation_result": validation_result,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Update the current prompt with the new one
            self.current_prompt = new_prompt

            logger.info("Prompt Improved for the company:", extra={"company": company_name})
        except Exception as e:
            logger.exception("An error occurred while improving the prompt", extra={"error": str(e)})
            return self.current_prompt  # Keep the current prompt in case of error

        return new_prompt
