import json
import logging
import os
import re
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import google.generativeai as genai
import pandas as pd
import requests
from bs4 import BeautifulSoup
from retry import retry
from tqdm import tqdm

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Configurare l'API di Google Gemini
API_KEY = os.environ.get("GOOGLE_API_KEY", "")  # Inserisci la tua API key se non è impostata come variabile d'ambiente
genai.configure(api_key=API_KEY)


class WebScraperModule:
    """Modulo dedicato al web scraping per la ricerca di dati finanziari."""

    def __init__(self, user_agent=None, timeout=60, max_retries=5):
        """
        Inizializza il modulo di scraping.

        Args:
            user_agent (str): User agent da utilizzare per le richieste HTTP
            timeout (int): Timeout in secondi per le richieste
            max_retries (int): Numero massimo di tentativi per le richieste
        """
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries

        if user_agent is None:
            # Rotazione di user agent per evitare blocchi
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36 Edg/92.0.902.84",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36",
            ]
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

        # Aggiunta di un ritardo tra le richieste per evitare blocchi
        self.request_delay = 2  # secondi

    @retry(tries=5, delay=3, backoff=2, jitter=1)
    def get_page(self, url:str)-> str | None:
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

    def find_company_website(self, company_name:str)-> str | None:
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

            # Rimuovi parole comuni e prendi le prime due parole significative
            significant_tokens = [
                t for t in company_tokens if len(t) > 2 and t not in ["inc", "ltd", "the", "and", "corp"]
            ]
            if significant_tokens:
                # Prova a costruire un URL diretto
                company_domain = significant_tokens[0].lower()
                if len(significant_tokens) > 1:
                    company_domain += significant_tokens[1].lower()

                # Prova diversi domini comuni
                potential_domains = [
                    f"https://www.{company_domain}.com/",
                    f"https://{company_domain}.com/",
                    f"https://www.{company_domain}.org/",
                    f"https://www.{significant_tokens[0]}.com/",
                ]

                for domain in potential_domains:
                    try:
                        logger.info(f"Tentativo di accesso diretto a {domain}")
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

            # Filtra i risultati per ottenere domini aziendali plausibili
            for result in results:
                url = result.get("href")
                if url and self._is_corporate_domain(url, company_name):
                    # Verifica che sia davvero un sito aziendale
                    return self._normalize_url(url)

            # Metodo alternativo: cerca nella pagina dei risultati qualsiasi URL che contenga parti del nome dell'azienda
            all_links = soup.find_all("a")
            for link in all_links:
                url = link.get("href")
                if url and self._is_potential_corporate_domain(url, company_name):
                    return self._normalize_url(url)

            return None
        except Exception as e:
            logger.error(f"Errore durante la ricerca del sito web di {company_name}: {e}")
            return None

    def _is_corporate_domain(self, url:str, company_name:str)-> bool:
        """Verifica se un URL è probabilmente il dominio aziendale."""
        domain = urlparse(url).netloc

        # Rimuovi www. e converti in lowercase
        domain = domain.lower().replace("www.", "")
        company_tokens = set(self._tokenize_company_name(company_name.lower()))

        # Verifica se almeno un token significativo del nome dell'azienda è nel dominio
        return any(token in domain for token in company_tokens if len(token) > 2)

    def _is_potential_corporate_domain(self, url:str, company_name:str)-> bool:
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

    def _tokenize_company_name(self, name:str)-> list:
        """Divide il nome dell'azienda in token significativ."""
        # Rimuovi elementi comuni come Inc, Corp, Ltd
        cleaned = re.sub(
            r"\b(inc|corp|corporation|ltd|limited|llc|group|holding|holdings)\b", "", name, flags=re.IGNORECASE
        )

        # Dividi in token
        tokens = re.findall(r"\b\w+\b", cleaned)
        return [t for t in tokens if len(t) > 1]

    def _normalize_url(self, url:str)-> str:
        """Normalizza un URL garantendo che sia completo e valido."""
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url.lstrip("/")

        # Rimuovi parametri e frammenti
        url = url.split("?")[0].split("#")[0]

        # Assicurati che termini con uno slash
        if not url.endswith("/"):
            url += "/"

        return url

    def find_investor_relations_page(self, company_url:str)-> str | None:
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

    def find_financial_reports(self, ir_page_url: str, source_type: str ="Annual Report")-> list:
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

    def _extract_year_from_text(self, text:str)-> str | None:
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

    def _extract_year_from_url(self, url:str)-> str | None:
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

    def find_sec_filings(self, company_name:str, form_type="10-K")-> list:
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

    def scrape_financial_sources(self, company_name:str, source_type: str)-> tuple | None:
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

        # Step 1: Trova il sito web aziendale
        company_url = self.find_company_website(company_name)
        if not company_url:
            logger.warning("Impossible to find %s", company_name)

            # Prova con ricerca SEC se potrebbe essere un'azienda USA
            if self._could_be_us_company(company_name):
                logger.info(" Tentative for %s", company_name)
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]  # Il più recente
                    return best_url, best_year, "SEC Filing", "MEDIA"

            return None, None, None, "BASSA"

        logger.info("Find %s: %s", company_name, company_url)

        # Step 2: Trova la pagina delle relazioni con gli investitori
        ir_page = self.find_investor_relations_page(company_url)
        if not ir_page:
            logger.warning("Impossible to find the IR for the %s", company_name)

            # Prova con ricerca SEC come fallback
            if self._could_be_us_company(company_name):
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]
                    return best_url, best_year, "SEC Filing", "MEDIA"

            return None, None, None, "BASSA"

        logger.info("Find IR page %s: %s", company_name, ir_page)

        # Step 3: Find financial reports on the IR page
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

    def _could_be_us_company(self, company_name):
        """Check if the company name suggests it could be a US company."""
        us_indicators = ["Inc", "Inc.", "Corp", "Corp.", "LLC", "LLP", "Co.", "USA", "America", "US "]
        return any(indicator in company_name for indicator in us_indicators)


