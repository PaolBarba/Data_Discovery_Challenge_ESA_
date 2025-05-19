"""Result Validator Module."""

import json
import logging
import re
import sys

import google.generativeai as genai
from prompts.validation_prompt import generate_validation_prompt
from utils import load_config_yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class ResultValidator:
    """Module for validating results using the Gemini API."""

    def __init__(self):
        """Initialize the result validator."""
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
                logger.info("Validation completed for %s: Score %s", company_name, validation_result.get("validation_score"))
                return validation_result
            else:  # noqa: RET505
                logger.error("Errore API Gemini: Nessuna risposta ricevuta")
                return {
                    "is_valid": False,
                    "validation_score": 0,
                    "feedback": "Errore API Gemini: Nessuna risposta ricevuta",
                    "improvement_suggestions": "Verifica la connessione e riprova",
                }
        except Exception as e:
            logger.exception("Errore durante la validazione")
            return {
                "is_valid": False,
                "validation_score": 0,
                "feedback": f"Error during validation: {e!s}",
                "improvement_suggestions": "Check the connection and try again",
            }

    def _extract_json_from_text(self, text: str) -> dict | None:
        """Extract JSON from the text response."""
        try:
            json_pattern = r"({[\s\S]*})"
            match = re.search(json_pattern, text)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Unable to extract JSON from the response: %s", e)
            return None
