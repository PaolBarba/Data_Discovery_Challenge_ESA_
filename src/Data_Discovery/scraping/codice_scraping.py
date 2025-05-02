import pandas as pd
import requests
import os
import time
import json
import sys
import re
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
from concurrent.futures import ThreadPoolExecutor
import google.generativeai as genai
from tqdm import tqdm
import random
from retry import retry
import argparse

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s', # Aggiunto threadName per il debug
    handlers=[
        logging.FileHandler("financial_sources_finder.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configurare l'API di Google Gemini
# L'API Key verrà letta dagli argomenti o dalle variabili d'ambiente nel blocco main

class WebScraperModule:
    """Modulo dedicato al web scraping per la ricerca di dati finanziari"""

    def __init__(self, user_agent=None, timeout=30, max_retries=3):
        """
        Inizializza il modulo di scraping

        Args:
            user_agent (str): User agent da utilizzare per le richieste HTTP
            timeout (int): Timeout in secondi per le richieste
            max_retries (int): Numero massimo di tentativi per le richieste
        """
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries # Non direttamente usato qui ma può essere utile

        if user_agent is None:
            # Rotazione di user agent per evitare blocchi
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
            ]
            user_agent = random.choice(user_agents)

        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,it;q=0.8', # Aggiunta lingua italiana
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1' # Do Not Track
        })

    @retry(tries=3, delay=2, backoff=2, logger=logger)
    def get_page(self, url):
        """
        Ottiene il contenuto di una pagina web con gestione dei tentativi

        Args:
            url (str): URL della pagina da scaricare

        Returns:
            str: Contenuto HTML della pagina o None in caso di errore
        """
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True) # Allow redirects
            response.raise_for_status() # Lancia eccezione per status code 4xx o 5xx
            # Check content type to avoid non-html pages if possible
            content_type = response.headers.get('Content-Type', '').lower()
            if 'html' in content_type:
                 # Gestisci correttamente la decodifica
                response.encoding = response.apparent_encoding # Prova a determinare l'encoding
                return response.text
            else:
                logger.warning(f"Content-Type non HTML per {url}: {content_type}. Contenuto ignorato.")
                return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Errore durante il download della pagina {url}: {e}")
            raise  # La decorazione retry gestirà i nuovi tentativi

    def find_company_website(self, company_name):
        """
        Cerca il sito web ufficiale di un'azienda utilizzando una ricerca (es. DuckDuckGo)

        Args:
            company_name (str): Nome dell'azienda

        Returns:
            str: URL del sito aziendale o None
        """
        try:
            # Utilizziamo DuckDuckGo HTML per evitare blocchi/API keys
            # Potrebbe essere meno affidabile di Google/Bing API a pagamento
            search_term = f'"{company_name}" official website investor relations' # Query più specifica
            search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(search_term)}"
            logger.info(f"Ricerca sito web per '{company_name}' su: {search_url}")
            html = self.get_page(search_url)

            if not html:
                logger.warning(f"Nessun contenuto HTML ricevuto da DuckDuckGo per '{company_name}'")
                return None

            soup = BeautifulSoup(html, 'html.parser')
            # Trova i link nei risultati di ricerca
            results = soup.find_all('a', {'class': 'result__a'})

            potential_urls = []
            for result in results:
                url = result.get('href')
                if url:
                    # Decodifica URL se necessario (DuckDuckGo a volte usa redirect)
                    if 'duckduckgo.com/y.js' in url:
                        parsed_url = urlparse(url)
                        query_params = requests.utils.parse_qs(parsed_url.query)
                        url = query_params.get('uddg', [None])[0]

                    if url and self._is_potential_corporate_domain(url, company_name):
                         normalized_url = self._normalize_url(url)
                         if normalized_url:
                            potential_urls.append(normalized_url)

            if potential_urls:
                 # Dai priorità agli URL che contengono più parti del nome
                 potential_urls.sort(key=lambda u: sum(t in urlparse(u).netloc for t in self._tokenize_company_name(company_name.lower()) if len(t)>2), reverse=True)
                 best_url = potential_urls[0]
                 logger.info(f"Trovato potenziale sito web per '{company_name}': {best_url}")
                 return best_url

            logger.warning(f"Nessun URL aziendale plausibile trovato nei risultati di ricerca per '{company_name}'")
            return None
        except Exception as e:
            logger.error(f"Errore durante la ricerca del sito web di '{company_name}': {e}", exc_info=True)
            return None

    def _is_potential_corporate_domain(self, url, company_name):
        """Verifica meno stringente per identificare possibili domini aziendali"""
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            scheme = parsed_url.scheme

            if not domain or scheme not in ['http', 'https']:
                return False

            # Rimuovi 'www.'
            if domain.startswith('www.'):
                domain = domain[4:]

            # Ignora domini generici o noti non aziendali
            non_corporate_domains = [
                'google.', 'facebook.', 'youtube.', 'linkedin.', 'twitter.',
                'amazon.', 'bing.', 'yahoo.', 'instagram.', 'wikipedia.', 'bloomberg.',
                'reuters.', 'ft.com', 'wsj.com', 'forbes.com', 'sec.gov', # Aggiunto sec.gov per distinguerlo dai siti aziendali
                'gov.uk', 'europa.eu', 'duckduckgo.com', 'yahoo.com', # Aggiunti altri noti
                'pinterest.', 'reddit.', 'telegram.', 'whatsapp.', 'tiktok.', # Social/Messaging
                'github.com', 'gitlab.com', # Codice sorgente
                'maps.', 'microsoft.com' # Domini troppo generici a volte
            ]
            if any(nd in domain for nd in non_corporate_domains):
                 # Fai un'eccezione per Microsoft se il nome dell'azienda è Microsoft
                 if "microsoft" in company_name.lower() and "microsoft.com" in domain:
                     pass # Ok per Microsoft
                 else:
                    return False


            # Tokenizza nome azienda e dominio
            company_tokens = self._tokenize_company_name(company_name.lower())
            domain_parts = domain.split('.')

            # Controlla sovrapposizione tra i token significativi e il dominio (escludendo TLD)
            significant_tokens = [t for t in company_tokens if len(t) > 2 and t not in ['inc', 'ltd', 'the', 'and', 'corp', 'plc', 'ag', 'sa', 'nv', 'bv']]
            domain_name_part = domain_parts[0] # Considera solo la parte principale del dominio

            # Heuristica: almeno un token significativo deve essere nel dominio
            # O il nome del dominio deve essere molto simile a un token lungo
            if not significant_tokens: # Se il nome è corto (es. 3M)
                 return any(token in domain_name_part for token in company_tokens if len(token) > 1)

            return any(token in domain_name_part for token in significant_tokens) or \
                   any(len(token) > 4 and token.startswith(domain_name_part[:4]) for token in significant_tokens)


        except Exception as e:
            logger.warning(f"Errore in _is_potential_corporate_domain per URL '{url}': {e}")
            return False

    def _tokenize_company_name(self, name):
        """Divide il nome dell'azienda in token significativi"""
        # Rimuovi elementi comuni come Inc, Corp, Ltd, PLC, AG, SA, NV, BV, ecc. e punteggiatura
        cleaned = re.sub(r'[.,]', '', name.lower())
        cleaned = re.sub(r'\b(inc|corp|corporation|ltd|limited|llc|group|holding|holdings|plc|ag|sas|spa|gmbh|co|company|incorporated|the|and|of|de|el|la)\b', '', cleaned, flags=re.IGNORECASE)

        # Dividi in token alfanumerici
        tokens = re.findall(r'\b[a-z0-9]+\b', cleaned)
        return [t for t in tokens if len(t) > 1] # Ignora token troppo corti

    def _normalize_url(self, url):
        """Normalizza un URL garantendo che sia completo e valido"""
        try:
            url = url.strip()
            if not url:
                return None

            # Aggiungi schema se mancante (default https)
            if not url.startswith('http://') and not url.startswith('https://'):
                # Prova prima a vedere se la pagina risponde su https
                test_url_https = 'https://' + url.lstrip('/')
                try:
                    # Test veloce con HEAD request
                    response = self.session.head(test_url_https, timeout=5, allow_redirects=True)
                    if response.status_code < 400:
                         url = test_url_https
                    else: # Prova http
                         test_url_http = 'http://' + url.lstrip('/')
                         response = self.session.head(test_url_http, timeout=5, allow_redirects=True)
                         if response.status_code < 400:
                            url = test_url_http
                         else: # Mantieni https come default se entrambi falliscono il test rapido
                             url = test_url_https
                except requests.exceptions.RequestException:
                    # Se HEAD fallisce, usa https come default più sicuro
                    url = 'https://' + url.lstrip('/')


            parsed = urlparse(url)
            # Rimuovi parametri e frammenti, normalizza path
            path = parsed.path if parsed.path else '/'
            # Assicurati che termini con uno slash se è solo il dominio
            if not parsed.path or parsed.path == '/':
                 path = '/'

            # Ricostruisci URL pulito
            normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
            # Rimuovi eventuale slash finale se il path non è solo '/'
            if normalized.endswith('/') and len(normalized) > len(parsed.scheme + "://") + len(parsed.netloc) + 1:
                 normalized = normalized.rstrip('/')

            return normalized

        except Exception as e:
            logger.warning(f"Errore nella normalizzazione dell'URL '{url}': {e}")
            return None # Ritorna None se l'URL non è valido

    def find_investor_relations_page(self, company_url):
        """
        Cerca la pagina delle relazioni con gli investitori sul sito aziendale

        Args:
            company_url (str): URL del sito aziendale (normalizzato)

        Returns:
            str: URL della pagina IR o None
        """
        if not company_url:
            return None
        try:
            # Scarica la home page
            logger.info(f"Ricerca pagina IR su: {company_url}")
            html = self.get_page(company_url)
            if not html:
                return None

            soup = BeautifulSoup(html, 'html.parser')

            # Cerca link che contengono termini relativi a IR (multilingua base)
            ir_keywords_text = ['investor relations', 'investors', 'investor', 'shareholders', 'investisseurs', 'investoren', 'aktionäre', 'relazioni con gli investitori', 'azionisti', 'inversionistas']
            ir_keywords_href = ['investor', 'ir/', '/ir', 'shareholder', 'investisseur', 'investor-relations', 'investoren', 'aktionær', 'investorinformation', 'relazioni-investitori', 'investor_relations']
            financial_keywords = ['financials', 'finances', 'finanzberichte', 'finanzas', 'bilanci'] # Keywords meno specifiche

            candidate_links = {} # {url: score}

            for link in soup.find_all('a', href=True):
                text = link.get_text().lower().strip()
                href = link.get('href', '').lower()
                full_url = None

                # Controllo keywords nel testo o nell'href
                is_ir_link = any(keyword in text for keyword in ir_keywords_text) or \
                             any(keyword in href for keyword in ir_keywords_href)
                is_financial_link = any(keyword in text or keyword in href for keyword in financial_keywords)

                if is_ir_link or is_financial_link:
                    try:
                        # Costruisci URL assoluto e normalizzalo
                        temp_url = urljoin(company_url, link.get('href')) # Usa l'href originale non lowercased
                        full_url = self._normalize_url(temp_url)
                    except Exception:
                        continue # Ignora URL non validi

                    if full_url and urlparse(full_url).netloc == urlparse(company_url).netloc: # Assicurati sia sullo stesso dominio
                        score = 0
                        if is_ir_link: score += 5
                        if 'investor' in full_url: score += 2
                        if 'relations' in full_url: score += 1
                        if is_financial_link and not is_ir_link: score += 1 # Punteggio minore per link solo finanziari

                        # Penalizza link troppo generici o non specifici
                        if full_url.endswith(('.pdf', '.zip', '.xlsx', '.docx')): score -= 2 # Non è la pagina IR principale
                        if full_url == company_url: score = -1 # Ignora se è la homepage stessa

                        if score > 0:
                            candidate_links[full_url] = candidate_links.get(full_url, 0) + score

            if candidate_links:
                # Ordina per punteggio decrescente
                sorted_links = sorted(candidate_links.items(), key=lambda item: item[1], reverse=True)
                best_ir_url = sorted_links[0][0]
                logger.info(f"Trovata potenziale pagina IR per '{company_url}': {best_ir_url}")
                return best_ir_url

            # Fallback: Prova URL comuni per IR
            common_ir_paths = ['investor-relations/', 'investors/', 'ir/', 'investor/', 'shareholder-information/']
            for path in common_ir_paths:
                potential_ir_url = urljoin(company_url, path)
                potential_ir_url = self._normalize_url(potential_ir_url)
                if potential_ir_url:
                     try:
                         # Test veloce con HEAD
                         response = self.session.head(potential_ir_url, timeout=5, allow_redirects=True)
                         if response.status_code < 400:
                              logger.info(f"Trovata pagina IR con path comune: {potential_ir_url}")
                              return potential_ir_url
                     except requests.exceptions.RequestException:
                         continue # Ignora se non raggiungibile

            logger.warning(f"Impossibile trovare una pagina IR dedicata su {company_url}")
            return None # Non trovato
        except Exception as e:
            logger.error(f"Errore durante la ricerca della pagina IR su {company_url}: {e}", exc_info=True)
            return None

    def find_financial_reports(self, page_url, source_type='Annual Report'):
        """
        Cerca i report finanziari (link a documenti) nella pagina fornita (es. pagina IR)

        Args:
            page_url (str): URL della pagina dove cercare (es. pagina IR)
            source_type (str): Tipo di report da cercare (Annual, Quarterly, Consolidated, etc.)

        Returns:
            list: Lista di tuple (url_documento, anno) dei report trovati, ordinati per anno desc.
        """
        if not page_url:
            return []
        try:
            logger.info(f"Ricerca report '{source_type}' su: {page_url}")
            html = self.get_page(page_url)
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')

            # Keywords per identificare i link ai report (più specifiche)
            # Da adattare in base a `source_type`
            keywords = []
            file_extensions = ('.pdf', '.xlsx', '.xls', '.docx', '.doc', '.zip', '.html', '.htm', '.aspx') # Includi HTML/ASPX per report interattivi/pagine dedicate
            year_pattern = r'(FY|Fiscal Year|Financial Year|)\s*(?<!\d)(20[1-3]\d)(?!\d|[-\/]\d)' # Pattern Anno (2010-2039)
            year_range_pattern = r'(20[1-3]\d)\s*[-\/]\s*(20[1-3]\d)' # Pattern Anno Range

            # Adatta keywords e priorità in base a source_type
            st_lower = source_type.lower()
            if 'annual' in st_lower or '10-k' in st_lower or 'consolidated' in st_lower:
                keywords = ['annual report', 'report annuale', 'jahresbericht', 'rapport annuel', 'informe anual',
                            'consolidated financial statement', 'bilancio consolidato', 'konzernabschluss', 'états financiers consolidés',
                            '10-k', '20-f', # Moduli SEC
                            'financial statement', 'bilancio', 'financial report', 'annual results', 'year-end']
                if 'consolidated' in st_lower: keywords = keywords[5:9] + keywords # Priorità a consolidated
            elif 'quarterly' in st_lower or '10-q' in st_lower:
                keywords = ['quarterly report', 'report trimestrale', 'quartalsbericht', 'rapport trimestriel',
                            'interim report', 'interim results', 'quarterly results',
                            '10-q', 'q1', 'q2', 'q3', 'q4', '1st quarter', '2nd quarter', '3rd quarter', '4th quarter']
            else: # Tipo generico
                 keywords = ['financial report', 'financial statement', 'financial results', 'earnings release', 'press release financial']


            results = {} # {year: [(url, score)]} per gestire più URL per anno e scegliere il migliore

            for link in soup.find_all('a', href=True):
                text = link.get_text().strip()
                href = link.get('href', '')
                link_text_lower = text.lower()
                href_lower = href.lower()

                # Filtra link non rilevanti (javascript, mailto, immagini, etc.)
                if not href or href.startswith(('javascript:', 'mailto:', '#')) or href_lower.endswith(('.png', '.jpg', '.gif', '.svg')):
                    continue

                # Verifica se è un potenziale link a un report
                has_keyword = any(kw in link_text_lower or kw in href_lower for kw in keywords)
                is_document_link = href_lower.endswith(file_extensions) or 'download' in href_lower or 'attachment' in href_lower

                if has_keyword and is_document_link:
                    # Estrai l'anno
                    year = self._extract_year(text + ' ' + href) # Cerca anno nel testo E nell'href
                    if not year: continue # Ignora se non troviamo un anno valido

                    # Costruisci URL assoluto e normalizzalo
                    try:
                         full_url = urljoin(page_url, href)
                         # Non normalizzare qui per mantenere eventuali parametri necessari per il download
                    except Exception:
                        continue

                    # Calcola uno score per prioritizzare i link migliori
                    score = 0
                    if '.pdf' in href_lower: score += 5 # PDF è spesso il report principale
                    if any(kw in link_text_lower for kw in keywords): score += 3 # Keyword nel testo è più affidabile
                    if year in text: score += 2 # Anno nel testo
                    if 'annual report' in link_text_lower and 'annual' in st_lower: score += 2 # Match esatto tipo
                    if '10-k' in href_lower and 'annual' in st_lower: score += 3
                    if '10-q' in href_lower and 'quarterly' in st_lower: score += 3
                    if '.htm' in href_lower or '.aspx' in href_lower: score += 1 # Pagine web dedicate sono ok
                    if '.zip' in href_lower: score -= 1 # Meno preferibile
                    if 'interactive' in href_lower: score += 1 # Report interattivi

                    if year not in results: results[year] = []
                    results[year].append((full_url, score))


            if not results:
                 logger.warning(f"Nessun link a report '{source_type}' trovato su {page_url}")
                 return []

            # Seleziona il link migliore per ogni anno e ordina gli anni
            final_reports = []
            sorted_years = sorted(results.keys(), reverse=True) # Anni più recenti prima

            current_year = datetime.now().year
            relevant_years = [y for y in sorted_years if int(y) <= current_year and int(y) >= current_year - 5] # Considera ultimi 5 anni + anno corrente

            for year in relevant_years:
                 best_link_for_year = max(results[year], key=lambda item: item[1]) # Scegli link con score più alto
                 final_reports.append((best_link_for_year[0], year)) # (url, year)

            logger.info(f"Trovati {len(final_reports)} report '{source_type}' rilevanti su {page_url}")
            return final_reports # Già ordinati per anno decrescente

        except Exception as e:
            logger.error(f"Errore durante la ricerca di report finanziari su {page_url}: {e}", exc_info=True)
            return []

    def _extract_year(self, text):
        """Estrae l'anno più probabile (recente) da un testo (link text + href)."""
        # Pattern migliorato per anni fiscali e range
        year_pattern = r'(FY|Fiscal Year|Financial Year|)\s*(?<!\d)(20[1-3]\d)(?!\d|[-\/]\d{1,2}\b)' # Match '2023', 'FY2023', 'Fiscal Year 2023' ma non '2023/24' o '2023-25' nel mezzo
        year_range_pattern = r'(20[1-3]\d)\s*[-\/]\s*(?:20|)(\d{2})\b' # Match '2023-2024', '2023/2024', '2023-24', '2023/24'

        years_found = []

        # Cerca range (es. 2023/2024 -> prendi 2023)
        for match in re.finditer(year_range_pattern, text):
            try:
                start_year = int(match.group(1))
                end_year_short = int(match.group(2))
                # Ricostruisci end_year completo (es. 24 -> 2024)
                start_century = start_year // 100 * 100
                end_year = start_century + end_year_short
                if end_year == start_year + 1: # Valido solo se l'anno finale è quello successivo
                     years_found.append(str(start_year))
            except ValueError:
                continue

        # Cerca anni singoli (es. 2023, FY2023)
        for match in re.finditer(year_pattern, text):
            try:
                year = match.group(2) # Il gruppo che cattura '20xx'
                years_found.append(year)
            except (IndexError, ValueError):
                continue

        if not years_found:
            return None

        # Rimuovi duplicati e ordina in modo decrescente
        unique_years = sorted(list(set(years_found)), reverse=True)

        # Restituisci l'anno più recente trovato
        return unique_years[0]

    def find_sec_filings(self, company_name, form_type='10-K'):
        """
        Cerca i filing SEC (10-K, 10-Q) per le aziende tramite ricerca EDGAR.
        NOTA: Questo metodo è basilare e potrebbe fallire per nomi complessi.
              Una soluzione robusta userebbe CIK lookup e API EDGAR dedicate.

        Args:
            company_name (str): Nome dell'azienda
            form_type (str): Tipo di form SEC (10-K, 10-Q, etc.)

        Returns:
            list: Lista di tuple (url_documento_html, anno_filing) dei filing trovati.
                  URL punta alla pagina HTML del filing (non al documento specifico).
        """
        try:
            # EDGAR search URL
            # Limitiamo a 10 risultati, ordinati per data (i più recenti prima di default)
            search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={requests.utils.quote(company_name)}&type={form_type}&count=10&output=atom"
            logger.info(f"Ricerca filing SEC '{form_type}' per '{company_name}' su: {search_url}")

            # Usiamo la sessione per la richiesta
            response = self.session.get(search_url, timeout=self.timeout)
            response.raise_for_status()

            # Parse a feed Atom (XML)
            soup = BeautifulSoup(response.content, 'xml') # Usare parser 'xml'
            entries = soup.find_all('entry')

            results = []
            for entry in entries:
                filing_date_str = entry.find('filing-date')
                link_tag = entry.find('link', {'rel': 'alternate'}) # Link alla pagina HTML del filing

                if filing_date_str and link_tag and link_tag.get('href'):
                    filing_date_text = filing_date_str.get_text()
                    # Estrai l'anno dalla data di filing (YYYY-MM-DD)
                    year_match = re.match(r'(\d{4})-\d{2}-\d{2}', filing_date_text)
                    if year_match:
                        year = year_match.group(1)
                        filing_html_url = link_tag.get('href')
                        results.append((filing_html_url, year)) # (URL pagina filing, Anno filing)

            if not results:
                 logger.warning(f"Nessun filing SEC '{form_type}' trovato per '{company_name}' tramite ricerca base.")
                 return []

            # Ordina per anno (già implicito dall'API, ma per sicurezza)
            results.sort(key=lambda x: x[1], reverse=True)
            logger.info(f"Trovati {len(results)} filing SEC '{form_type}' per '{company_name}'")
            return results

        except requests.exceptions.RequestException as e:
             logger.error(f"Errore richiesta SEC EDGAR per '{company_name}': {e}")
             return []
        except Exception as e:
            logger.error(f"Errore durante la ricerca di filing SEC per '{company_name}': {e}", exc_info=True)
            return []

    def scrape_financial_sources(self, company_name, source_type):
        """
        Esegue il web scraping completo per trovare le fonti finanziarie di un'azienda.
        Cerca prima sul sito aziendale, poi fallback su SEC se appropriato.

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria (es. "Annual Report", "Quarterly Report")

        Returns:
            tuple: (url, year, source_description, confidence) o (None, None, None, "BASSA")
                   URL è il link diretto al documento/pagina specifica, se possibile.
                   Year è l'anno di riferimento del report.
        """
        logger.info(f"Avvio scraping per '{company_name}' (Tipo: {source_type})")
        best_url, best_year, source_description, confidence = None, None, None, "BASSA"

        # Step 1: Trova il sito web aziendale
        company_url = self.find_company_website(company_name)

        if company_url:
            logger.info(f"Sito web trovato per '{company_name}': {company_url}")
            # Step 2: Trova la pagina IR
            ir_page_url = self.find_investor_relations_page(company_url)

            # Step 3: Cerca i report sulla pagina IR (se trovata) o sulla homepage
            search_target_url = ir_page_url if ir_page_url else company_url
            if search_target_url:
                 reports = self.find_financial_reports(search_target_url, source_type)
                 if reports:
                     # Trovati report sul sito aziendale, prendi il più recente
                     best_url, best_year = reports[0] # Già ordinati per anno decrescente
                     source_description = f"{source_type} from Company Website ({'IR Page' if ir_page_url else 'Homepage'})"
                     # Valuta confidenza in base al tipo di link
                     if best_url.lower().endswith('.pdf'):
                         confidence = "ALTA"
                     elif best_url.lower().endswith(('.htm', '.html', '.aspx')):
                          confidence = "MEDIA" # Pagina web, potrebbe essere meno diretta
                     else:
                          confidence = "MEDIA" # Altro tipo di file
                     logger.info(f"Report trovato sul sito aziendale per '{company_name}': URL={best_url}, Anno={best_year}, Conf={confidence}")
                     # Non fermarti qui, controlla anche SEC se applicabile

        # Step 4: Fallback/Check con SEC Filings (per Annual/Quarterly e aziende potenzialmente USA)
        is_annual = 'annual' in source_type.lower() or 'consolidated' in source_type.lower()
        is_quarterly = 'quarterly' in source_type.lower()
        sec_form_type = None
        if is_annual: sec_form_type = '10-K'
        elif is_quarterly: sec_form_type = '10-Q'

        if sec_form_type and self._could_be_us_company(company_name):
            logger.info(f"Tentativo di ricerca SEC ({sec_form_type}) per '{company_name}' come fallback/verifica.")
            sec_results = self.find_sec_filings(company_name, sec_form_type)
            if sec_results:
                sec_url, sec_year = sec_results[0] # Prendi il più recente
                # Confronta con il risultato del sito web (se trovato)
                if best_url and best_year: # Aggiunto controllo che best_year non sia None
                     # Se l'anno SEC è più recente O uguale ma la fonte è considerata migliore (SEC è Alta confidenza)
                     if int(sec_year) > int(best_year) or (int(sec_year) == int(best_year) and confidence != "ALTA"):
                         logger.info(f"Filing SEC ({sec_form_type}, Anno {sec_year}) trovato più recente/affidabile del report sul sito. Aggiorno.")
                         best_url = sec_url # Nota: questo è l'URL della pagina HTML del filing
                         best_year = sec_year
                         source_description = f"SEC Filing ({sec_form_type})"
                         confidence = "ALTA"
                     else:
                          logger.info(f"Report dal sito web (Anno {best_year}) è preferito o uguale al filing SEC (Anno {sec_year}). Mantengo risultato sito web.")
                else:
                    # Nessun risultato dal sito web, usa SEC
                    logger.info(f"Nessun report trovato sul sito, uso filing SEC ({sec_form_type}, Anno {sec_year}).")
                    best_url = sec_url
                    best_year = sec_year
                    source_description = f"SEC Filing ({sec_form_type})"
                    confidence = "ALTA"


        # Log finale del risultato dello scraping
        if best_url and best_year:
            logger.info(f"Scraping completato per '{company_name}'. Risultato: URL={best_url}, Anno={best_year}, Fonte='{source_description}', Conf={confidence}")
        else:
            logger.warning(f"Scraping completato per '{company_name}'. Nessuna fonte trovata.")
            return None, None, None, "BASSA" # Assicurati di ritornare questo se non trovi nulla

        return best_url, best_year, source_description, confidence

    def _could_be_us_company(self, company_name):
        """Verifica euristica MOLTO semplice se un'azienda potrebbe essere statunitense."""
        # Questa euristica è debole e andrebbe migliorata (es. controllo TLD, sede legale se nota)
        us_indicators = [' Inc', ' Inc.', ' Corp', ' Corp.', ' LLC', ' LLP', ' Co.', ' Corporation'] # Spazio prima per evitare match parziali
        # Evita match se sono nomi europei comuni (AG, PLC, SA, NV)
        eu_indicators = [' AG', ' PLC', ' SE', ' N.V.', ' S.A.', ' S.p.A.', ' GmbH', ' SAS', ' OYJ', ' ASA', ' A/S', ' AB']
        name_upper = company_name.upper()
        if any(ind.upper() in name_upper for ind in eu_indicators):
            return False
        return any(ind.upper() in name_upper for ind in us_indicators)


