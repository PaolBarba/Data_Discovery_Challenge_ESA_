"""Claude Challenge Code for scraping financial data sources."""

import json
import logging
import re
import secrets
import sys
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from utils import load_config_yaml, save_code

from Data_Discovery.model.prompt_generator import PromptGenerator
from Data_Discovery.model.prompt_tuner import PromptTuner

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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

    def _create_retry_session(self) -> requests.Session:
        """Create a requests session with retry strategy."""
        session = requests.Session()
        retries = Retry(total=self.max_retries, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def find_company_website_with_ai(self, company_name: str) -> str | None:
        """Use AI to find the official website of a company."""
        try:
            prompt = self.prompt_generator.generate_prompt(company_name, source_type="Annual Report")
            response = self.prompt_generator.call(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception:
            logger.exception("AI failed to find company website")
        return None

    def ai_web_scraping(self, company_name: str, source_type: str) -> object | None:
        """Generate and safely execute AI scraping code."""
        prompt = self.prompt_generator.generate_web_scraping_prompt(company_name, source_type)
        response = self.prompt_generator.call(prompt)

        if response is None or not hasattr(response, "text") or not response.text:
            logger.warning("Empty AI scraping response for %s", company_name)
            return None

        code_text = re.sub(r"^```(?:python)?|```$", "", response.text.strip(), flags=re.MULTILINE)
        Path("generated_code").mkdir(parents=True, exist_ok=True)
        code_file_path = Path("generated_code") / f"{company_name}_{source_type}.py"

        try:
            save_code(code_text, code_file_path)
        except Exception:
            logger.exception("Failed to write AI-generated code")
            return None

        logger.info("Generated scraping code saved to: %s", code_file_path)
        return self.load_and_run_code(code_file_path)

    def load_and_run_code(self, code_file_path: Path) -> object | None:
        """Dynamically load and execute a Python script. Be cautious with this."""
        try:
            code = Path(code_file_path).read_text(encoding="utf-8")
            code = re.sub(r"^```(?:python)?|```$", "", code.strip(), flags=re.MULTILINE)

            module_vars = {"__file__": code_file_path, "__name__": "__main__", "__package__": None}
            exec(compile(code, code_file_path, "exec"), module_vars)  # noqa: S102
            return module_vars.get("result")  # Assuming the script sets a variable named 'result'
        except Exception:
            logger.exception("Execution of AI-generated code failed")
            return None

    def is_page_not_found(self, url: str) -> bool:
        """Check if the URL returns a 403/404 error."""
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            logger.warning("Failed to check URL: %s", e)
            return True
        else:
            return response.status_code in (403, 404)

    def scrape_financial_sources(self, company_name: str, source_type: str) -> Any:
        """Try to find financial sources using prompt tuning, fall back to AI scraping."""
        attempt = 0
        cleaned_response = None
        url = ""
        while attempt < self.max_retries:
            try:
                if attempt == 0:
                    logger.info("Attempting to fetch website for '%s'", company_name)
                    raw_response = self.find_company_website_with_ai(company_name)
                else:
                    logger.info("Retrying with tuned prompt (%d/%d)", attempt, self.max_retries)
                    improved_prompt = self.prompt_tuner.improve_prompt(url, company_name)
                    tuned_response = self.prompt_tuner.call(improved_prompt)
                    raw_response = tuned_response.text.strip() if tuned_response else None

                if not raw_response:
                    attempt += 1
                    continue

                cleaned_response = re.sub(r"^```(?:json)?|```$", "", raw_response.strip(), flags=re.IGNORECASE)
                data = json.loads(cleaned_response)
                url = data.get("url")

                if not url or self.is_page_not_found(url):
                    logger.warning("Invalid or missing page for '%s' on attempt %d", company_name, attempt + 1)
                    attempt += 1
                    continue

                data["response_status"] = "Page found"
                return tuple(data.values())

            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Error parsing or processing response on attempt %d: %s", attempt + 1, e)
                attempt += 1

        logger.info("Falling back to AI web scraping for '%s'", company_name)
        attempt_web_scraping = 0
        while attempt_web_scraping < self.max_retries:
            logger.info("Attempting AI web scraping for '%s' (attempt %d)", company_name, attempt_web_scraping + 1)
            data = self.ai_web_scraping(company_name, source_type)
            if data is None:
                logger.warning("AI web scraping failed for '%s' on attempt %d", company_name, attempt_web_scraping + 1)
                attempt_web_scraping += 1
                continue
            url = data.get("url")
            data["response_status"] = "Page not found" if self.is_page_not_found(url) else "Page found"
            if data["response_status"] == "Page found":
                break
            attempt_web_scraping += 1

        if not data:
            return None, None, None, None, "Page not found"
        if len(data.values()) != 5:
            return None, None, None, None, "Page not found"
        return tuple(data.values())