class PromptGenerator:
    """Mananage the prompt generation and optimization for the financial data source finder."""

    def __init__(self):
        """Inizialize the prompt generator."""
        # Prompt base che verrà ottimizzato TODO: Ottimizzare e tradurre in inglese 
        self.base_prompt_template = """
        SEI UN ESPERTO RICERCATORE FINANZIARIO specializzato nell individuare fonti ufficiali di dati finanziari per multinazionali.

        TASK: Trova la fonte più autorevole e specifica di dati finanziari per "{company_name}" (tipologia di fonte: {source_type}).

        ISTRUZIONI DETTAGLIATE:

        1. TROVARE L'URL PIÙ SPECIFICO possibile che punti DIRETTAMENTE alla pagina contenente i dati finanziari più recenti.
           - NON fornire URL generici della homepage dell'azienda
           - PREFERIRE SEMPRE URL che puntano direttamente a bilanci/report specifici anziché pagine generali
           - PRIORITÀ: pagina IR ufficiale > documento specifico > database finanziario > aggregatore

        2. IDENTIFICARE L'ANNO DI RIFERIMENTO più recente disponibile:
           - Deve essere l'anno fiscale/di riferimento dei dati, NON l'anno di pubblicazione
           - Se disponibili più periodi, scegli il più recente (annuale o trimestrale)
           - Specifica l'anno in formato numerico (es. "2023" o "2023-2024")

        PRIORITÀ DI FONTE in base al tipo "{source_type}":
        - Per "Annual Report": IR website > SEC filings > PDF ufficiali > database finanziari
        - Per "Consolidated": documenti consolidati ufficiali > IR website > database finanziari
        - Per "Quarterly": quarterly report ufficiali > IR website > database finanziari
        - Per qualsiasi altro tipo: IR website > documenti ufficiali > database finanziari attendibili

        SPECIFICHE TECNICHE PER L'URL:
        - I documenti PDF/XBRL sono ALTAMENTE PREFERIBILI rispetto a pagine HTML generiche
        - URL di IR (Investor Relations) sono PREFERIBILI rispetto a motori di ricerca o aggregatori
        - Per aziende USA, i filing SEC (10-K, 10-Q) sono OTTIMALI
        - Per aziende UE, i report ESEF/XBRL sono OTTIMALI

        ISTRUZIONI PER LA RISPOSTA:
        - Restituisci un oggetto JSON con questa ESATTA struttura, SENZA TESTO ADDIZIONALE:
        {{
            "url": "URL_PRECISO_DELLA_FONTE",
            "year": "ANNO_DI_RIFERIMENTO",
            "confidence": "ALTA/MEDIA/BASSA",
            "source_type": "TIPO_DI_FONTE"
        }}

        {optimization_instructions}

        IMPORTANTE: Se trovi più fonti, seleziona SOLO la migliore in base ai criteri sopra. La precisione è fondamentale.
        """

        # Istruzioni di ottimizzazione iniziali (vuote)
        self.optimization_instructions = ""

        # Dizionario per memorizzare prompt specifici per azienda
        self.company_specific_prompts = {}

        # Contatore di ottimizzazioni per azienda
        self.optimization_counter = {}

    def generate_prompt(self, company_name, source_type):
        """
        Generate the prompt for the given company name and source type.

        Args:
            company_name (str): Name of the company
            source_type (str): Type of financial source (e.g., "Annual Report", "Quarterly Report", "Consolidated").

        Returns
        -------
            str: Prompt optimize.
        """
        # Verify if the company name is already in the specific prompts
        if company_name in self.company_specific_prompts:
            return self.company_specific_prompts[company_name]

        # Istruction for optimization
        optimization_text = self.optimization_instructions

        # Enrich the prompt with additional information if available
        company_info = self._get_company_additional_info(company_name)
        if company_info:
            optimization_text += f"\n\nAdditioanl Information: {company_info}"

        # Generate the final prompt
        return self.base_prompt_template.format(
            company_name=company_name, source_type=source_type, optimization_instructions=optimization_text
        )

    def optimize_prompt(self, company_name:str, feedback:dict, current_prompt:str, scraping_results:tuple)-> str:
        """
        Optimize the prompt based on feedback and scraping results.

        Args:
            company_name (str): Name of the company
            feedback (dict): Feedback received (problems, suggestions, critical points)
            current_prompt (str): Current prompt to be optimized
            scraping_results (tuple): Results from web scraping (url, year, description, confidence)

        Returns
        -------
            str: Prompt ottimizzato
        """
        # Increment the optimization counter for the company
        if company_name not in self.optimization_counter:
            self.optimization_counter[company_name] = 0
        self.optimization_counter[company_name] += 1

        # Limit the number of optimizations to 5 attempts
        if self.optimization_counter[company_name] > 5:
            logger.warning("Reached max optimization attempts for %s, using scraping results", company_name)
            return self._generate_scraping_based_prompt(company_name, scraping_results)

        # Generate the optimization request
        optimization_request = self._create_optimization_request(
            company_name, feedback, current_prompt, scraping_results
        )

        try:
            # Ask Google Gemini to optimize the prompt
            model = genai.GenerativeModel("gemini-1.5-pro-latest")
            response = model.generate_content(
                optimization_request,
                generation_config={
                    "temperature": 0.2,
                    "top_p": 0.95,
                    "max_output_tokens": 2048,
                },
            )

            # Extract the optimized prompt from the response
            optimized_prompt = response.text.strip()

            # Verify the optimized prompt
            if len(optimized_prompt) < 100 or "{company_name}" not in optimized_prompt:
                logger.warning("Invalid optimized prompt for %s: %s", company_name, optimized_prompt)
                return self._generate_scraping_based_prompt(company_name, scraping_results)

            # Store the optimized prompt for the company
            self.company_specific_prompts[company_name] = optimized_prompt

            logger.info(
                "Optimized prompt for %s (Attempt %s): %s",
                company_name,
                self.optimization_counter[company_name],
                optimized_prompt
            )

            return optimized_prompt

        except Exception as e:
            logger.error(f"Errore durante l'ottimizzazione del prompt per {company_name}: {e}")
            # In case of failure, use the scraping results as a fallback
            return self._generate_scraping_based_prompt(company_name, scraping_results)

    def _create_optimization_request(self, company_name, feedback, current_prompt, scraping_results):
        """create the request for optimization of the prompt."""
        scraping_info = ""
        if scraping_results:
            url, year, desc, conf = scraping_results
            scraping_info = f"""
            Il web scraping ha trovato le seguenti informazioni:
            - URL: {url if url else 'Non trovato'}
            - Anno: {year if year else 'Non trovato'}
            - Tipo di fonte: {desc if desc else 'Non identificato'}
            - Confidenza: {conf}
            """

        return f"""
        SEI UN ESPERTO DI PROMPT ENGINEERING specializzato nell'ottimizzazione di prompt per sistemi di intelligenza artificiale.

        TASK: Ottimizzare il prompt esistente per migliorare la ricerca di dati finanziari per l'azienda "{company_name}".

        FEEDBACK DALL'ULTIMO TENTATIVO:
        - Problemi identificati: {feedback.get('problems', 'Nessun dato trovato o validato')}
        - Suggerimenti: {feedback.get('suggestions', 'N/A')}
        - Punti critici: {feedback.get('critical_points', 'N/A')}

        {scraping_info}

        PROMPT ATTUALE:
        ```
        {current_prompt}
        ```

        ISTRUZIONI PER L'OTTIMIZZAZIONE:
        1. Mantieni la struttura generale del prompt
        2. Aggiungi istruzioni specifiche per risolvere i problemi identificati
        3. Migliora la precisione delle richieste per ottenere URL diretti ai documenti
        4. Assicurati che il prompt richieda esplicitamente l'anno fiscale corretto
        5. Rafforza le priorità di ricerca in base al tipo di fonte richiesta

        RESTITUISCI SOLO IL NUOVO PROMPT OTTIMIZZATO, SENZA SPIEGAZIONI O COMMENTI AGGIUNTIVI.
        """

    def _generate_scraping_based_prompt(self, company_name, scraping_results):
        """Genera un prompt basato sui risultati dello scraping quando l'ottimizzazione fallisce"""
        if not scraping_results or not any(scraping_results):
            # Nessun risultato di scraping utilizzabile, usa un prompt generico migliorato
            return self.base_prompt_template.format(
                company_name=company_name,
                source_type="Annual Report",
                optimization_instructions="ATTENZIONE: Cerca con particolare attenzione, i tentativi precedenti non hanno prodotto risultati validi.",
            )

        url, year, desc, conf = scraping_results

        # Crea un prompt che incorpora i risultati dello scraping come suggerimenti
        domain_hint = ""
        if url:
            try:
                domain = urlparse(url).netloc
                domain_hint = f"\n- Considera il dominio {domain} che sembra promettente per questa ricerca"
            except:
                pass

        year_hint = ""
        if year:
            year_hint = (
                f"\n- L'anno fiscale {year} sembra essere disponibile, ma verifica se esistono report più recenti"
            )

        optimization_text = f"""
        SUGGERIMENTI BASATI SU RICERCHE PRECEDENTI:
        - Il tipo di fonte '{desc}' sembra appropriato per questa azienda{domain_hint}{year_hint}
        - La precedente ricerca ha avuto un livello di confidenza '{conf}', cerca di migliorarlo
        """

        return self.base_prompt_template.format(
            company_name=company_name, source_type=desc or "Annual Report", optimization_instructions=optimization_text
        )

    def _get_company_additional_info(self, company_name):
        """
        Fornisce informazioni specifiche predefinite (hints) per alcune aziende.
        Questi sono suggerimenti euristici basati su suffissi comuni e nomi noti.
        L'accuratezza non è garantita e l'elenco non è esaustivo.
        """
        # Dizionario di hints (chiave è una parte significativa del nome, case-insensitive)
        # NOTA: Mantenere le chiavi in lowercase per il matching
        known_info = {
            # Esempi USA/Canada (INC, CORP, CO, PLC-Ireland/Canada)
            "johnson controls": "Azienda globale (registrata in Irlanda, sede USA?). Cerca 'Investors' sul sito .com. Considera SEC filings (10-K/Q).",
            "magna international": "Azienda Canadese. Cerca 'Investors' sul sito .com.",
            "abbott laboratories": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (abbottinvestor.com).",
            "oracle corp": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.oracle.com). FY finisce Maggio.",
            "procter & gamble": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (pginvestor.com). FY finisce Giugno.",
            "warner bros. discovery": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ir.wbd.com).",
            "general electric": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ge.com/investor-relations).",
            "aptiv plc": "Azienda globale (registrata in Irlanda, origini USA?). Cerca 'Investors' sul sito .com. Considera SEC filings (10-K/Q).",
            "amazon": "Azienda USA. Focus su SEC filings (10-K, 10-Q) sul sito IR: ir.aboutamazon.com. FY standard (Dicembre).",
            "pfizer inc": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investors.pfizer.com).",
            "coca-cola company": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investors.coca-colacompany.com).",
            "caterpillar inc": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investors.caterpillar.com).",
            "manpowergroup inc.": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.manpowergroup.com).",
            "paramount global": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ir.paramount.com).",
            "hp inc.": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.hp.com). FY finisce Ottobre.",
            "goodyear tire & rubber": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.goodyear.com).",
            "brookfield corporation": "Azienda Canadese. Cerca 'Investors' o 'Shareholders' sul sito .com.",
            "microsoft corporation": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR: microsoft.com/en-us/investor. FY finisce Giugno.",
            "mondelez international": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ir.mondelezinternational.com).",
            "international business machines": "IBM. Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ibm.com/investor).",
            "meta platforms": "Facebook/Meta. Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.fb.com).",
            "walt disney company": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (thewaltdisneycompany.com/investor-relations/). FY finisce Settembre.",
            "pepsico inc": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (pepsico.com/investors).",
            "thermo fisher scientific": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (ir.thermofisher.com).",
            "accenture plc": "Azienda globale (registrata in Irlanda). Cerca 'Investor Relations' sito .com. Considera SEC filings (10-K/Q). FY finisce Agosto.",
            "exxon mobil corp": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (corporate.exxonmobil.com/investors).",
            "dell technologies": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investors.delltechnologies.com). FY finisce Gennaio/Febbraio.",
            "alphabet inc.": "Google. Azienda USA. Focus su SEC filings (10-K, 10-Q) per Alphabet Inc. sul sito IR: abc.xyz/investor/. FY standard (Dicembre).",
            "johnson & johnson": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.jnj.com).",
            "stanley black & decker": "Azienda USA. Focus su SEC filings (10-K, 10-Q) e sito IR (investor.stanleyblackanddecker.com).",
            "eaton corporation": "Azienda globale (registrata in Irlanda). Cerca 'Investor Relations' sito .com. Considera SEC filings (10-K/Q).",
            # Esempi Europa Continentale (AG, SE, SA, NV, SPA, etc.)
            "adecco group ag": "Azienda Svizzera (AG). Cerca 'Investors' sul sito .com.",
            "publicis groupe": "Azienda Francese (SA). Cerca 'Investisseurs' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "gebr. knauf": "Azienda Tedesca (privata?). Potrebbe essere difficile trovare dati pubblici. Cerca 'Presse', 'Unternehmen'.",
            "compagnie de saint gobain": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "engie": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "thyssenkrupp": "Azienda Tedesca (AG). Cerca 'Investoren' o 'Investors' sul sito .com.",
            "voestalpine": "Azienda Austriaca (AG). Cerca 'Investoren' o 'Investors' sul sito .com.",
            "orange": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "accor": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "fcc": "Fomento de Construcciones y Contratas. Azienda Spagnola (SA). Cerca 'Inversores' o 'Investors'.",
            "societe nationale sncf": "Azienda Francese (Statale?). Cerca 'Finance' o 'Groupe'. Potrebbe avere report specifici.",
            "crh plc": "Azienda Irlandese (PLC). Cerca 'Investors' sul sito .com. Controlla per ESEF format.",  # Anche se PLC, base Irlanda -> EU
            "deutsche bahn": "Azienda Tedesca (AG, Statale?). Cerca 'Investor Relations' o 'Finanzberichte'.",
            "safran": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "basf": "Azienda Tedesca (SE). Cerca 'Investor Relations' sul sito basf.com. Controlla per ESEF format.",
            "wpp plc": "Azienda UK (PLC). Cerca 'Investors' sul sito .com.",  # Spostato qui perchè PLC è tipico UK
            "gi group": "Azienda Italiana (Holding, SPA?). Cerca 'Investor Relations' o 'Gruppo'.",
            "acciona": "Azienda Spagnola (SA). Cerca 'Accionistas e Inversores' o 'Investors'.",
            "sodexo": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "akzo nobel nv": "Azienda Olandese (NV). Cerca 'Investors' sul sito .com.",
            "dior": "Parte di LVMH. Azienda Francese. Cerca report LVMH, sezione 'Finance' o 'Investors'.",
            "sonova": "Azienda Svizzera (Holding AG). Cerca 'Investor Relations'.",
            "ikea": "Ingka Holding B.V. Azienda Olandese/Svedese (privata?). Dati finanziari potrebbero essere limitati. Cerca 'About us', 'Reports'.",
            "airbus se": "Azienda Europea (SE, Olanda/Francia/Germania). Cerca 'Investors' o 'Finance' sul sito airbus.com.",
            "etex": "Azienda Belga. Cerca 'Investors' o 'Financial'.",
            "siemens": "Azienda Tedesca (AG). Cerca 'Investor Relations' sul sito .com. Controlla per ESEF. FY finisce Settembre.",
            "mol hungarian oil": "Azienda Ungherese. Cerca 'Investor Relations'.",
            "krones": "Azienda Tedesca (AG). Cerca 'Investoren'.",
            "sanofi": "Azienda Francese (SA). Cerca 'Investisseurs' o 'Investors'.",
            "wurth": "Würth Group. Azienda Tedesca (privata?). Dati potrebbero essere limitati. Cerca 'Unternehmen', 'Presse', 'Reports'.",
            "totalenergies se": "Azienda Francese (SE). Cerca 'Finance' o 'Investors'.",
            "koninklijke ahold delhaize nv": "Azienda Olandese/Belga (NV). Cerca 'Investors'.",
            "hartmann": "Paul Hartmann AG. Azienda Tedesca. Cerca 'Investoren'.",
            "sap": "Azienda Tedesca (SE). Cerca 'Investor Relations' sul sito sap.com.",
            "enel spa": "Azienda Italiana (SPA). Cerca 'Investitori' o 'Investors'.",
            "shv holdings nv": "Azienda Olandese (privata?). Dati potrebbero essere limitati.",
            "bmw": "Bayerische Motoren Werke AG. Azienda Tedesca. Cerca 'Investor Relations'.",
            "thales": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "signify nv": "Ex Philips Lighting. Azienda Olandese (NV). Cerca 'Investor Relations'.",
            "bayer": "Azienda Tedesca (AG). Cerca 'Investoren' o 'Investors'.",
            "veolia environnement": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "tui": "Azienda Tedesca/UK (AG/PLC?). Cerca 'Investors'.",
            "randstad nv": "Azienda Olandese (NV). Cerca 'Investors'.",
            "nv bekaert sa": "Azienda Belga (NV/SA). Cerca 'Investors'.",
            "glencore plc": "Azienda Svizzera/UK (PLC). Cerca 'Investors'.",
            "deutsche lufthansa": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "abb ltd": "Azienda Svizzera/Svedese (Ltd ma base Svizzera). Cerca 'Investor Relations'.",
            "capgemini": "Azienda Francese (SE). Cerca 'Finance' o 'Investors'.",
            "merck group": "Merck KGaA. Azienda Tedesca. Cerca 'Investoren' o 'Investors'.",
            "bpost": "Azienda Belga (SA/NV). Cerca 'Investors'.",
            "synlab": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "l air liquide": "Air Liquide SA. Azienda Francese. Cerca 'Investors'.",
            "umicore": "Azienda Belga (SA/NV). Cerca 'Investors'.",
            "kone": "Azienda Finlandese (Oyj). Cerca 'Investors'.",
            "nokia": "Azienda Finlandese (Oyj). Cerca 'Investors'.",
            "telefonica": "Azienda Spagnola (SA). Cerca 'Accionistas e Inversores'.",
            "eni s p a": "Azienda Italiana (SPA). Cerca 'Investitori' o 'Investors'.",
            "arcelormittal": "Azienda Lussemburghese (SA). Cerca 'Investors'.",
            "heidelbergcement": "Heidelberg Materials AG. Azienda Tedesca. Cerca 'Investor Relations'.",
            "medtronic plc": "Azienda globale (registrata Irlanda). Cerca 'Investor Relations'. Considera SEC filings. FY finisce Aprile.",
            "nestle s.a.": "Azienda Svizzera (SA). Cerca 'Investors'.",
            "novomatic group": "Azienda Austriaca (AG). Cerca 'Investor Relations'.",
            "rethmann": "Rethmann SE & Co. KG. Azienda Tedesca (privata?). Dati limitati.",
            "jbs s.a.": "Azienda Brasiliana (SA). Cerca 'Investidores' o 'Investors'.",
            "mercedes-benz group": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "compass group plc": "Azienda UK (PLC). Cerca 'Investors'. FY finisce Settembre.",
            "atos se": "Azienda Francese (SE). Cerca 'Finance' o 'Investors'.",
            "volkswagen": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "deutsche telekom": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "alstom": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "danone": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "deutsche post": "DHL Group. Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "schaeffler": "Azienda Tedesca (AG). Cerca 'Investor Relations'.",
            "bouygues": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "edp": "Energias de Portugal SA. Azienda Portoghese. Cerca 'Investidores'.",
            "novartis ag": "Azienda Svizzera (AG). Cerca 'Investors'.",
            "henkel kgaa": "Azienda Tedesca (KGaA). Cerca 'Investor Relations'.",
            "d ieteren group": "Azienda Belga (SA/NV). Cerca 'Investors'.",
            "heineken": "Azienda Olandese (NV). Cerca 'Investors'.",
            "inditex": "Azienda Spagnola (SA). Zara etc. Cerca 'Inversores'. FY finisce Gennaio.",
            "iberdrola": "Azienda Spagnola (SA). Cerca 'Accionistas e Inversores'.",
            "leonardo societa per azioni": "Azienda Italiana (SPA). Cerca 'Investitori'.",
            "bosch": "Robert Bosch GmbH. Azienda Tedesca (privata?). Dati limitati. Cerca 'Unternehmen', 'Reports'.",
            "essilorluxottica": "Azienda Francese/Italiana (SA). Cerca 'Investors'.",
            "sgs": "Azienda Svizzera (SA). Cerca 'Investor Relations'.",
            "compagnie generale des etablissements michelin": "Michelin. Azienda Francese (SCA). Cerca 'Finance' o 'Investors'.",
            "holcim ag": "Azienda Svizzera (AG). Cerca 'Investors'.",
            "schneider electric se": "Azienda Francese (SE). Cerca 'Finance' o 'Investors'.",
            "eurofins scientific": "Azienda Lussemburghese/Francese (SE). Cerca 'Investors'.",
            "repsol": "Azienda Spagnola (SA). Cerca 'Accionistas e Inversores'.",
            "anheuser-busch inbev": "AB InBev. Azienda Belga/Globale (SA/NV). Cerca 'Investors'.",
            "novo nordisk": "Azienda Danese (A/S). Cerca 'Investors'.",
            "solvay": "Azienda Belga (SA). Cerca 'Investors'.",
            "bertelsmann stiftung": "Fondazione Tedesca. Non è una società quotata standard. Dati potrebbero essere diversi.",
            "wienerberger group": "Azienda Austriaca (AG). Cerca 'Investors'.",
            "krka tovarna zdravil dd novo mesto": "KRKA d.d. Azienda Slovena. Cerca 'Investors'.",
            "prysmian s.p.a.": "Azienda Italiana (SPA). Cerca 'Investitori'.",
            "vinci": "Azienda Francese (SA). Cerca 'Finance' o 'Investors'.",
            "kuehne nagel": "Kuehne + Nagel International AG. Azienda Svizzera. Cerca 'Investor Relations'.",
            "strabag group": "Azienda Austriaca (SE). Cerca 'Investor Relations'.",
            "prosegur": "Prosegur Compañía de Seguridad SA. Azienda Spagnola. Cerca 'Inversores'.",
            "andritz group": "Azienda Austriaca (AG). Cerca 'Investors'.",
            "asseco": "Asseco Poland SA (o gruppo?). Azienda Polacca. Cerca 'Investor Relations' o 'Relacje inwestorskie'.",
            "electricite de france": "EDF. Azienda Francese (SA, Statale?). Cerca 'Finance' o 'Investors'.",
            "l oreal": "L'Oréal SA. Azienda Francese. Cerca 'Finance' o 'Investors'.",
            "stellantis": "Azienda Olandese/Globale (NV). Fiat Chrysler Peugeot etc. Cerca 'Investors'.",
            # Esempi Asia/Pacifico (LTD, CORPORATION, K.K.)
            "bridgestone corporation": "Azienda Giapponese. Cerca 'Investor Relations' sul sito globale .com. FY finisce Dicembre.",
            "sumitomo corporation": "Azienda Giapponese. Cerca 'Investor Relations' sul sito globale .com. FY finisce Marzo.",
            "dentsu group inc.": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Dicembre.",
            "fujitsu limited": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "sony group corporation": "Azienda Giapponese. Cerca 'Investor Relations' sul sito sony.com/en/SonyInfo/IR/. FY finisce Marzo.",
            "hbis group co. ltd.": "Hebei Iron and Steel. Azienda Cinese (Statale?). Dati potrebbero essere sul sito cinese o limitati.",
            "nippon steel corporation": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "mitsui & co ltd": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "h & m hennes & mauritz": "H&M. Azienda Svedese (AB). Cerca 'Investors'. FY finisce Novembre.",  # Messo qui per H&M
            "toyota motor corporation": "Azienda Giapponese. Cerca 'Investor Relations' sul sito global.toyota/en/ir/. FY finisce Marzo.",
            "itochu corporation": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "nippon telegraph and telephone": "NTT. Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "zhejiang geely holding group": "Geely. Azienda Cinese. Dati potrebbero essere limitati.",
            "sinochem": "Azienda Cinese (Statale?). Dati limitati.",
            "john swire & sons limited": "Swire Group. Holding basata a Hong Kong/UK. Dati potrebbero essere complessi o per sussidiarie.",
            "marubeni corporation": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "hitachi ltd": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "samsung electronics co. ltd.": "Azienda Sudcoreana. Cerca 'Investor Relations' sul sito globale samsung.com.",
            "mitsubishi corporation": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Marzo.",
            "canon incorporated": "Azienda Giapponese. Cerca 'Investor Relations'. FY finisce Dicembre.",
            # Esempi Nordici (AB, ASA, A/S, OYJ)
            "atlas copco aktiebolag": "Azienda Svedese (AB). Cerca 'Investors'.",
            "aktiebolaget skf": "SKF. Azienda Svedese (AB). Cerca 'Investors'.",
            "securitas ab": "Azienda Svedese (AB). Cerca 'Investors'.",
            "dsv a/s": "Azienda Danese (A/S). Cerca 'Investor'.",
            "konecranes": "Azienda Finlandese (Oyj). Cerca 'Investors'.",
            "sandvik aktiebolag": "Azienda Svedese (AB). Cerca 'Investors'.",
            "skanska ab": "Azienda Svedese (AB). Cerca 'Investors'.",
            "aktiebolaget volvo": "Volvo Group. Azienda Svedese (AB). Cerca 'Investors'.",
            "orkla asa": "Azienda Norvegese (ASA). Cerca 'Investor Relations'.",
            "aktiebolaget electrolux": "Electrolux. Azienda Svedese (AB). Cerca 'Investors'.",
            "assa abloy ab": "Azienda Svedese (AB). Cerca 'Investors'.",
            "telefonaktiebolaget lm ericsson": "Ericsson. Azienda Svedese (AB). Cerca 'Investors'.",
            "husqvarna ab": "Azienda Svedese (AB). Cerca 'Investors'.",
            "alfa laval ab": "Azienda Svedese (AB). Cerca 'Investors'.",
            "iss a/s": "Azienda Danese (A/S). Cerca 'Investor Relations'.",
            "vestas wind systems a/s": "Azienda Danese (A/S). Cerca 'Investors'.",
            "yara international asa": "Azienda Norvegese (ASA). Cerca 'Investor Relations'.",
            "norsk hydro asa": "Azienda Norvegese (ASA). Cerca 'Investors'.",
            "a.p. moller - maersk": "Maersk. Azienda Danese (A/S). Cerca 'Investor Relations'.",
            "carlsberg a/s": "Azienda Danese (A/S). Cerca 'Investors'.",
            # Esempi UK (PLC)
            "bp p.l.c.": "Azienda UK (PLC). Cerca 'Investors'.",
            "john wood group plc": "Azienda UK (PLC). Cerca 'Investors'.",
            "vodafone group plc": "Azienda UK (PLC). Cerca 'Investors'. FY finisce Marzo.",
            "british american tobacco plc": "BAT. Azienda UK (PLC). Cerca 'Investors'.",
            "iwg plc": "Regus. Azienda UK/Globale (PLC, sede Svizzera?). Cerca 'Investors'.",
            "3i group plc": "Azienda UK (PLC). Cerca 'Investors'. FY finisce Marzo.",
            "gsk plc": "GlaxoSmithKline. Azienda UK (PLC). Cerca 'Investors'.",
            "intertek group plc": "Azienda UK (PLC). Cerca 'Investors'.",
            "relx plc": "Azienda UK/Olandese (PLC/NV). Cerca 'Investors'.",
            "astrazeneca plc": "Azienda UK/Svedese (PLC). Cerca 'Investors'.",
            "unilever plc": "Azienda UK (PLC). Cerca 'Investors'.",  # Anche NV olandese storicamente
            # Altri / Privati / Difficili
            "ferrero": "Azienda Italiana/Lussemburghese (privata). Dati finanziari pubblici limitati.",
            "cargill": "Azienda USA (privata). Dati limitati.",
            "fletcher group": "Potrebbe riferirsi a Fletcher Building (Nuova Zelanda) o altri. Specificare se possibile.",
            "advance properties": "Nome generico, potrebbe essere immobiliare privata. Dati limitati.",
            "zf friedrichshafen": "Azienda Tedesca (Fondazione/AG?). Cerca 'Unternehmen', 'Presse'.",
            "edizione": "Holding Famiglia Benetton (Italia). Dati potrebbero essere per le controllate (es. Mundys/Atlantia).",
            "atlas uk bidco limited": "Veicolo di acquisizione UK. Probabilmente non ha report propri, cercare la parent company.",
            # Mantieni gli originali se non sovrascritti
            "apple inc.": "Azienda USA. Focus su SEC filings (10-K per Annual, 10-Q per Quarterly) e pagina IR ufficiale: investor.apple.com. Anno fiscale termina a fine Settembre.",
            # Siemens già coperto sopra
            # Toyota già coperto sopra
            # Unilever già coperto sopra
        }

        # Cerca una corrispondenza (case-insensitive)
        normalized_company_name = company_name.lower()
        for key, value in known_info.items():
            # Match se la chiave è contenuta nel nome azienda normalizzato
            # Diamo priorità a match più lunghi/completi se ci sono più chiavi possibili?
            # Per ora usiamo il primo match trovato.
            if key in normalized_company_name:
                logger.debug(f"Trovato hint specifico per '{company_name}' basato sulla chiave '{key}'")
                return value  # Ritorna l'hint trovato

        return None  # Nessuna info specifica trovata