class PromptGenerator:
    """Gestore della generazione e ottimizzazione dei prompt per Gemini"""

    def __init__(self):
        """Inizializza il generatore di prompt con modelli di base"""
        # Prompt base che verrà ottimizzato
        # Migliorato per chiarezza e specificità
        self.base_prompt_template = """
        SEI UN ESPERTO RICERCATORE FINANZIARIO con accesso a vaste basi di dati e capacità di navigazione web simulate. Specializzazione: individuare fonti UFFICIALI e SPECIFICHE di dati finanziari per multinazionali.

        AZIENDA TARGET: "{company_name}"
        TIPO DI FONTE RICHIESTA: "{source_type}"

        OBIETTIVO PRINCIPALE: Trovare l'URL **più diretto e specifico** possibile che punti al documento o alla pagina web contenente i dati finanziari più recenti del tipo richiesto per l'azienda target. Trovare anche l'**anno fiscale di riferimento** di tali dati.

        ISTRUZIONI DETTAGLIATE:

        1.  **RICERCA URL SPECIFICO:**
            * **Priorità Massima:** Link diretto a un documento scaricabile (PDF, XLSX, XBRL/iXBRL) del report richiesto (es. Annual Report PDF, 10-K Filing).
            * **Priorità Alta:** Link a una pagina web UFFICIALE dell'azienda che presenta specificamente i dati del report richiesto (es. pagina HTML interattiva del report annuale, sezione specifica dei risultati trimestrali).
            * **Priorità Media:** Link alla sezione principale "Investor Relations" (o equivalente) del sito UFFICIALE dell'azienda, SE contiene link chiari ai report specifici.
            * **Priorità Bassa:** Link a database finanziari affidabili (es. SEC EDGAR per 10-K/10-Q) SOLO se fonti ufficiali dirette non sono trovate o sono meno specifiche.
            * **DA EVITARE:** URL generici della homepage, pagine di notizie/blog, URL di aggregatori non ufficiali, URL rotti o che richiedono login complesso.

        2.  **IDENTIFICAZIONE ANNO DI RIFERIMENTO:**
            * Determina l'**anno fiscale (Financial Year - FY)** a cui si riferiscono i dati nel documento/pagina trovata. Questo NON è necessariamente l'anno di pubblicazione.
            * Se l'URL contiene più anni, seleziona l'anno fiscale **più recente** disponibile per il tipo di report richiesto.
            * Formato Anno: Restituisci solo l'anno numerico (es. "2023"). Se l'anno fiscale copre due anni solari (es. FY 2023-2024), restituisci l'anno finale ("2024").

        3.  **CONSIDERAZIONI SUL TIPO DI FONTE ("{source_type}"):**
            * Se "Annual Report" / "Consolidated": Cerca Report Annuali completi, Bilanci Consolidati, 10-K (USA), 20-F (non-USA su SEC), ESEF/iXBRL (EU).
            * Se "Quarterly Report": Cerca Report Trimestrali, 10-Q (USA), Risultati Intermedi.
            * Se altro: Interpreta al meglio (es. "Sustainability Report", "Press Release Earnings").

        4.  **AFFIDABILITÀ E AUTOREVOLEZZA:**
            * Dai priorità assoluta ai siti web UFFICIALI dell'azienda (.com, .co.uk, .de, ecc.).
            * Fonti regolatorie (SEC.gov, ESMA, etc.) sono molto affidabili.
            * Sii scettico verso domini non chiaramente collegati all'azienda.

        ISTRUZIONI PER LA RISPOSTA (JSON ESATTO):
        Restituisci **SOLO ed ESCLUSIVAMENTE** un oggetto JSON valido con la seguente struttura precisa. Non includere ```json, testo introduttivo, spiegazioni o commenti al di fuori del JSON.

        {{
            "url": "URL_SPECIFICO_TROVATO",
            "year": "ANNO_RIFERIMENTO_DATI_YYYY",
            "confidence": "ALTA | MEDIA | BASSA",
            "source_type_found": "DESCRIZIONE_BREVE_FONTE_TROVATA"
        }}

        * `url`: L'URL diretto e specifico identificato. Se non trovato, usa `null`.
        * `year`: L'anno fiscale di riferimento dei dati trovati (stringa "YYYY"). Se non trovato, usa `null`.
        * `confidence`: La tua confidenza nella correttezza e specificità del risultato ("ALTA" per link diretti a documenti ufficiali recenti, "MEDIA" per pagine IR o link meno specifici, "BASSA" se incerto o fonte non ottimale).
        * `source_type_found`: Una breve descrizione della fonte effettivamente trovata (es. "Annual Report PDF", "SEC 10-K Filing Page", "Investor Relations Section", "Quarterly Results HTML").

        {optimization_instructions}

        NOTA CRITICA: La precisione e la specificità dell'URL sono fondamentali. Se trovi più candidati validi, scegli quello che corrisponde meglio ai criteri di priorità e specificità. Se non riesci a trovare una fonte adeguata con confidenza almeno MEDIA, restituisci `null` per `url` e `year`.
        """

        # Istruzioni di ottimizzazione iniziali (vuote)
        self.optimization_instructions = ""

        # Dizionario per memorizzare prompt specifici per azienda (ottimizzati)
        self.company_specific_prompts = {}

        # Contatore di ottimizzazioni per azienda
        self.optimization_counter = {}

    def generate_prompt(self, company_name, source_type):
        """
        Genera un prompt personalizzato per una specifica azienda

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria

        Returns:
            str: Prompt ottimizzato o base
        """
        # Verifica se esiste un prompt specifico già ottimizzato per questa azienda
        if company_name in self.company_specific_prompts:
            logger.debug(f"Utilizzo prompt specifico ottimizzato per {company_name}")
            return self.company_specific_prompts[company_name]

        # Altrimenti, usa il template base
        logger.debug(f"Genero prompt base per {company_name}")
        # Includi eventuali istruzioni di ottimizzazione generali (se presenti)
        # e informazioni specifiche predefinite sull'azienda
        additional_info = self._get_company_additional_info(company_name)
        current_optimization_instructions = self.optimization_instructions # Parte da quelle globali
        if additional_info:
             # Aggiunge l'hint specifico nel punto designato del prompt
             additional_hint = f"\n\nHINT SPECIFICO PER QUESTA AZIENDA (Potrebbe essere utile):\n- {additional_info}\n"
             # Se optimization_instructions è già presente, aggiungi l'hint lì, altrimenti crealo.
             # Questo assume che {optimization_instructions} sia alla fine del prompt base.
             # current_optimization_instructions = additional_hint # Sostituisce le globali
             # Oppure Aggiunge:
             current_optimization_instructions += additional_hint


        prompt = self.base_prompt_template.format(
            company_name=company_name,
            source_type=source_type,
            optimization_instructions=current_optimization_instructions # Inserisce hint qui
        )

        return prompt

    @retry(tries=2, delay=3, logger=logger) # Tentativi limitati per l'ottimizzazione
    def optimize_prompt(self, company_name, feedback, current_prompt, scraping_results=None):
        """
        Ottimizza il prompt in base al feedback del validatore, chiedendo a Gemini.

        Args:
            company_name (str): Nome dell'azienda
            feedback (dict): Feedback dal sistema di validazione ({problems:[], suggestions:[]})
            current_prompt (str): Prompt attuale che ha fallito la validazione
            scraping_results (tuple): Risultati dello scraping (url, year, description, confidence) come riferimento

        Returns:
            str: Nuovo prompt ottimizzato, oppure il prompt originale se l'ottimizzazione fallisce.
        """
        # Incrementa il contatore di ottimizzazioni per questa azienda
        self.optimization_counter[company_name] = self.optimization_counter.get(company_name, 0) + 1
        optimization_attempt = self.optimization_counter[company_name]

        logger.info(f"Tentativo di ottimizzazione prompt {optimization_attempt} per {company_name}...")

        # Limite di ottimizzazioni per evitare loop
        # Aumentato a 3 tentativi totali (compreso il primo fallito)
        max_optimizations = 2
        if optimization_attempt > max_optimizations:
            logger.warning(f"Raggiunto limite di {max_optimizations} ottimizzazioni per {company_name}. Mantengo ultimo prompt o uso fallback.")
            # Fallback: usa i risultati dello scraping per creare un prompt molto specifico
            # return self._generate_scraping_based_prompt(company_name, scraping_results, current_prompt)
            # Oppure semplicemente restituisci il prompt corrente per evitare ulteriori chiamate
            return current_prompt


        # Genera un prompt per chiedere a Gemini di ottimizzare il prompt precedente
        optimization_request = self._create_optimization_request_prompt(company_name, feedback, current_prompt, scraping_results)

        try:
            # Richiedi a Gemini di ottimizzare il prompt
            # Usare un modello potenzialmente più potente per questo task? (Es. gemini-1.5-pro-latest se disponibile)
            # Per ora usiamo gemini-pro
            optimizer_model = genai.GenerativeModel('gemini-pro')
            response = optimizer_model.generate_content(
                optimization_request,
                generation_config={
                    "temperature": 0.4, # Più creativo per la riformulazione
                    "top_p": 0.95,
                    "max_output_tokens": 2048, # Abbastanza spazio per il prompt riscritto
                }
                # Considera safety_settings se necessario
            )

            optimized_prompt = response.text.strip()

            # Verifica minimale che la risposta sia un prompt plausibile
            if len(optimized_prompt) > 200 and "{company_name}" in optimized_prompt and '"url":' in optimized_prompt:
                 # Memorizza il prompt ottimizzato specifico per questa azienda
                 self.company_specific_prompts[company_name] = optimized_prompt
                 logger.info(f"Prompt ottimizzato con successo per {company_name} (Tentativo {optimization_attempt})")
                 return optimized_prompt
            else:
                 logger.warning(f"Ottimizzazione prompt per {company_name} ha prodotto un risultato non valido o troppo corto. Mantengo prompt precedente. Risposta: {optimized_prompt[:200]}...")
                 # Non memorizzare il prompt fallito
                 return current_prompt # Ritorna il prompt che ha fallito

        except Exception as e:
            logger.error(f"Errore API durante l'ottimizzazione del prompt per {company_name}: {e}")
            # In caso di errore API, ritorna il prompt precedente
            return current_prompt


    def _create_optimization_request_prompt(self, company_name, feedback, current_prompt, scraping_results):
        """Crea la richiesta per l'ottimizzazione del prompt a Gemini"""

        scraping_info = "Nessun dato da web scraping preliminare disponibile."
        if scraping_results and scraping_results[0]:
            url, year, desc, conf = scraping_results
            scraping_info = f"""RISULTATI DA WEB SCRAPING PRELIMINARE (potrebbero essere utili):
            - URL Scraper: {url}
            - Anno Scraper: {year}
            - Descrizione Scraper: {desc}
            - Confidenza Scraper: {conf}
            """

        problem_str = "\n- ".join(feedback.get('problems', ['Nessun problema specifico indicato']))
        suggestion_str = "\n- ".join(feedback.get('suggestions', ['Nessun suggerimento specifico']))

        return f"""
        SEI UN ESPERTO DI PROMPT ENGINEERING. Il tuo compito è **riscrivere e migliorare** un prompt esistente per un modello AI di ricerca finanziaria, basandoti sul feedback ricevuto dopo un tentativo fallito.

        CONTESTO:
        Il prompt originale è stato usato per cercare una specifica fonte finanziaria per l'azienda "{company_name}".
        La risposta generata usando quel prompt è stata valutata come **NON SODDISFACENTE**.

        FEEDBACK SULLA RISPOSTA PRECEDENTE (Problemi da risolvere):
        - {problem_str}

        SUGGERIMENTI PER IL MIGLIORAMENTO (dal validatore):
        - {suggestion_str}

        {scraping_info}

        PROMPT ORIGINALE (da migliorare):
        ```prompt
        {current_prompt}
        ```

        ISTRUZIONI PER LA RISCRITTURA DEL PROMPT:
        1.  **Analizza attentamente** il feedback (problemi e suggerimenti) e i risultati dello scraping (se presenti).
        2.  **Modifica il "PROMPT ORIGINALE"** per affrontare specificamente i problemi sollevati. Rendi le istruzioni più chiare, specifiche o restrittive dove necessario.
        3.  **Incorpora suggerimenti** utili dal feedback o dai dati di scraping. Ad esempio, se il problema era un URL troppo generico, enfatizza la ricerca di PDF o link diretti. Se l'anno era sbagliato, chiarisci come determinarlo. Se lo scraping ha trovato un URL promettente, potresti suggerire di verificarlo.
        4.  **Mantieni l'obiettivo principale** (trovare URL specifico e anno) e la **struttura di output JSON richiesta** nel prompt originale.
        5.  **NON cambiare il ruolo** ("SEI UN ESPERTO RICERCATORE FINANZIARIO...") o le variabili `{company_name}` e `{source_type}`.
        6.  **Riscrivi l'intero prompt** in modo chiaro e conciso, applicando le modifiche necessarie.
        7.  **Restituisci SOLO ed ESCLUSIVAMENTE il testo completo del NUOVO prompt ottimizzato.** Non aggiungere spiegazioni, commenti, o ```prompt.

        NUOVO PROMPT OTTIMIZZATO:
        """ # Gemini dovrà continuare da qui generando il nuovo prompt completo


    def _generate_scraping_based_prompt(self, company_name, scraping_results, previous_prompt):
        """Fallback: Genera un prompt che suggerisce fortemente i risultati dello scraping."""
        logger.warning(f"Utilizzo fallback: generazione prompt basato sui risultati dello scraping per {company_name}")

        if scraping_results and scraping_results[0] and scraping_results[1]:
            url, year, desc, conf = scraping_results

            # Estrai source_type dal prompt precedente (soluzione fragile)
            match = re.search(r'TIPO DI FONTE RICHIESTA:\s*"([^"]+)"', previous_prompt)
            source_type = match.group(1) if match else "Tipo Sconosciuto"

            scraping_suggestion = f"""
            ISTRUZIONI AGGIUNTIVE PRIORITARIE (Basate su scraping preliminare):
            - È stato identificato un potenziale URL: {url}
            - Anno associato (stimato): {year}
            - Descrizione stimata: {desc} (Confidenza: {conf})
            - **VERIFICA QUESTO URL e ANNO**. Se sono corretti, specifici e pertinenti per "{source_type}", usali. Altrimenti, cerca una fonte migliore seguendo le istruzioni generali ma dando priorità a fonti simili a quella trovata dallo scraping.
            """
            # Inserisci il suggerimento nel template base
            # Rimuovi eventuali hint precedenti prima di aggiungere il nuovo
            cleaned_base_prompt = re.sub(r'HINT SPECIFICO PER QUESTA AZIENDA.*?\n\n', '', self.base_prompt_template, flags=re.DOTALL)

            new_prompt = cleaned_base_prompt.format(
                company_name=company_name,
                source_type=source_type,
                optimization_instructions=scraping_suggestion
            )
            self.company_specific_prompts[company_name] = new_prompt # Memorizza questo prompt specifico
            return new_prompt
        else:
            # Se lo scraping non ha dato risultati utili, ritorna il prompt precedente senza modifiche
            logger.warning(f"Scraping preliminare non ha fornito dati utili per {company_name}. Nessuna modifica al prompt precedente.")
            return previous_prompt


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
            "crh plc": "Azienda Irlandese (PLC). Cerca 'Investors' sul sito .com. Controlla per ESEF format.", # Anche se PLC, base Irlanda -> EU
            "deutsche bahn": "Azienda Tedesca (AG, Statale?). Cerca 'Investor Relations' o 'Finanzberichte'.",
            "safran": "Azienda Francese (SA). Cerca 'Finance' o 'Investors' sul sito .com. Controlla per ESEF format.",
            "basf": "Azienda Tedesca (SE). Cerca 'Investor Relations' sul sito basf.com. Controlla per ESEF format.",
            "wpp plc": "Azienda UK (PLC). Cerca 'Investors' sul sito .com.", # Spostato qui perchè PLC è tipico UK
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
             "h & m hennes & mauritz": "H&M. Azienda Svedese (AB). Cerca 'Investors'. FY finisce Novembre.", # Messo qui per H&M
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
            "unilever plc": "Azienda UK (PLC). Cerca 'Investors'.", # Anche NV olandese storicamente

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
                return value # Ritorna l'hint trovato

        return None # Nessuna info specifica trovata

