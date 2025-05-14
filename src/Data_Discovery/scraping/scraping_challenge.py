"""Claude Challenge Code for scraping financial data sources."""

import logging
import re
import secrets
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from retry import retry
from utils import laod_config_yaml

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

    def __init__(
        self,
        config_path: str = "src/Data_Discovery/config/scraping_config/config.yaml",
        user_agent=None,
    ):
        """
        Inizializza il modulo di scraping.

        Args:
            user_agent (str): User agent da utilizzare per le richieste HTTP
            timeout (int): Timeout in secondi per le richieste
            max_retries (int): Numero massimo di tentativi per le richieste
        """
        self.session = requests.Session()
        self.config = laod_config_yaml(config_path)
        self.timeout = self.config["timeout"]
        self.max_retries = self.config["max_retries"]
        # self.prompt = self.config["prompt"]

        if user_agent is None:
            # Rotating user agents to avoid being blocked
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

    @retry(tries=1, delay=3, backoff=2, jitter=1)
    def get_page(self, url: str) -> str | None:
        """Load the HTML page from the given URL.

        Args:
            url (str): url of the page to load.

        Returns
        -------
            str: HTML content of the page or None if failed to load
        """
        try:
            # Sleep to avoid being blocked by the server
            time.sleep(self.request_delay)

            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                return response.text
            logger.warning(f"Status code for the {url}: {response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"Errore durante il download della pagina {url}: {e}")
            raise  # The retry decorator will handle the retry logic

    def find_company_website_with_ai(self, company_name: str) -> str | None:
        """
        Look for the official website of the company.

        Args:
            company_name (str): Name of the company

        Returns
        -------
            str: URL of the company's website or None if not found
        """
        self.web_scraping_code = self.call(self.prompt, company_name)

        # Load the code and run it

        # TODO if it is not correct retry giving the llm the error got

        return

    def find_company_website(self, company_name: str) -> str | None:
        """
        Look for the official website of the company.

        Args:
            company_name (str): Name of the company

        Returns
        -------
            str: URL of the company's website or None if not found
        """
        try:
            # Alternative approch and direct approch

            # Start trying to build a direct URL from the company name
            company_tokens = self._tokenize_company_name(company_name.lower())

            # Remove common tokens that are not significant for the domain
            significant_tokens = [
                t for t in company_tokens if len(t) > 2 and t not in ["inc", "ltd", "the", "and", "corp"]
            ]
            if significant_tokens:
                # Try to build a domain from the first two significant tokens
                company_domain = significant_tokens[0].lower()
                if len(significant_tokens) > 1:
                    company_domain += significant_tokens[1].lower()

                # Try to build potential domains
                potential_domains = [
                    f"https://www.{company_domain}.com/",
                    f"https://{company_domain}.com/",
                    f"https://www.{company_domain}.org/",
                    f"https://www.{significant_tokens[0]}.com/",
                ]

                for domain in potential_domains:
                    try:
                        logger.info(f"Attempting direct access to {domain}")
                        html = self.get_page(domain)
                        if html:
                            return domain
                    except Exception:
                        continue

            #  DuckDuckGo search for the official website
            search_url = f"https://duckduckgo.com/html/?q={company_name}+official+website"
            html = self.get_page(search_url)

            if not html:
                # Fallback: prova con un approccio SEC per aziende USA
                if self._could_be_us_company(company_name):
                    logger.info(f"Tentativo di ricerca SEC diretta per {company_name}")
                    return None  # Questo farà sì che il codice passi direttamente alla ricerca SEC
                return None

            soup = BeautifulSoup(html, "html.parser")
            results = soup.find_all("a", {"class": "result__url"})

            # Filter the results to obtain plausible corporate domains
            for result in results:
                url = result.get("href")
                if url and self._is_corporate_domain(url, company_name):
                    # verify if the URL is valid and accessible and the official website
                    return self._normalize_url(url)

            # Alternative method: search the results page for any URL containing parts of the company name
            all_links = soup.find_all("a")
            for link in all_links:
                url = link.get("href")
                if url and self._is_potential_corporate_domain(url, company_name):
                    return self._normalize_url(url)

            return None
        except Exception as e:
            logger.error(f"Error while searching for the website of {company_name}: {e}")
            return None

    def _is_corporate_domain(self, url: str, company_name: str) -> bool:
        """Check if a URL is likely the corporate domain."""
        domain = urlparse(url).netloc

        # remove the protocol and www
        domain = domain.lower().replace("www.", "")
        company_tokens = set(self._tokenize_company_name(company_name.lower()))

        # Check if the domain contains significant tokens from the company name
        return any(token in domain for token in company_tokens if len(token) > 2)

    def _is_potential_corporate_domain(self, url: str, company_name: str) -> bool:
        """Verifica meno stringente per identificare possibili domini aziendali."""
        # Rimuovi parametri e frammenti
        url = url.split("?")[0].split("#")[0]

        # Ignora URL di motori di ricerca e siti noti non aziendali
        non_corporate_domains = [
            "google.",
            "facebook.",
            "youtube.",
            "linkedin.",
            "twitter.",
            "amazon.",
            "bing.",
            "yahoo.",
            "instagram.",
            "wikipedia.",
        ]

        if any(nd in url.lower() for nd in non_corporate_domains):
            return False

        # Estrai il dominio
        domain = urlparse(url).netloc
        if not domain:
            return False

        # Verifica se parti del nome dell'azienda sono nel dominio
        domain = domain.lower()
        company_tokens = self._tokenize_company_name(company_name.lower())

        # Controlla sovrapposizione tra i token significativi e il dominio
        significant_tokens = [t for t in company_tokens if len(t) > 2 and t not in ["inc", "ltd", "the", "and", "corp"]]
        return any(token in domain for token in significant_tokens)

    def _tokenize_company_name(self, name: str) -> list:
        """Split the company name into significant tokens."""
        # Rimuovi elementi comuni come Inc, Corp, Ltd
        cleaned = re.sub(
            r"\b(inc|corp|corporation|ltd|limited|llc|group|holding|holdings)\b", "", name, flags=re.IGNORECASE
        )

        # Dividi in token
        tokens = re.findall(r"\b\w+\b", cleaned)
        return [t for t in tokens if len(t) > 1]

    def _normalize_url(self, url: str) -> str:
        """Normalize a URL ensuring it is complete and valid."""
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url.lstrip("/")

        # Remove parameters and fragments
        url = url.split("?")[0].split("#")[0]

        # Ensure it ends with a slash
        if not url.endswith("/"):
            url += "/"

        return url

    def find_investor_relations_page(self, company_url: str) -> str | None:
        """Find the investor relations page of the company.

        Args:
            company_url (str): URL of the company's website.

        Returns
        -------
            str: URL of the investor relations page or None if not found
        """
        try:
            # Scarica la home page
            html = self.get_page(company_url)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")

            # Cerca link che contengono termini relativi a IR
            ir_keywords = [
                "investor",
                "investors",
                "investor relations",
                "ir/",
                "financials",
                "shareholders",
                "financial information",
                "annual report",
                "quarterly report",
            ]

            # Cerca nei menu principali e nei footer
            for link in soup.find_all("a"):
                text = link.get_text().lower().strip()
                href = link.get("href")

                if not href:
                    continue

                # Controlla se il testo del link o l'URL contiene parole chiave IR
                if any(keyword in text or keyword in href.lower() for keyword in ir_keywords):
                    return urljoin(company_url, href)

            # Metodo alternativo: cerca nella sitemap se disponibile
            sitemap_url = urljoin(company_url, "sitemap.xml")
            try:
                sitemap_content = self.get_page(sitemap_url)
                if sitemap_content:
                    sitemap_soup = BeautifulSoup(sitemap_content, "xml")
                    for loc in sitemap_soup.find_all("loc"):
                        url = loc.text
                        if any(keyword in url.lower() for keyword in ir_keywords):
                            return url
            except Exception:
                pass  # Ignora gli errori nella ricerca della sitemap

            return None
        except Exception as e:
            logger.error(f"Errore durante la ricerca della pagina IR su {company_url}: {e}")
            return None

    def find_financial_reports(self, ir_page_url: str, source_type: str = "Annual Report") -> list:
        """Look for financial reports on the investor relations page.

        Args:
            ir_page_url (str): URL of the investor relations page.
            source_type (str): Type of financial report (e.g., "Annual Report", "Quarterly Report", "Consolidated").

        Returns
        -------
            list: List of tuples (url, year) of financial reports found.
        """
        try:
            html = self.get_page(ir_page_url)
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")

            # Determina le parole chiave in base al tipo di report
            if source_type.lower() == "annual report" or source_type.lower() == "annual":
                keywords = [
                    "annual report",
                    "annual filing",
                    "10-k",
                    "yearly report",
                    "form 10-k",
                    "annual financial report",
                    "year-end report",
                ]
            elif source_type.lower() == "quarterly report" or source_type.lower() == "quarterly":
                keywords = ["quarterly report", "quarterly filing", "10-q", "form 10-q", "q1", "q2", "q3", "q4"]
            elif source_type.lower() == "consolidated":
                keywords = [
                    "consolidated financial",
                    "consolidated statement",
                    "consolidated report",
                    "consolidated annual report",
                    "consolidated results",
                ]
            else:
                keywords = ["financial report", "financial statement", "financial results", "earnings report"]

            # Cerca report sia nei link testuali che nei PDF/documenti
            results = []

            # Cerca link a documenti PDF o simili
            for link in soup.find_all("a"):
                text = link.get_text().strip()
                href = link.get("href", "")

                # Verifica se è un link a un documento finanziario
                is_financial_doc = any(keyword in text.lower() or keyword in href.lower() for keyword in keywords)
                is_document = href.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".html"))

                if is_financial_doc and (is_document or "download" in href.lower()):
                    # Estrai l'anno dal testo del link o dal nome del file
                    year = self._extract_year_from_text(text) or self._extract_year_from_url(href)

                    if year:
                        full_url = urljoin(ir_page_url, href)
                        results.append((full_url, year))

            # Ordina i risultati per anno (più recente prima)
            results.sort(key=lambda x: x[1], reverse=True)

            return results
        except Exception as e:
            logger.error(f"Errore durante la ricerca di report finanziari su {ir_page_url}: {e}")
            return []

    def _extract_year_from_text(self, text: str) -> str | None:
        """Extract the year from the text."""
        # Regex pattern to match various year formats
        year_patterns = [
            r"20\d{2}",  # Anno standard a 4 cifre
            r"FY\s*20\d{2}",  # Anno fiscale
            r"20\d{2}[/-]20\d{2}",  # Intervallo di anni
        ]

        for pattern in year_patterns:
            match = re.search(pattern, text)
            if match:
                year_text = match.group(0)
                # Extract only the year part (e.g., 2023 from FY2023 or 2023-2024)
                return re.search(r"20\d{2}", year_text).group(0)

        return None

    def _extract_year_from_url(self, url: str) -> str | None:
        """Extract the year from the URL."""
        # Simile all'estrazione dal testo, ma specifico per URL
        year_patterns = [
            r"20\d{2}",  # Anno standard
            r"FY-?20\d{2}",  # FY2023 o FY-2023
            r"AR-?20\d{2}",  # AR2023 o AR-2023 (Annual Report)
        ]

        for pattern in year_patterns:
            match = re.search(pattern, url)
            if match:
                year_text = match.group(0)
                # Extract only the year part (e.g., 2023 from FY2023 or 2023-2024)
                return re.search(r"20\d{2}", year_text).group(0)

        return None

    def find_sec_filings(self, company_name: str, form_type="10-K") -> list:
        """Look for SEC filings for the company.

        Args:
            company_name (str): Name of the company
            form_type (str): Type of SEC filing (e.g., "10-K", "10-Q").

        Returns
        -------
            list: Lista di tuple (url, anno) dei filing trovati
        """
        try:
            # Simulazione di ricerca SEC (in produzione si utilizzerebbe l'API SEC EDGAR)
            # Per semplicità utilizziamo un approccio di scraping di base
            search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={company_name}&type={form_type}&count=10"
            html = self.get_page(search_url)

            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            results = []

            # Cerca le tabelle dei risultati
            filing_items = soup.find_all("tr")
            for item in filing_items:
                # Cerca la data del filing
                date_elem = item.find("td", {"nowrap": "nowrap"})
                if not date_elem:
                    continue

                date_text = date_elem.get_text().strip()
                year_match = re.search(r"20\d{2}", date_text)
                if not year_match:
                    continue

                year = year_match.group(0)

                # Cerca il link ai documenti
                doc_link = item.find("a", text=re.compile(r"Documents"))
                if not doc_link:
                    continue

                doc_url = urljoin("https://www.sec.gov", doc_link.get("href"))

                results.append((doc_url, year))

            # Ordina per anno (più recente prima)
            results.sort(key=lambda x: x[1], reverse=True)

            return results
        except Exception as e:
            logger.error(f"Errore durante la ricerca di filing SEC per {company_name}: {e}")
            return []

    def scrape_financial_sources(self, company_name: str, source_type: str) -> tuple | None:
        """
        Scrape the financial sources for the given company name and source type.

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria

        Returns
        -------
            tuple: (url, year, source_description, confidence)
        """
        logger.info("Start %s (Type: %s)", company_name, source_type)

        # Find the web site of the company
        company_url = self.find_company_website(company_name)

        # If it does not find it, try a a sec reserch (could be a US company)
        if not company_url:
            logger.warning("Impossible to find %s", company_name)

            # Prova con ricerca SEC se potrebbe essere un'azienda USA
            if self._could_be_us_company(company_name):
                logger.info(" Tentative for %s", company_name)
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]
                    return best_url, best_year, "SEC Filing", "MEDIA"

            return None, None, None, "BASSA"

        logger.info("Find %s: %s", company_name, company_url)

        # Look for the page regarding financial data
        ir_page = self.find_investor_relations_page(company_url)
        # If it does not find it, try a sec research, could be a US company
        if not ir_page:
            logger.warning("Impossible to find the IR for the %s", company_name)

            if self._could_be_us_company(company_name):
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]
                    return best_url, best_year, "SEC Filing", "MEDIA"

            return None, None, None, "BASSA"

        logger.info("Find IR page %s: %s", company_name, ir_page)

        # Check the financial report on the IR page
        reports = self.find_financial_reports(ir_page, source_type)

        # If no reports found, try SEC filings as a fallback
        if not reports and self._could_be_us_company(company_name):
            form_type = "10-K" if source_type.lower() in ["annual", "annual report"] else "10-Q"
            sec_results = self.find_sec_filings(company_name, form_type)
            reports.extend(sec_results)

        if not reports:
            logger.warning("No report found for %s", company_name)
            return None, None, None, "BASSA"

        # Select the most recent report
        best_url, best_year = reports[0]

        # Determine source description and confidence level
        if "sec.gov" in best_url:
            source_description = "SEC Filing"
            confidence = "ALTA"
        elif best_url.lower().endswith(".pdf"):
            source_description = f"{source_type} PDF"
            confidence = "ALTA"
        else:
            source_description = source_type
            confidence = "MEDIA"

        logger.info("Find report for %s: %s (Year: %s)", company_name, best_url, best_year)

        return best_url, best_year, source_description, confidence

    def _could_be_us_company(self, company_name: str) -> bool:
        """Check if the company name suggests it could be a US company."""
        us_indicators = ["Inc", "Inc.", "Corp", "Corp.", "LLC", "LLP", "Co.", "USA", "America", "US "]
        return any(indicator in company_name for indicator in us_indicators)