class PromptTuner:
    """Modulo per l'ottimizzazione automatica dei prompt basata sui feedback"""

    def __init__(self, initial_prompt_template=None):
        """
        Inizializza il tuner con un prompt iniziale

        Args:
            initial_prompt_template (str): Template del prompt iniziale
        """
        self.current_prompt = (
            initial_prompt_template
            or """
        SEI UN ESPERTO RICERCATORE FINANZIARIO specializzato nell'individuare fonti ufficiali di dati finanziari per multinazionali.

        TASK: Trova la fonte più autorevole e specifica di dati finanziari per "{company_name}" (tipologia di fonte: {source_type}).

        ISTRUZIONI DETTAGLIATE:
        1. Identifica il sito web ufficiale dell'azienda
        2. Cerca la sezione "Investor Relations" o equivalente
        3. Individua il report finanziario più recente del tipo richiesto
        4. Fornisci l'URL diretto al documento (preferibilmente PDF) e l'anno fiscale

        FORMATO RISPOSTA:
        {{
            "url": "URL diretto al documento finanziario (non alla pagina che lo contiene)",
            "year": "Anno fiscale del report (YYYY)",
            "confidence": "ALTA/MEDIA/BASSA",
            "notes": "Breve spiegazione della tua scelta"
        }}

        IMPORTANTE:
        - Preferisci sempre link diretti a PDF o documenti specifici
        - Verifica che l'URL sia accessibile e non richieda login
        - Indica l'anno fiscale più recente disponibile
        """
        )

        self.tuning_history = []
        self.model = genai.GenerativeModel("gemini-1.5-pro-latest")

    def generate_prompt(self, company_name, source_type):
        """
        Genera un prompt personalizzato per l'azienda

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria

        Returns
        -------
            str: Prompt completo
        """
        return self.current_prompt.format(company_name=company_name, source_type=source_type)

    def improve_prompt(self, company_name, source_type, scraping_result, validation_result):
        """
        Migliora il prompt in base ai risultati della validazione

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            scraping_result (dict): Risultato dello scraping
            validation_result (dict): Risultato della validazione

        Returns
        -------
            str: Nuovo prompt ottimizzato
        """
        # Costruisci un prompt per Gemini per migliorare il prompt attuale
        improvement_prompt = f"""
        Sei un esperto di ottimizzazione di prompt per ricerca finanziaria.

        CONTESTO:
        - Azienda: {company_name}
        - Tipo di fonte richiesta: {source_type}
        - Prompt attuale utilizzato:
        ```
        {self.current_prompt}
        ```

        - Risultato dello scraping web: {json.dumps(scraping_result, indent=2)}
        - Feedback della validazione: {json.dumps(validation_result, indent=2)}

        TASK:
        Migliora il prompt per ottenere risultati più accurati. Il prompt deve essere ottimizzato per:
        1. Trovare l'URL diretto al documento finanziario più recente
        2. Identificare correttamente l'anno fiscale
        3. Aumentare la precisione e l'affidabilità dei risultati

        IMPORTANTE:
        - Mantieni la struttura JSON della risposta
        - Aggiungi istruzioni specifiche per superare i problemi riscontrati
        - Non cambiare completamente il prompt, ma miglioralo in modo incrementale

        RESTITUISCI SOLO IL NUOVO PROMPT MIGLIORATO, NIENT'ALTRO.
        """

        try:
            response = self.model.generate_content(improvement_prompt)
            new_prompt = response.text.strip()

            # Salva la storia del tuning per analisi
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

            # Aggiorna il prompt corrente
            self.current_prompt = new_prompt

            logger.info(f"Prompt migliorato per {company_name}")
            return new_prompt
        except Exception as e:
            logger.error(f"Errore durante il miglioramento del prompt: {e}")
            return self.current_prompt  # Mantieni il prompt attuale in caso di errore