class Validator:
    """Modulo per validare i risultati ottenuti (URL e anno) usando Gemini come giudice"""

    def __init__(self, api_key):
        """
        Inizializza il validatore con la sua API key e modello Gemini dedicato

        Args:
            api_key (str): API key di Google Gemini
        """
        self.api_key = api_key
        # Potrebbe avere senso usare un modello più potente o configurato diversamente per la validazione
        self.model = genai.GenerativeModel('gemini-pro')
        self.web_scraper = WebScraperModule(timeout=15) # Scraper interno per verificare URL

    @retry(tries=3, delay=5, backoff=2, logger=logger) # Riprova in caso di errori API
    def validate_result(self, company_name, source_type_requested, url_found, year_found, scraping_results=None):
        """
        Valida l'URL e l'anno trovati dal ricercatore Gemini, usando un altro prompt Gemini (giudice).

        Args:
            company_name (str): Nome dell'azienda
            source_type_requested (str): Tipo di fonte finanziaria richiesta originariamente
            url_found (str): URL trovato dal ricercatore Gemini
            year_found (str): Anno trovato dal ricercatore Gemini (formato YYYY)
            scraping_results (tuple): Risultati dallo scraper (url, year, desc, conf) per confronto

        Returns:
            dict: Dizionario con { "validated": True/False, "feedback": {problems:[], suggestions:[]} }
                  Restituisce sempre un dizionario, anche in caso di errore interno.
        """
        logger.info(f"Avvio validazione per {company_name}: URL='{url_found}', Anno='{year_found}'")

        # Controlli preliminari sull'input
        if not url_found or not year_found:
            logger.warning(f"Validazione fallita (Input mancante) per {company_name}: URL o Anno non forniti.")
            return {"validated": False, "feedback": {"problems": ["URL o anno mancanti nella risposta del ricercatore."], "suggestions": ["Il ricercatore deve fornire sia URL che anno."]}}
        try:
             # Verifica base formato anno
             int(year_found)
             if len(year_found) != 4: raise ValueError("Formato anno non YYYY")
        except (ValueError, TypeError):
             logger.warning(f"Validazione fallita (Anno non valido) per {company_name}: Anno='{year_found}'")
             return {"validated": False, "feedback": {"problems": [f"Anno '{year_found}' non è in formato numerico YYYY."], "suggestions": ["Il ricercatore deve fornire l'anno in formato YYYY."]}}

        # Prova a verificare rapidamente se l'URL è accessibile
        url_accessible = self._check_url_accessibility(url_found)
        if not url_accessible:
             logger.warning(f"Validazione fallita (URL non accessibile) per {company_name}: URL='{url_found}'")
             return {"validated": False, "feedback": {"problems": [f"L'URL fornito '{url_found}' non è accessibile o restituisce un errore."], "suggestions": ["Verificare la correttezza dell'URL.", "Cercare un URL alternativo funzionante."]}}


        # Crea il prompt per il giudice Gemini
        validation_prompt = self._create_validation_prompt(company_name, source_type_requested, url_found, year_found, scraping_results)

        try:
            response = self.model.generate_content(
                validation_prompt,
                generation_config={
                    "temperature": 0.1, # Molto fattuale per giudicare
                    "max_output_tokens": 1024, # Spazio per feedback dettagliato
                }
                 # Considerare safety_settings se i prompt generano contenuti problematici
                 # safety_settings=...
            )

            # Estrai e pulisci il JSON dalla risposta del giudice
            validation_json = self._parse_validation_response(response.text, company_name)

            if validation_json:
                logger.info(f"Validazione per {company_name} completata. Validated: {validation_json.get('validated')}")
                # Assicurati che il feedback sia sempre presente nel formato atteso
                if "feedback" not in validation_json or not isinstance(validation_json["feedback"], dict):
                     validation_json["feedback"] = {"problems": ["Feedback mancante o malformato dal validatore."], "suggestions": []}
                return validation_json
            else:
                # Errore nel parsing della risposta del giudice
                 logger.error(f"Validazione fallita (Errore Interno Validatore) per {company_name}: Impossibile parsare la risposta del giudice.")
                 return {"validated": False, "feedback": {"problems": ["Errore interno del sistema di validazione (risposta non parsabile)."], "suggestions": ["Riprovare."] }}

        except Exception as e:
            logger.error(f"Errore API durante la chiamata di validazione per {company_name}: {e}", exc_info=True)
            # Rilancia l'eccezione per far scattare il retry della funzione chiamante
            raise


    def _check_url_accessibility(self, url):
        """Verifica rapida se l'URL è accessibile con una HEAD request."""
        try:
            response = self.web_scraper.session.head(url, timeout=10, allow_redirects=True)
            # Considera status < 400 come successo (include 2xx, 3xx redirects)
            if response.status_code < 400:
                logger.debug(f"Check accessibilità URL '{url}' OK (Status: {response.status_code})")
                return True
            else:
                logger.warning(f"Check accessibilità URL '{url}' fallito (Status: {response.status_code})")
                return False
        except requests.exceptions.Timeout:
            logger.warning(f"Check accessibilità URL '{url}' fallito (Timeout)")
            return False
        except requests.exceptions.RequestException as e:
            # Gestisce errori di connessione, SSL, redirect troppo lunghi etc.
            logger.warning(f"Check accessibilità URL '{url}' fallito (Errore Richiesta: {e})")
            return False
        except Exception as e:
             logger.error(f"Errore inatteso durante check accessibilità URL '{url}': {e}")
             return False # Considera non accessibile in caso di errore imprevisto


    def _parse_validation_response(self, response_text, company_name):
        """Estrae e pulisce il JSON dalla risposta del validatore Gemini."""
        try:
            # Trova il blocco JSON, anche se preceduto/seguito da testo
            json_match = re.search(r'\{\s*"validated":.*?\s*\}', response_text, re.DOTALL | re.IGNORECASE)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                # Validazione base della struttura
                if isinstance(data, dict) and "validated" in data and "feedback" in data and isinstance(data["feedback"], dict):
                    # Assicura che problems e suggestions siano liste
                    data["feedback"]["problems"] = data["feedback"].get("problems", [])
                    if not isinstance(data["feedback"]["problems"], list): data["feedback"]["problems"] = [str(data["feedback"]["problems"])]

                    data["feedback"]["suggestions"] = data["feedback"].get("suggestions", [])
                    if not isinstance(data["feedback"]["suggestions"], list): data["feedback"]["suggestions"] = [str(data["feedback"]["suggestions"])]

                    # Verifica anche la presenza della sotto-chiave assessment (opzionale ma utile)
                    if "assessment" not in data["feedback"]:
                         data["feedback"]["assessment"] = {} # Aggiungi vuoto se manca

                    return data
                else:
                    logger.warning(f"JSON di validazione incompleto o malformato ricevuto per {company_name}: {data}")
                    return None
            else:
                logger.warning(f"Nessun JSON valido trovato nella risposta di validazione per {company_name}. Risposta: {response_text[:200]}...")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Errore parsing JSON di validazione per {company_name}: {e}. Risposta: {response_text[:500]}")
            return None
        except Exception as e:
            logger.error(f"Errore generico durante il parsing della risposta di validazione per {company_name}: {e}")
            return None


    def _create_validation_prompt(self, company_name, source_type_requested, url_found, year_found, scraping_results):
        """Crea il prompt per il modello Gemini validatore (giudice)"""

        scraping_info = "Nessun dato da web scraping preliminare disponibile per confronto."
        if scraping_results and scraping_results[0]:
            s_url, s_year, s_desc, s_conf = scraping_results
            scraping_info = f"""DATI DA WEB SCRAPING PRELIMINARE (per riferimento):
            - URL Scraper: {s_url}
            - Anno Scraper: {s_year}
            - Descrizione Scraper: {s_desc}
            - Confidenza Scraper: {s_conf}
            """

        return f"""
        SEI UN GIUDICE FINANZIARIO ESPERTO E METICOLOSO. Il tuo unico compito è valutare l'accuratezza, la pertinenza e la specificità di un URL e di un Anno forniti come presunta fonte finanziaria per una data azienda.

        CONTESTO DELLA RICHIESTA ORIGINALE:
        - Azienda Target: "{company_name}"
        - Tipo di Fonte Richiesta: "{source_type_requested}"

        RISULTATO DA VALUTARE (prodotto da un altro AI):
        - URL Proposto: {url_found}
        - Anno di Riferimento Proposto: {year_found}

        {scraping_info}

        CRITERI DI VALUTAZIONE (Valuta OGNI criterio attentamente):

        1.  **URL - Accessibilità e Appartenenza:**
            * L'URL è valido e accessibile (senza errori 4xx/5xx)? (Già pre-verificato come accessibile, ma considera il contenuto).
            * L'URL appartiene chiaramente al dominio web ufficiale di "{company_name}" o a un'autorità regolatoria riconosciuta (es. SEC.gov)?

        2.  **URL - Pertinenza al Contenuto:**
            * Il contenuto della pagina/documento puntato dall'URL è effettivamente relativo a informazioni finanziarie di "{company_name}"?
            * Il contenuto corrisponde al TIPO di fonte richiesta ("{source_type_requested}")? (es. è davvero un Annual Report se richiesto Annual Report?)

        3.  **URL - Specificità:**
            * Quanto è SPECIFICO l'URL rispetto alla richiesta?
                * Ottimo: Link diretto a un file (PDF, XLSX, XBRL) del report specifico.
                * Buono: Link a una pagina HTML dedicata a quel report specifico.
                * Sufficiente: Link a una sezione IR che elenca chiaramente quel report con link diretto vicino.
                * Insufficiente: Link generico alla homepage IR, sezione news, homepage azienda.

        4.  **ANNO - Correttezza e Recenza:**
            * L'anno "{year_found}" è plausibile come anno fiscale per "{company_name}"?
            * L'anno "{year_found}" corrisponde **effettivamente** all'anno fiscale dei dati presentati nell'URL? (Verifica date nel documento/pagina se possibile).
            * È l'anno fiscale **più recente** disponibile per quel tipo di report in quella fonte URL?

        ISTRUZIONI PER LA RISPOSTA (JSON OBBLIGATORIO):
        Rispondi **ESCLUSIVAMENTE** con un oggetto JSON valido. Non aggiungere testo esterno al JSON. La struttura DEVE essere la seguente:

        {{
            "validated": true | false,
            "feedback": {{
                "assessment": {{
                     "url_ownership": "Valutazione (es. 'Ufficiale Azienda', 'Regolatorio Riconosciuto', 'Terze Parti', 'Non Chiaro', 'Non Corretto')",
                     "content_relevance": "Valutazione (es. 'Altamente Rilevante', 'Parzialmente Rilevante', 'Non Rilevante', 'Contenuto Errato')",
                     "url_specificity": "Valutazione (es. 'File Diretto', 'Pagina Dedicata', 'Sezione IR', 'Generico', 'Non Specifico')",
                     "year_accuracy": "Valutazione (es. 'Corretto e Recente', 'Corretto ma Non Recente', 'Anno Errato', 'Non Verificabile')",
                     "overall_match": "Valutazione (es. 'Perfetto', 'Buono', 'Sufficiente', 'Scarso', 'Inadeguato')"
                 }},
                "problems": [
                    "Elenco chiaro e conciso dei problemi SPECIFICI che impediscono la validazione (se validated=false). Sii preciso."
                    // Esempio: "L'URL punta alla sezione IR generica, non al report annuale specifico richiesto.",
                    // Esempio: "L'anno 2022 è corretto ma il report 2023 è disponibile nello stesso URL.",
                    // Esempio: "Il contenuto dell'URL non corrisponde a un Quarterly Report.",
                    // Esempio: "L'URL appartiene a un sito terzo non ufficiale."
                ],
                "suggestions": [
                     "Suggerimenti COSTRUTTIVI per il ricercatore AI su come migliorare la prossima ricerca (se ci sono problemi)."
                     // Esempio: "Cercare link diretti a file PDF con 'Annual Report' e l'anno nel nome/testo.",
                     // Esempio: "Verificare la presenza di un report più recente nella pagina fornita.",
                     // Esempio: "Focalizzare la ricerca sul sito ufficiale investor.[dominioazienda].com.",
                     // Esempio: "Ignorare URL da siti di aggregazione notizie."
                ]
            }}
        }}

        NOTA: Imposta `"validated": true` **SOLO SE** tutti i criteri principali (Pertinenza, Specificità URL, Correttezza/Recenza Anno, Appartenenza URL) sono valutati positivamente (da Sufficiente in su, con almeno Buono per specificità e anno). Altrimenti, imposta `"validated": false` e dettaglia i problemi e suggerimenti nel feedback. Sii rigoroso.
        """


