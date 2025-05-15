"""Claude Challenge Code for scraping financial data sources."""

import json
import logging
import re
import secrets
import sys

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry  # type: ignore
from utils import load_config_yaml

from Data_Discovery.model.prompt_generator import PromptGenerator
from Data_Discovery.model.prompt_tuner import PromptTuner

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# TODO: The class has too many responsibilities, consider splitting it into smaller classes
# TODO: Configuration must be externalized, consider using a config file or environment variables
# TODO: Check if some code is repeated, if so, consider creating a helper function
# TODO: Check if some code can be simplified, if so, consider using a simpler approach
# TODO: Check if some code is useless, if so, consider removing it


class WebScraperModule:
    """Module for web scraping financial data sources."""

    def __init__(self):
        """
        Initialize the web scraper with necessary configurations.

        Args:
            user_agent (str): User agent da utilizzare per le richieste HTTP
            timeout (int): Timeout in secondi per le richieste
            max_retries (int): Numero massimo di tentativi per le richieste.
        """
        self.session = requests.Session()
        self.config = load_config_yaml("src/Data_Discovery/config/scraping_config/config.yaml")
        self.timeout = self.config["timeout"]
        self.max_retries = self.config["max_retries"]
        self.prompt_generator = PromptGenerator()
        self.prompt_tuner = PromptTuner()
        user_agents = self.config["user_agents"]
        # Random choice of agents, random generator are not suitable for cryptography https://docs.astral.sh/ruff/rules/suspicious-non-cryptographic-random-usage/
        user_agent = secrets.choice(user_agents)

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "max-age=0",
                "Connection": "keep-alive",
            }
        )

        # Add the delay to avoid being blocked by the server
        self.request_delay = self.config["request_delay"]

    def find_company_website_with_ai(self, company_name: str) -> str | None:
        """
        Look for the official website of the company.

        Args:
            company_name (str): Name of the company

        Returns
        -------
            str: URL of the company's website or None if not found
        """
        self.company_prompt = self.prompt_generator.generate_prompt(
            company_name=company_name, source_type="Annual Report"
        )

        response = self.prompt_generator.call(self.company_prompt)
        # Load the code and run it
        if response and response.text:
            return response.text.strip()
        return None

    def scrape_financial_sources(self, company_name: str, source_type: str) -> tuple | None:
        """Scrape the financial sources for the given company name and source type.

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria

        Returns
        -------
            tuple: (url, year, source_description, confidence)
        """
        max_retries = 2
        attempt = 0

        while attempt < max_retries:
            values = [None, None, None, None]

            if attempt == 0:
                logger.info("Attempting initial fetch for company: %s", company_name)
                raw_response = self.find_company_website_with_ai(company_name)
            else:
                logger.info("Retrying (%d/%d) with improved prompt...", attempt, max_retries)
                new_prompt = self.prompt_tuner.improve_prompt(values[0], company_name)
                model_response = self.prompt_tuner.call(new_prompt)
                if model_response:
                    raw_response = model_response.text.strip()
            # Robust cleaning of markdown-wrapped response
            if raw_response:
                cleaned_response = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response, flags=re.IGNORECASE)
            logger.info("Cleaned response: '%s'", cleaned_response)

            if not cleaned_response:
                logger.warning("Attempt %d: Empty response for company '%s'.", attempt + 1, company_name)
                attempt += 1
                continue

            try:
                data = json.loads(cleaned_response)
            except json.JSONDecodeError as e:
                logger.exception("Attempt %d: JSON decode error for company '%s': %s", attempt + 1, company_name, str(e))  # noqa: TRY401
                attempt += 1
                continue

            values = list(data.values())

            if not values or self.is_page_not_found(values[0]):
                logger.warning("Attempt %d: Invalid or missing page for company '%s'.", attempt + 1, company_name)
                attempt += 1
                continue
            else:
                return tuple(values)

        return tuple(values)

    def is_page_not_found(self, url) -> bool:
        """
        Check if the page is not found (404 error).

        Args:
            url (str): URL to check.

        Returns
        -------
            bool: True if the page is not found, False otherwise.
        """
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retries))

        try:
            response = session.get(url, timeout=10)
            return response.status_code == 404  # noqa: TRY300
        except requests.exceptions.RequestException as e:
            logger.exception("Request failed: %s", e)  # noqa: TRY401
            return True