class ResultValidator:
    """Modulo per la validazione dei risultati tramite Gemini API"""

    def __init__(self):
        """Inizializza il validatore dei risultati"""
        # Utilizziamo Gemini invece di Mistral
        self.model = "gemini-1.5-pro-latest"  # Modello Gemini da utilizzare

    def validate_result(self, company_name, source_type, scraping_result):
        """
        Valida i risultati dello scraping utilizzando Gemini

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

        validation_prompt = f"""
        Sei un VALIDATORE ESPERTO di fonti finanziarie per multinazionali.

        CONTESTO:
        - Azienda: {company_name}
        - Tipo di fonte richiesta: {source_type}

        RISULTATO DA VALIDARE:
        - URL: {url}
        - Anno fiscale: {year}
        - Descrizione fonte: {source_description}
        - Livello di confidenza dichiarato: {confidence}

        TASK:
        Valuta l'accuratezza e l'affidabilità di questo risultato. Considera:
        1. L'URL sembra essere una fonte ufficiale e diretta al documento richiesto?
        2. L'anno fiscale è plausibile e recente?
        3. La fonte è appropriata per il tipo richiesto?

        RESTITUISCI LA TUA VALUTAZIONE IN QUESTO FORMATO JSON:
        {{
            "is_valid": true/false,
            "validation_score": 0-100,
            "feedback": "Spiegazione dettagliata della tua valutazione",
            "improvement_suggestions": "Suggerimenti specifici per migliorare la ricerca"
        }}
        """

        try:
            # Utilizziamo l'API di Gemini invece di Mistral
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(validation_prompt)

            if response:
                validation_text = response.text
                validation_result = self._extract_json_from_text(validation_text)
                if not validation_result:
                    validation_result = {
                        "is_valid": False,
                        "validation_score": 0,
                        "feedback": "Impossibile analizzare la risposta di validazione",
                        "improvement_suggestions": "Riprova con un prompt più chiaro",
                    }
                logger.info(
                    f"Validazione completata per {company_name}: Score {validation_result.get('validation_score')}"
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
                "feedback": f"Errore durante la validazione: {e!s}",
                "improvement_suggestions": "Verifica la connessione e riprova",
            }

    def _extract_json_from_text(self, text):
        """Estrae un oggetto JSON da una risposta testuale"""
        try:
            json_pattern = r"({[\s\S]*})"
            match = re.search(json_pattern, text)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Impossibile estrarre JSON dalla risposta: {e}")
            return None


class FinancialSourcesFinder:
    """Classe principale che coordina il processo di ricerca delle fonti finanziarie"""

    def __init__(self, api_key=None, max_tuning_iterations=3, validation_threshold=80):
        """
        Inizializza il finder con le configurazioni necessarie

        Args:
            api_key (str): Chiave API per Gemini (opzionale se già configurata)
            max_tuning_iterations (int): Numero massimo di iterazioni di tuning
            validation_threshold (int): Soglia di validazione (0-100)
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
        Trova la fonte finanziaria per un'azienda con tuning automatico

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria

        Returns
        -------
            dict: Risultato finale con URL, anno e metadati
        """
        logger.info(f"Avvio ricerca per {company_name} (tipo: {source_type})")

        # Esegui lo scraping iniziale
        url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

        # Prepara il risultato dello scraping
        scraping_result = {"url": url, "year": year, "source_description": source_description, "confidence": confidence}

        # Valida il risultato
        validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # Ciclo di tuning automatico
        iteration = 0
        while (
            not validation_result.get("is_valid", False)
            or validation_result.get("validation_score", 0) < self.validation_threshold
        ) and iteration < self.max_tuning_iterations:
            iteration += 1
            logger.info(f"Iterazione di tuning {iteration} per {company_name}")

            # Migliora il prompt
            self.prompt_tuner.improve_prompt(company_name, source_type, scraping_result, validation_result)

            # Riprova lo scraping
            url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)

            # Aggiorna il risultato
            scraping_result = {
                "url": url,
                "year": year,
                "source_description": source_description,
                "confidence": confidence,
            }

            # Rivaluta
            validation_result = self.validator.validate_result(company_name, source_type, scraping_result)

        # Prepara il risultato finale
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

        logger.info(f"Ricerca completata per {company_name}: {'VALIDA' if final_result['is_valid'] else 'NON VALIDA'}")
        return final_result


def process_companies_batch(companies_batch, source_type, finder):
    """
    Elabora un batch di aziende in parallelo

    Args:
        companies_batch (list): Lista di nomi di aziende
        source_type (str): Tipo di fonte finanziaria
        finder (FinancialSourcesFinder): Istanza del finder

    Returns
    -------
        list: Risultati per il batch
    """
    results = []
    for company in companies_batch:
        try:
            result = finder.find_financial_source(company, source_type)
            results.append(result)
        except Exception as e:
            logger.error(f"Errore nell'elaborazione di {company}: {e}")
            results.append(
                {"company_name": company, "source_type": source_type, "url": None, "year": None, "error": str(e)}
            )
    return results


def main():
    """Funzione principale del programma"""
    import argparse

    parser = argparse.ArgumentParser(description="Trova fonti finanziarie per multinazionali")
    parser.add_argument(
        "--input", default="C://Users//raffl//Downloads//discovery.csv", help="File CSV di input con lista di aziende"
    )
    parser.add_argument("--output", default="financial_sources_results.csv", help="File CSV di output")
    parser.add_argument("--source-type", default="Annual Report", help="Tipo di fonte finanziaria da cercare")
    parser.add_argument("--api-key", help="Chiave API Gemini (opzionale se impostata come variabile d'ambiente)")
    parser.add_argument("--threads", type=int, default=4, help="Numero di thread per l'elaborazione parallela")
    parser.add_argument("--batch-size", type=int, default=10, help="Dimensione del batch per l'elaborazione")
    parser.add_argument("--validation-threshold", type=int, default=80, help="Soglia di validazione (0-100)")
    parser.add_argument("--max-tuning", type=int, default=3, help="Numero massimo di iterazioni di tuning")

    args = parser.parse_args()

    # Configura l'API key se fornita
    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("Chiave API Gemini non fornita. Imposta GOOGLE_API_KEY o usa --api-key")
        sys.exit(1)

    # Carica il CSV di input
    try:
        df = pd.read_csv(args.input, sep=";")
        if "NAME" not in df.columns:
            # Prova a usare la prima colonna come nome dell'azienda
            company_column = df.columns[0]
            df = df.rename(columns={company_column: "NAME"})
            logger.warning(f"Colonna 'NAME' non trovata, uso '{company_column}' invece")
    except Exception as e:
        logger.error(f"Errore nel caricamento del CSV: {e}")
        sys.exit(1)

    # Inizializza il finder
    finder = FinancialSourcesFinder(
        api_key=api_key, max_tuning_iterations=args.max_tuning, validation_threshold=args.validation_threshold
    )

    # Prepara i batch di aziende
    companies = df["NAME"].tolist()
    batches = [companies[i : i + args.batch_size] for i in range(0, len(companies), args.batch_size)]

    # Elabora i batch in parallelo
    all_results = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = []
        for batch in batches:
            future = executor.submit(process_companies_batch, batch, args.source_type, finder)
            futures.append(future)

        # Mostra una barra di progresso
        for future in tqdm(futures, desc="Elaborazione batch", unit="batch"):
            batch_results = future.result()
            all_results.extend(batch_results)

    # Converti i risultati in DataFrame
    results_df = pd.DataFrame(all_results)

    # Salva i risultati
    results_df.to_csv(args.output, index=False)
    logger.info(f"Risultati salvati in {args.output}")

    # Stampa statistiche
    valid_results = results_df[results_df["is_valid"] == True]
    logger.info(f"Totale aziende elaborate: {len(results_df)}")
    logger.info(f"Risultati validi: {len(valid_results)} ({len(valid_results)/len(results_df)*100:.1f}%)")

    # Salva anche un report JSON con dettagli aggiuntivi
    report_path = args.output.replace(".csv", "_report.json")
    with open(report_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "total_companies": len(results_df),
                "valid_results": len(valid_results),
                "validation_rate": len(valid_results) / len(results_df),
                "source_type": args.source_type,
                "results": all_results,
            },
            f,
            indent=2,
        )
    logger.info(f"Report dettagliato salvato in {report_path}")


if __name__ == "__main__":
    main()