class FinancialSourceFinder:
    """Orchestra il processo di ricerca, scraping, validazione e ottimizzazione"""

    def __init__(self, csv_path, api_key, output_csv="financial_sources_output.csv", max_workers=5, max_iterations=3): # Ridotto max_iterations default
        """
        Inizializza il finder

        Args:
            csv_path (str): Percorso del file CSV di input
            api_key (str): API key di Google Gemini
            output_csv (str): Nome del file CSV di output
            max_workers (int): Numero massimo di thread per l'elaborazione parallela
            max_iterations (int): Numero massimo di cicli (Ricerca->Valida->Ottimizza) per azienda
        """
        self.csv_path = csv_path
        self.output_csv = output_csv
        self.max_workers = max_workers
        self.max_iterations = max_iterations # Numero totale di tentativi di ricerca+validazione

        # Verifica API Key
        if not api_key:
            logger.critical("API Key di Google Gemini non fornita. Impostala come variabile d'ambiente GOOGLE_API_KEY o usa l'argomento --api_key.")
            sys.exit(1)
        # Configura l'API globalmente (necessario per i modelli genai)
        try:
            genai.configure(api_key=api_key)
            # Test rapido connessione/autenticazione listando i modelli disponibili
            models = [m.name for m in genai.list_models()]
            if not any('generateContent' in m.supported_generation_methods for m in genai.list_models()):
                 logger.critical("Nessun modello compatibile con generateContent trovato con questa API Key.")
                 sys.exit(1)
            logger.info(f"API Key Google Gemini configurata correttamente. Modelli disponibili (estratto): {[m for m in models if 'gemini' in m][:5]}")
        except Exception as e:
             logger.critical(f"Errore durante la configurazione o verifica dell'API Key Google Gemini: {e}")
             sys.exit(1)


        # Inizializzazione moduli con dipendenze
        self.scraper = WebScraperModule()
        self.prompt_generator = PromptGenerator()
        self.validator = Validator(api_key)
        # Modello principale per la ricerca (potrebbe essere diverso da validatore/ottimizzatore)
        try:
            self.search_model = genai.GenerativeModel('gemini-pro') # Usa gemini-pro per la ricerca
        except Exception as e:
             logger.critical(f"Impossibile inizializzare il modello Gemini 'gemini-pro': {e}")
             sys.exit(1)

        self.results = [] # Lista per memorizzare i risultati finali per ogni azienda

    def load_companies(self):
        """Carica la lista di aziende dal file CSV"""
        try:
            df = pd.read_csv(self.csv_path)
            # Assumiamo colonne 'CompanyName' e 'SourceType' (case insensitive)
            df.columns = [col.lower() for col in df.columns]
            required_cols = ['companyname', 'sourcetype']
            if not all(col in df.columns for col in required_cols):
                logger.critical(f"Il file CSV deve contenere le colonne 'CompanyName' e 'SourceType' (ignora maiuscole/minuscole). Colonne trovate: {list(df.columns)}")
                sys.exit(1)

            # Rinomina colonne per coerenza interna
            df = df.rename(columns={'companyname': 'CompanyName', 'sourcetype': 'SourceType'})

            # Pulisci dati: rimuovi spazi extra, converti in stringa
            df['CompanyName'] = df['CompanyName'].astype(str).str.strip()
            df['SourceType'] = df['SourceType'].astype(str).str.strip()

            # Rimuovi righe con CompanyName mancante
            df = df.dropna(subset=['CompanyName'])
            df = df[df['CompanyName'] != '']

            # Se SourceType è mancante, usa un default o logga un warning
            default_source_type = "Annual Report"
            missing_source_type = df['SourceType'].isnull() | (df['SourceType'] == '')
            if missing_source_type.any():
                 logger.warning(f"{missing_source_type.sum()} righe con SourceType mancante. Verrà usato il default: '{default_source_type}'")
                 df.loc[missing_source_type, 'SourceType'] = default_source_type

            companies = df[['CompanyName', 'SourceType']].to_dict('records')
            if not companies:
                 logger.critical(f"Nessuna azienda valida trovata nel file CSV: {self.csv_path}")
                 sys.exit(1)

            logger.info(f"Caricate {len(companies)} aziende valide dal file {self.csv_path}")
            return companies

        except FileNotFoundError:
            logger.critical(f"File CSV non trovato: {self.csv_path}")
            sys.exit(1)
        except pd.errors.EmptyDataError:
             logger.critical(f"Il file CSV è vuoto: {self.csv_path}")
             sys.exit(1)
        except Exception as e:
            logger.critical(f"Errore imprevisto durante la lettura o elaborazione del file CSV: {e}", exc_info=True)
            sys.exit(1)


    def _parse_search_response(self, response_text, company_name):
        """Estrae e pulisce il JSON dalla risposta della ricerca Gemini."""
        logger.debug(f"Parsing risposta ricerca per {company_name}:\n{response_text[:300]}...")
        try:
            # Cerca il primo blocco JSON nella risposta
            json_match = re.search(r'\{\s*"url":.*?\s*\}', response_text, re.DOTALL | re.IGNORECASE)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)

                # Validazione più robusta della struttura e dei tipi
                required_keys = {"url", "year", "confidence", "source_type_found"}
                if not isinstance(data, dict) or not required_keys.issubset(data.keys()):
                     logger.warning(f"JSON ricerca incompleto ricevuto per {company_name}. Chiavi mancanti o struttura errata. JSON: {data}")
                     return None

                # Controlla tipi (permetti null per url e year)
                if not (data["url"] is None or isinstance(data["url"], str)):
                     logger.warning(f"Tipo non valido per 'url' in JSON ricerca per {company_name}: {type(data['url'])}. JSON: {data}")
                     return None
                if not (data["year"] is None or isinstance(data["year"], str)): # Year è atteso come stringa YYYY
                     # Prova a convertire se è un numero
                     if isinstance(data["year"], int) and len(str(data["year"]))==4:
                          data["year"] = str(data["year"])
                     else:
                          logger.warning(f"Tipo o formato non valido per 'year' in JSON ricerca per {company_name}: {data['year']}. JSON: {data}")
                          return None
                if not isinstance(data["confidence"], str) or data["confidence"].upper() not in ["ALTA", "MEDIA", "BASSA"]:
                     logger.warning(f"Valore non valido per 'confidence' in JSON ricerca per {company_name}: {data['confidence']}. JSON: {data}")
                     # Forziamo un default se non valido? O scartiamo? Per ora scartiamo.
                     return None
                if not isinstance(data["source_type_found"], str):
                     logger.warning(f"Tipo non valido per 'source_type_found' in JSON ricerca per {company_name}: {type(data['source_type_found'])}. JSON: {data}")
                     return None

                # Se i controlli passano, ritorna i dati
                logger.debug(f"JSON ricerca parsato con successo per {company_name}.")
                return data

            else:
                logger.warning(f"Nessun JSON valido trovato nella risposta di ricerca per {company_name}. Risposta: {response_text[:200]}...")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Errore parsing JSON ricerca per {company_name}: {e}. Risposta: {response_text[:500]}...")
            return None
        except Exception as e:
            logger.error(f"Errore generico durante il parsing della risposta di ricerca per {company_name}: {e}", exc_info=True)
            return None

    @retry(tries=3, delay=5, backoff=2, logger=logger) # Riprova su errori API (es. 5xx, rate limit)
    def _call_gemini_search(self, prompt, company_name):
        """Chiama l'API Gemini per la ricerca con gestione dei tentativi e logging."""
        logger.debug(f"Chiamata API Gemini Search per {company_name}...")
        # logger.debug(f"Prompt inviato:\n{prompt}") # Loggare il prompt può essere utile ma verboso
        try:
            response = self.search_model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2, # Bassa T per risposte più fattuali e aderenti al formato
                    "max_output_tokens": 1024, # Sufficiente per il JSON e un po' di margine
                    "top_p": 0.95, # Default
                    #"response_mime_type": "application/json" # Desiderabile ma non sempre supportato/affidabile
                }
                # Aggiungere safety settings se necessario
            )
            logger.debug(f"Risposta API Gemini Search ricevuta per {company_name}.")
            # A volte l'API può restituire un blocco vuoto o metadata invece del testo
            if not response.parts:
                 logger.warning(f"Risposta API Gemini Search per {company_name} non contiene parti testuali.")
                 # Potrebbe essere un blocco per safety? Controlla response.prompt_feedback
                 if response.prompt_feedback and response.prompt_feedback.block_reason:
                     logger.error(f"Prompt bloccato per {company_name}. Ragione: {response.prompt_feedback.block_reason}")
                     # Qui potremmo sollevare un'eccezione specifica per gestirla sopra
                     raise ValueError(f"Prompt blocked due to safety reasons: {response.prompt_feedback.block_reason}")
                 return "" # Ritorna stringa vuota se non bloccato ma senza parti

            return response.text # Estrae il contenuto testuale

        except Exception as e:
            # Gestisce errori specifici dell'API genai se disponibili, altrimenti errore generico
            logger.warning(f"Errore API Gemini durante la ricerca per {company_name}: {e}. Nuovo tentativo...")
            # Rilancia l'eccezione per far funzionare il decoratore @retry
            raise

    def process_company(self, company_data):
        """
        Elabora una singola azienda: Ricerca -> Scraping -> Validazione -> [Ottimizzazione -> Ricerca -> Validazione]
        """
        company_name = company_data['CompanyName']
        source_type_requested = company_data['SourceType']
        log_prefix = f"[{company_name} ({source_type_requested})]" # Prefisso per i log di questa azienda
        logger.info(f"{log_prefix} --- Inizio elaborazione ---")

        current_prompt = self.prompt_generator.generate_prompt(company_name, source_type_requested)
        final_result = None # Memorizza il risultato finale (validato o l'ultimo tentato)
        validation_status = "Not Processed"
        final_feedback = {}
        actual_iterations = 0 # Contatore iterazioni effettive

        # Esegui lo scraping preliminare UNA SOLA VOLTA all'inizio
        scraping_results = None
        try:
            scraping_results = self.scraper.scrape_financial_sources(company_name, source_type_requested)
            logger.info(f"{log_prefix} Risultati scraping preliminare: {scraping_results[:2]}") # Logga solo URL e Anno per brevità
        except Exception as e:
            logger.error(f"{log_prefix} Errore grave durante lo scraping preliminare: {e}", exc_info=True)
            # Non bloccare il processo, continua senza dati di scraping

        # Ciclo di Ricerca -> Validazione -> Ottimizzazione
        for iteration in range(self.max_iterations):
            actual_iterations += 1 # Incrementa contatore iterazioni effettive
            logger.info(f"{log_prefix} Iterazione {actual_iterations}/{self.max_iterations}")
            validation_status = "Attempted" # Stato cambia appena si prova

            # 1. Chiama Gemini Search
            gemini_result = None
            try:
                gemini_response_text = self._call_gemini_search(current_prompt, company_name)
                if gemini_response_text: # Controlla se la risposta non è vuota
                    gemini_result = self._parse_search_response(gemini_response_text, company_name)
                else:
                     logger.warning(f"{log_prefix} Risposta vuota da Gemini Search.")

            except Exception as e:
                logger.error(f"{log_prefix} Errore chiamata/parsing Gemini Search (Iterazione {actual_iterations}): {e}")
                # Se la chiamata fallisce anche dopo i retry, non possiamo continuare questa iterazione
                # Potremmo uscire dal loop o semplicemente registrare il fallimento per questa iterazione
                final_feedback = {"problems": [f"Errore API Gemini Search: {e}"], "suggestions": ["Riprovare più tardi."]}
                validation_status = "Failed (API Error)"
                # Conserva l'ultimo risultato valido, se esiste
                if final_result is None: # Se è il primo tentativo e fallisce subito
                     final_result = {'url': None, 'year': None, 'confidence': 'BASSA', 'source_type_found': 'Error'}
                break # Interrompi il ciclo per questa azienda se l'API search fallisce gravemente


            # Se Gemini non restituisce un JSON valido o restituisce null
            if not gemini_result or gemini_result.get("url") is None:
                logger.warning(f"{log_prefix} Risultato non valido o nullo da Gemini Search.")
                final_feedback = {"problems": ["Ricerca Gemini non ha prodotto un URL valido o risultato parsabile."], "suggestions": ["Riformulare prompt.", "Verificare nome azienda e tipo fonte."]}
                # Se non abbiamo nessun risultato precedente, impostane uno vuoto
                if final_result is None:
                     final_result = {'url': None, 'year': None, 'confidence': 'BASSA', 'source_type_found': 'Not Found'}
                # Non passare alla validazione se non c'è URL
                if iteration < self.max_iterations - 1:
                     logger.info(f"{log_prefix} Tentativo di ottimizzazione prompt...")
                     current_prompt = self.prompt_generator.optimize_prompt(company_name, final_feedback, current_prompt, scraping_results)
                     time.sleep(random.uniform(1, 3)) # Pausa prima della prossima iterazione
                     continue # Passa alla prossima iterazione con il prompt ottimizzato
                else:
                     validation_status = "Failed (No Result Found)"
                     break # Fine iterazioni


            # Conserva questo risultato come l'ultimo valido tentato
            final_result = gemini_result
            url_to_validate = gemini_result.get('url')
            year_to_validate = gemini_result.get('year')

            # 2. Valida il risultato ottenuto
            try:
                validation_response = self.validator.validate_result(
                    company_name, source_type_requested, url_to_validate, year_to_validate, scraping_results
                )
                validated = validation_response.get("validated", False)
                final_feedback = validation_response.get("feedback", {}) # Aggiorna il feedback con quello del validatore

                if validated:
                    logger.info(f"{log_prefix} *** Risultato VALIDATO all'iterazione {actual_iterations} ***")
                    validation_status = 'Validated'
                    break # Esce dal loop se il risultato è validato

                else:
                    # Risultato non validato, prepara per prossima iterazione (se ce ne sono)
                    logger.warning(f"{log_prefix} Risultato NON validato. Feedback: {final_feedback.get('problems')}")
                    validation_status = "Failed (Validation)"
                    if iteration < self.max_iterations - 1:
                         logger.info(f"{log_prefix} Tentativo di ottimizzazione prompt...")
                         current_prompt = self.prompt_generator.optimize_prompt(company_name, final_feedback, current_prompt, scraping_results)
                         time.sleep(random.uniform(1, 3)) # Pausa
                         # Continua il loop con il nuovo prompt
                    else:
                         logger.warning(f"{log_prefix} Massimo numero di iterazioni ({self.max_iterations}) raggiunto senza validazione.")
                         break # Esce dal loop dopo l'ultima iterazione fallita

            except Exception as e:
                # Errore durante la chiamata al validatore
                logger.error(f"{log_prefix} Errore grave durante la validazione (Iterazione {actual_iterations}): {e}", exc_info=True)
                final_feedback = {"problems": [f"Errore API/Sistema Validatore: {e}"], "suggestions": ["Riprovare."]}
                validation_status = "Failed (Validation Error)"
                # Esci dal loop per questa azienda se il validatore ha problemi seri
                break


        # Fine del ciclo per l'azienda, registra il risultato finale
        logger.info(f"{log_prefix} --- Elaborazione terminata (Status: {validation_status}) ---")

        # Prepara i dati finali per il CSV, usando l'ultimo `final_result` ottenuto
        # (che sia validato o l'ultimo tentativo non validato)
        output_data = {
            'CompanyName': company_name,
            'SourceTypeRequested': source_type_requested,
            'FinalURL': final_result.get('url') if final_result else None,
            'FinalYear': final_result.get('year') if final_result else None,
            'FinalConfidence': final_result.get('confidence') if final_result else 'N/A',
            'FinalSourceTypeFound': final_result.get('source_type_found') if final_result else 'N/A',
            'ValidationStatus': validation_status,
            'ValidationFeedback': json.dumps(final_feedback), # Salva l'ultimo feedback come JSON string
            'ScrapingURL': scraping_results[0] if scraping_results else None,
            'ScrapingYear': scraping_results[1] if scraping_results else None,
            'ScrapingConfidence': scraping_results[3] if scraping_results else None,
            'Iterations': actual_iterations # Salva iterazioni effettive
        }
        return output_data


    def run(self):
        """Esegue il processo per tutte le aziende nel CSV usando ThreadPoolExecutor"""
        companies = self.load_companies()

        logger.info(f"Avvio elaborazione parallela per {len(companies)} aziende con {self.max_workers} workers...")

        # Usa ThreadPoolExecutor per parallelizzare `process_company`
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix='Worker') as executor:
            # Usa tqdm per mostrare una barra di progresso
            # `executor.map` mantiene l'ordine dei risultati rispetto all'input `companies`
            futures = [executor.submit(self.process_company, company) for company in companies]
            self.results = []
            for future in tqdm(futures, total=len(companies), desc="Processing Companies", unit="company"):
                 try:
                      # Raccogli i risultati man mano che sono pronti
                      result = future.result()
                      self.results.append(result)
                 except Exception as e:
                      # Cattura eccezioni non gestite all'interno di process_company (anche se dovrebbe gestirle)
                      logger.error(f"Errore irreversibile nell'elaborazione di un'azienda: {e}", exc_info=True)
                      # Potremmo voler aggiungere un risultato di errore qui se necessario
                      # self.results.append({...error data...})


        logger.info("Elaborazione parallela completata.")
        self.save_results()

    def save_results(self):
        """Salva i risultati raccolti in un file CSV"""
        if not self.results:
            logger.warning("Nessun risultato da salvare.")
            return

        # Converti la lista di dizionari in DataFrame
        try:
            df_results = pd.DataFrame(self.results)

            # Ordina le colonne per leggibilità
            column_order = [
                'CompanyName', 'SourceTypeRequested', 'ValidationStatus',
                'FinalURL', 'FinalYear', 'FinalConfidence', 'FinalSourceTypeFound',
                'ScrapingURL', 'ScrapingYear', 'ScrapingConfidence',
                'Iterations', 'ValidationFeedback'
            ]
            # Assicurati che tutte le colonne esistano prima di riordinare
            existing_columns = [col for col in column_order if col in df_results.columns]
            df_results = df_results[existing_columns]


            df_results.to_csv(self.output_csv, index=False, encoding='utf-8-sig') # utf-8-sig per compatibilità Excel
            logger.info(f"Risultati salvati con successo in: {self.output_csv}")

        except Exception as e:
            logger.error(f"Errore durante la creazione o il salvataggio del DataFrame dei risultati in CSV: {e}", exc_info=True)


