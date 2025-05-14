import json
import logging
import os
import re
import sys

import google.generativeai as genai
from dotenv import load_dotenv
from prompts.validation_prompt import generate_validation_prompt
from utils import load_config_yaml

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


# TODO: The class has too many responsibilities, consider splitting it into smaller classes
# TODO: Configuration must be externalized, consider using a config file or environment variables
# TODO: All the code must be written in English, consider translating the comments and docstrings
# TODO: Check if some code is repeated, if so, consider creating a helper function
# TODO: Check if some code can be simplified, if so, consider using a simpler approach
# TODO: Check if some code is useless, if so, consider removing it
# TODO: Optimization instructions should be more specific and clear
# TODO: Prompt must be written in English, consider translating it
# TODO: The prompt must be loaded from a file or a database, consider using a config file or environment variables


class ResultValidator:
    """Modulo per la validazione dei risultati tramite Gemini API"""

    def __init__(self):
        """Inizializza il validatore dei risultati"""
        # Utilizziamo Gemini invece di Mistral
        self.config = load_config_yaml("src/Data_Discovery/config/model_config/config.yaml")
        self.model_name = self.config.get("model_name")

    def validate_result(self, company_name, source_type, scraping_result):
        """
        Valida i risultati dello scraping utilizzando Gemini.

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            scraping_result (dict): Risultato dello scraping

        Returns
        -------
            dict: Risultato della validazione con score e feedback
        """
        url = scraping_result.get("url")
        year = scraping_result.get("year")
        source_description = scraping_result.get("source_description")
        confidence = scraping_result.get("confidence")

        validation_prompt = generate_validation_prompt(
            company_name=company_name,
            source_type=source_type,
            url=url,
            year=year,
            source_description=source_description,
            confidence=confidence,
        )

        try:
            # Use the Gemini API to validate the result
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(validation_prompt)

            if response:
                validation_text = response.text
                validation_result = self._extract_json_from_text(validation_text)
                if not validation_result:
                    validation_result = {
                        "is_valid": False,
                        "validation_score": 0,
                        "feedback": "Unable to parse the validation response",
                        "improvement_suggestions": "Retry with a clearer prompt",
                    }
                logger.info(
                    f"Validation completed for {company_name}: Score {validation_result.get('validation_score')}"
                )
                return validation_result
            else:
                logger.error("Errore API Gemini: Nessuna risposta ricevuta")
                return {
                    "is_valid": False,
                    "validation_score": 0,
                    "feedback": "Errore API Gemini: Nessuna risposta ricevuta",
                    "improvement_suggestions": "Verifica la connessione e riprova",
                }
        except Exception as e:
            logger.error(f"Errore durante la validazione: {e}")
            return {
                "is_valid": False,
                "validation_score": 0,
                "feedback": f"Error during validation: {e!s}",
                "improvement_suggestions": "Check the connection and try again",
            }

    def _extract_json_from_text(self, text):
        """Extract JSON from the text response."""
        try:
            json_pattern = r"({[\s\S]*})"
            match = re.search(json_pattern, text)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Unable to extract JSON from the response: {e}")
            return None