# --- Blocco di esecuzione principale ---
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Trova fonti finanziarie per MNE usando Gemini, Web Scraping e Auto-Tuning dei Prompt.")
    parser.add_argument("csv_path", help="Percorso del file CSV di input (colonne obbligatorie: CompanyName, SourceType - ignora maiuscole/minuscole)")
    parser.add_argument("-k", "--api_key", default=os.environ.get("GOOGLE_API_KEY"), help="API Key di Google Gemini (predefinita: legge variabile d'ambiente GOOGLE_API_KEY)")
    parser.add_argument("-o", "--output", default="financial_sources_output.csv", help="Nome del file CSV di output (predefinito: financial_sources_output.csv)")
    parser.add_argument("-w", "--workers", type=int, default=5, help="Numero di worker paralleli (predefinito: 5)")
    parser.add_argument("-i", "--iterations", type=int, default=3, help="Numero massimo di cicli Ricerca->Validazione->Ottimizzazione per azienda (predefinito: 3)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Abilita logging a livello DEBUG (molto verboso)")


    args = parser.parse_args()

    # Imposta livello di logging DEBUG se richiesto
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("Logging a livello DEBUG abilitato.")


    start_time = time.time()

    # Inizializza il Finder (che configurerà e verificherà l'API Key)
    try:
        finder = FinancialSourceFinder(
            csv_path=args.csv_path,
            api_key=args.api_key,
            output_csv=args.output,
            max_workers=args.workers,
            max_iterations=args.iterations
        )
    except SystemExit:
         # Se l'inizializzazione fallisce (es. API key errata, CSV non trovato), esce
         sys.exit(1)
    except Exception as e:
         logger.critical(f"Errore critico durante l'inizializzazione: {e}", exc_info=True)
         sys.exit(1)


    # Esegui il processo principale
    try:
        finder.run()
    except Exception as e:
        logger.critical(f"Errore critico durante l'esecuzione principale: {e}", exc_info=True)
        sys.exit(1)


    end_time = time.time()
    logger.info(f"Processo completato in {end_time - start_time:.2f} secondi.")
    logger.info(f"File di output generato: {args.output}")
    logger.info(f"Log dettagliato disponibile in: financial_sources_finder.log")