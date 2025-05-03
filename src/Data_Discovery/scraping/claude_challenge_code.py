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

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("financial_sources_finder.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configurare l'API di Google Gemini
API_KEY = os.environ.get("GOOGLE_API_KEY", "")  # Inserisci la tua API key se non è impostata come variabile d'ambiente
genai.configure(api_key=API_KEY)

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
        self.max_retries = max_retries
        
        if user_agent is None:
            # Rotazione di user agent per evitare blocchi
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0'
            ]
            user_agent = random.choice(user_agents)
            
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'en-US,en;q=0.9'
        })
    
    @retry(tries=3, delay=2, backoff=2)
    def get_page(self, url):
        """
        Ottiene il contenuto di una pagina web con gestione dei tentativi
        
        Args:
            url (str): URL della pagina da scaricare
            
        Returns:
            str: Contenuto HTML della pagina o None in caso di errore
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Status code non 200 per {url}: {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Errore durante il download della pagina {url}: {e}")
            raise  # La decorazione retry gestirà i nuovi tentativi
    
    def find_company_website(self, company_name):
        """
        Cerca il sito web ufficiale di un'azienda utilizzando una ricerca Google
        
        Args:
            company_name (str): Nome dell'azienda
            
        Returns:
            str: URL del sito aziendale o None
        """
        try:
            # Utilizziamo un'API di ricerca (in questo caso DuckDuckGo per evitare limitazioni)
            # In produzione si potrebbe utilizzare un'API di ricerca a pagamento
            search_url = f"https://duckduckgo.com/html/?q={company_name}+official+website"
            html = self.get_page(search_url)
            
            if not html:
                return None
                
            soup = BeautifulSoup(html, 'html.parser')
            results = soup.find_all('a', {'class': 'result__url'})
            
            # Filtra i risultati per ottenere domini aziendali plausibili
            for result in results:
                url = result.get('href')
                if url and self._is_corporate_domain(url, company_name):
                    # Verifica che sia davvero un sito aziendale
                    return self._normalize_url(url)
            
            # Metodo alternativo: cerca nella pagina dei risultati qualsiasi URL che contenga parti del nome dell'azienda
            all_links = soup.find_all('a')
            for link in all_links:
                url = link.get('href')
                if url and self._is_potential_corporate_domain(url, company_name):
                    return self._normalize_url(url)
                    
            return None
        except Exception as e:
            logger.error(f"Errore durante la ricerca del sito web di {company_name}: {e}")
            return None
    
    def _is_corporate_domain(self, url, company_name):
        """Verifica se un URL è probabilmente il dominio aziendale"""
        domain = urlparse(url).netloc
        
        # Rimuovi www. e converti in lowercase
        domain = domain.lower().replace('www.', '')
        company_tokens = set(self._tokenize_company_name(company_name.lower()))
        
        # Verifica se almeno un token significativo del nome dell'azienda è nel dominio
        return any(token in domain for token in company_tokens if len(token) > 2)
    
    def _is_potential_corporate_domain(self, url, company_name):
        """Verifica meno stringente per identificare possibili domini aziendali"""
        # Rimuovi parametri e frammenti
        url = url.split('?')[0].split('#')[0]
        
        # Ignora URL di motori di ricerca e siti noti non aziendali
        non_corporate_domains = ['google.', 'facebook.', 'youtube.', 'linkedin.', 'twitter.', 
                                'amazon.', 'bing.', 'yahoo.', 'instagram.', 'wikipedia.']
        
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
        significant_tokens = [t for t in company_tokens if len(t) > 2 and t not in ['inc', 'ltd', 'the', 'and', 'corp']]
        return any(token in domain for token in significant_tokens)
    
    def _tokenize_company_name(self, name):
        """Divide il nome dell'azienda in token significativi"""
        # Rimuovi elementi comuni come Inc, Corp, Ltd
        cleaned = re.sub(r'\b(inc|corp|corporation|ltd|limited|llc|group|holding|holdings)\b', '', name, flags=re.IGNORECASE)
        
        # Dividi in token
        tokens = re.findall(r'\b\w+\b', cleaned)
        return [t for t in tokens if len(t) > 1]
    
    def _normalize_url(self, url):
        """Normalizza un URL garantendo che sia completo e valido"""
        if not (url.startswith('http://') or url.startswith('https://')):
            url = 'https://' + url.lstrip('/')
            
        # Rimuovi parametri e frammenti
        url = url.split('?')[0].split('#')[0]
        
        # Assicurati che termini con uno slash
        if not url.endswith('/'):
            url += '/'
            
        return url
    
    def find_investor_relations_page(self, company_url):
        """
        Cerca la pagina delle relazioni con gli investitori sul sito aziendale
        
        Args:
            company_url (str): URL del sito aziendale
            
        Returns:
            str: URL della pagina IR o None
        """
        try:
            # Scarica la home page
            html = self.get_page(company_url)
            if not html:
                return None
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Cerca link che contengono termini relativi a IR
            ir_keywords = ['investor', 'investors', 'investor relations', 'ir/', 'financials', 
                          'shareholders', 'financial information', 'annual report', 'quarterly report']
            
            # Cerca nei menu principali e nei footer
            for link in soup.find_all('a'):
                text = link.get_text().lower().strip()
                href = link.get('href')
                
                if not href:
                    continue
                    
                # Controlla se il testo del link o l'URL contiene parole chiave IR
                if any(keyword in text or keyword in href.lower() for keyword in ir_keywords):
                    full_url = urljoin(company_url, href)
                    return full_url
            
            # Metodo alternativo: cerca nella sitemap se disponibile
            sitemap_url = urljoin(company_url, 'sitemap.xml')
            try:
                sitemap_content = self.get_page(sitemap_url)
                if sitemap_content:
                    sitemap_soup = BeautifulSoup(sitemap_content, 'xml')
                    for loc in sitemap_soup.find_all('loc'):
                        url = loc.text
                        if any(keyword in url.lower() for keyword in ir_keywords):
                            return url
            except Exception:
                pass  # Ignora gli errori nella ricerca della sitemap
                
            return None
        except Exception as e:
            logger.error(f"Errore durante la ricerca della pagina IR su {company_url}: {e}")
            return None
    
    def find_financial_reports(self, ir_page_url, source_type='Annual Report'):
        """
        Cerca i report finanziari nella pagina delle relazioni con gli investitori
        
        Args:
            ir_page_url (str): URL della pagina delle relazioni con gli investitori
            source_type (str): Tipo di report da cercare (Annual, Quarterly, Consolidated)
            
        Returns:
            list: Lista di tuple (url, anno) dei report trovati
        """
        try:
            html = self.get_page(ir_page_url)
            if not html:
                return []
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Determina le parole chiave in base al tipo di report
            if source_type.lower() == 'annual report' or source_type.lower() == 'annual':
                keywords = ['annual report', 'annual filing', '10-k', 'yearly report', 'form 10-k', 
                           'annual financial report', 'year-end report']
            elif source_type.lower() == 'quarterly report' or source_type.lower() == 'quarterly':
                keywords = ['quarterly report', 'quarterly filing', '10-q', 'form 10-q', 'q1', 'q2', 'q3', 'q4']
            elif source_type.lower() == 'consolidated':
                keywords = ['consolidated financial', 'consolidated statement', 'consolidated report', 
                           'consolidated annual report', 'consolidated results']
            else:
                keywords = ['financial report', 'financial statement', 'financial results', 'earnings report']
            
            # Cerca report sia nei link testuali che nei PDF/documenti
            results = []
            
            # Cerca link a documenti PDF o simili
            for link in soup.find_all('a'):
                text = link.get_text().strip()
                href = link.get('href', '')
                
                # Verifica se è un link a un documento finanziario
                is_financial_doc = any(keyword in text.lower() or keyword in href.lower() for keyword in keywords)
                is_document = href.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.html'))
                
                if is_financial_doc and (is_document or 'download' in href.lower()):
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
    
    def _extract_year_from_text(self, text):
        """Estrae l'anno da un testo"""
        # Cerca pattern come "2023", "FY2023", "FY 2023", "2022-2023"
        year_patterns = [
            r'20\d{2}',  # Anno standard a 4 cifre
            r'FY\s*20\d{2}',  # Anno fiscale
            r'20\d{2}[/-]20\d{2}'  # Intervallo di anni
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, text)
            if match:
                year_text = match.group(0)
                # Estrai solo il primo anno completo nel caso di intervalli
                year = re.search(r'20\d{2}', year_text).group(0)
                return year
                
        return None
    
    def _extract_year_from_url(self, url):
        """Estrae l'anno da un URL o nome di file"""
        # Simile all'estrazione dal testo, ma specifico per URL
        year_patterns = [
            r'20\d{2}',  # Anno standard
            r'FY-?20\d{2}',  # FY2023 o FY-2023
            r'AR-?20\d{2}'  # AR2023 o AR-2023 (Annual Report)
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, url)
            if match:
                year_text = match.group(0)
                # Estrai solo l'anno numerico
                year = re.search(r'20\d{2}', year_text).group(0)
                return year
                
        return None
    
    def find_sec_filings(self, company_name, form_type='10-K'):
        """
        Cerca i filing SEC per le aziende quotate negli USA
        
        Args:
            company_name (str): Nome dell'azienda
            form_type (str): Tipo di form SEC (10-K, 10-Q, ecc.)
            
        Returns:
            list: Lista di tuple (url, anno) dei filing trovati
        """
        try:
            # Simulazione di ricerca SEC (in produzione si utilizzerebbe l'API SEC EDGAR)
            # Per semplicità utilizziamo un approccio di scraping di base
            search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={company_name}&type={form_type}&count=10"
            html = self.get_page(search_url)
            
            if not html:
                return []
                
            soup = BeautifulSoup(html, 'html.parser')
            results = []
            
            # Cerca le tabelle dei risultati
            filing_items = soup.find_all('tr')
            for item in filing_items:
                # Cerca la data del filing
                date_elem = item.find('td', {'nowrap': 'nowrap'})
                if not date_elem:
                    continue
                    
                date_text = date_elem.get_text().strip()
                year_match = re.search(r'20\d{2}', date_text)
                if not year_match:
                    continue
                    
                year = year_match.group(0)
                
                # Cerca il link ai documenti
                doc_link = item.find('a', text=re.compile(r'Documents'))
                if not doc_link:
                    continue
                    
                doc_url = urljoin('https://www.sec.gov', doc_link.get('href'))
                
                results.append((doc_url, year))
            
            # Ordina per anno (più recente prima)
            results.sort(key=lambda x: x[1], reverse=True)
            
            return results
        except Exception as e:
            logger.error(f"Errore durante la ricerca di filing SEC per {company_name}: {e}")
            return []
    
    def scrape_financial_sources(self, company_name, source_type):
        """
        Esegue il web scraping completo per trovare le fonti finanziarie di un'azienda
        
        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            
        Returns:
            tuple: (url, year, source_description, confidence)
        """
        logger.info(f"Avvio scraping per {company_name} (tipo: {source_type})")
        
        # Step 1: Trova il sito web aziendale
        company_url = self.find_company_website(company_name)
        if not company_url:
            logger.warning(f"Impossibile trovare il sito web di {company_name}")
            
            # Prova con ricerca SEC se potrebbe essere un'azienda USA
            if self._could_be_us_company(company_name):
                logger.info(f"Tentativo di ricerca SEC per {company_name}")
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]  # Il più recente
                    return best_url, best_year, "SEC Filing", "MEDIA"
            
            return None, None, None, "BASSA"
        
        logger.info(f"Trovato sito web per {company_name}: {company_url}")
        
        # Step 2: Trova la pagina delle relazioni con gli investitori
        ir_page = self.find_investor_relations_page(company_url)
        if not ir_page:
            logger.warning(f"Impossibile trovare la pagina IR per {company_name}")
            
            # Prova con ricerca SEC come fallback
            if self._could_be_us_company(company_name):
                sec_results = self.find_sec_filings(company_name)
                if sec_results:
                    best_url, best_year = sec_results[0]
                    return best_url, best_year, "SEC Filing", "MEDIA"
            
            return None, None, None, "BASSA"
        
        logger.info(f"Trovata pagina IR per {company_name}: {ir_page}")
        
        # Step 3: Trova i report finanziari
        reports = self.find_financial_reports(ir_page, source_type)
        
        # Se non ci sono risultati con l'IR page, prova a cercare anche nella SEC
        if not reports and self._could_be_us_company(company_name):
            form_type = '10-K' if source_type.lower() in ['annual', 'annual report'] else '10-Q'
            sec_results = self.find_sec_filings(company_name, form_type)
            reports.extend(sec_results)
        
        if not reports:
            logger.warning(f"Nessun report finanziario trovato per {company_name}")
            return None, None, None, "BASSA"
        
        # Seleziona il report più recente
        best_url, best_year = reports[0]
        
        # Determina la descrizione della fonte e il livello di confidenza
        if 'sec.gov' in best_url:
            source_description = "SEC Filing"
            confidence = "ALTA"
        elif best_url.lower().endswith('.pdf'):
            source_description = f"{source_type} PDF"
            confidence = "ALTA"
        else:
            source_description = source_type
            confidence = "MEDIA"
        
        logger.info(f"Trovato report per {company_name}: {best_url} (Anno: {best_year})")
        
        return best_url, best_year, source_description, confidence
    
    def _could_be_us_company(self, company_name):
        """Verifica euristica se un'azienda potrebbe essere statunitense"""
        us_indicators = ['Inc', 'Inc.', 'Corp', 'Corp.', 'LLC', 'LLP', 'Co.', 'USA', 'America', 'US ']
        return any(indicator in company_name for indicator in us_indicators)
                
class PromptGenerator:
    """Gestore della generazione e ottimizzazione dei prompt per Gemini"""
    
    def __init__(self):
        """Inizializza il generatore di prompt con modelli di base"""
        # Prompt base che verrà ottimizzato
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
        Genera un prompt personalizzato per una specifica azienda
        
        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            
        Returns:
            str: Prompt ottimizzato
        """
        # Verifica se esiste un prompt specifico per questa azienda
        if company_name in self.company_specific_prompts:
            return self.company_specific_prompts[company_name]
        
        # Istruzioni di ottimizzazione generali
        optimization_text = self.optimization_instructions
        
        # Arricchimento con informazioni specifiche per aziende note
        company_info = self._get_company_additional_info(company_name)
        if company_info:
            optimization_text += f"\n\nINFORMAZIONI AGGIUNTIVE SU QUESTA AZIENDA: {company_info}"
        
        # Generazione del prompt finale
        prompt = self.base_prompt_template.format(
            company_name=company_name,
            source_type=source_type,
            optimization_instructions=optimization_text
        )
        
        return prompt
    
    def optimize_prompt(self, company_name, feedback, current_prompt, scraping_results=None):
        """
        Ottimizza il prompt in base al feedback del sistema di valutazione
        
        Args:
            company_name (str): Nome dell'azienda
            feedback (dict): Feedback dal sistema di valutazione
            current_prompt (str): Prompt attuale
            scraping_results (tuple): Risultati dello scraping (url, year, description, confidence)
            
        Returns:
            str: Prompt ottimizzato
        """
        # Incrementa il contatore di ottimizzazioni per questa azienda
        if company_name not in self.optimization_counter:
            self.optimization_counter[company_name] = 0
        self.optimization_counter[company_name] += 1
        
        # Limite di ottimizzazioni per evitare loop infiniti
        if self.optimization_counter[company_name] > 5:
            logger.warning(f"Raggiunto limite di ottimizzazioni per {company_name}, utilizzo risultati di scraping")
            return self._generate_scraping_based_prompt(company_name, scraping_results)
        
        # Genera un prompt per chiedere l'ottimizzazione basata sul feedback
        optimization_request = self._create_optimization_request(company_name, feedback, current_prompt, scraping_results)
        
        try:
            # Richiedi a Gemini di ottimizzare il prompt
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(
                optimization_request,
                generation_config={
                    "temperature": 0.2,
                    "top_p": 0.95,
                    "max_output_tokens": 2048,
                }
            )
            
            # Estrai il nuovo prompt ottimizzato
            optimized_prompt = response.text.strip()
            
            # Verifica che sia un prompt valido
            if len(optimized_prompt) < 100 or "{company_name}" not in optimized_prompt:
                logger.warning(f"Ottimizzazione non valida per {company_name}, utilizzo prompt basato su scraping")
                return self._generate_scraping_based_prompt(company_name, scraping_results)
            
            # Memorizza il prompt ottimizzato specifico per questa azienda
            self.company_specific_prompts[company_name] = optimized_prompt
            
            logger.info(f"Prompt ottimizzato con successo per {company_name} (tentativo {self.optimization_counter[company_name]})")
            
            return optimized_prompt
            
        except Exception as e:
            logger.error(f"Errore durante l'ottimizzazione del prompt per {company_name}: {e}")
            # In caso di errore, utilizza i risultati dello scraping
            return self._generate_scraping_based_prompt(company_name, scraping_results)
    
    def _create_optimization_request(self, company_name, feedback, current_prompt, scraping_results):
        """Crea la richiesta per l'ottimizzazione del prompt"""
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
                optimization_instructions="ATTENZIONE: Cerca con particolare attenzione, i tentativi precedenti non hanno prodotto risultati validi."
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
            year_hint = f"\n- L'anno fiscale {year} sembra essere disponibile, ma verifica se esistono report più recenti"
        
        optimization_text = f"""
        SUGGERIMENTI BASATI SU RICERCHE PRECEDENTI:
        - Il tipo di fonte '{desc}' sembra appropriato per questa azienda{domain_hint}{year_hint}
        - La precedente ricerca ha avuto un livello di confidenza '{conf}', cerca di migliorarlo
        """
        
        return self.base_prompt_template.format(
            company_name=company_name,
            source_type=desc or "Annual Report",
            optimization_instructions=optimization_text
        )
    
    def _get_company_additional_info(self, company_name):
        """Fornisce informazioni aggiuntive per aziende note"""
        # Dizionario di informazioni per aziende note
        known_companies = {
            "Apple": "Azienda tecnologica USA, ticker: AAPL, report finanziari disponibili su investor.apple.com e SEC",
            "Microsoft": "Azienda tecnologica USA, ticker: MSFT, report disponibili su microsoft.com/investor e SEC",
            "Amazon": "E-commerce e cloud USA, ticker: AMZN, report su ir.aboutamazon.com e SEC",
            "Google": "Cerca anche come 'Alphabet Inc', ticker: GOOGL, report su abc.xyz/investor e SEC",
            "Alphabet": "Società madre di Google, ticker: GOOGL, report su abc.xyz/investor e SEC",
            "Tesla": "Azienda automotive USA, ticker: TSLA, report su ir.tesla.com e SEC",
            "Volkswagen": "Azienda automotive tedesca, report disponibili su volkswagenag.com/en/InvestorRelations",
            "Toyota": "Azienda automotive giapponese, report disponibili su global.toyota/en/ir/",
            "Samsung": "Azienda tecnologica sudcoreana, report disponibili su samsung.com/global/ir/",
            "Nestlé": "Azienda alimentare svizzera, report disponibili su nestle.com/investors"
        }
        
        # Cerca corrispondenze parziali nel nome dell'azienda
        for known_name, info in known_companies.items():
            if known_name.lower() in company_name.lower() or company_name.lower() in known_name.lower():
                return info
        
        return None

class PromptTuner:
    """Modulo per l'ottimizzazione automatica dei prompt basata sui feedback"""
    
    def __init__(self, initial_prompt_template=None):
        """
        Inizializza il tuner con un prompt iniziale
        
        Args:
            initial_prompt_template (str): Template del prompt iniziale
        """
        self.current_prompt = initial_prompt_template or """
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
        
        self.tuning_history = []
        self.model = genai.GenerativeModel('gemini-pro')
    
    def generate_prompt(self, company_name, source_type):
        """
        Genera un prompt personalizzato per l'azienda
        
        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            
        Returns:
            str: Prompt completo
        """
        return self.current_prompt.format(
            company_name=company_name,
            source_type=source_type
        )
    
    def improve_prompt(self, company_name, source_type, scraping_result, validation_result):
        """
        Migliora il prompt in base ai risultati della validazione
        
        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            scraping_result (dict): Risultato dello scraping
            validation_result (dict): Risultato della validazione
            
        Returns:
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
            self.tuning_history.append({
                "company": company_name,
                "old_prompt": self.current_prompt,
                "new_prompt": new_prompt,
                "scraping_result": scraping_result,
                "validation_result": validation_result,
                "timestamp": datetime.now().isoformat()
            })
            
            # Aggiorna il prompt corrente
            self.current_prompt = new_prompt
            
            logger.info(f"Prompt migliorato per {company_name}")
            return new_prompt
        except Exception as e:
            logger.error(f"Errore durante il miglioramento del prompt: {e}")
            return self.current_prompt  # Mantieni il prompt attuale in caso di errore


class ResultValidator:
    """Modulo per la validazione dei risultati tramite Mistral API gratuita"""

    def __init__(self):
        """Inizializza il validatore dei risultati"""
        self.api_url = "https://api.mistral.yz.men/v1/chat/completions"
        self.model = "mistral-tiny"  # Puoi cambiare modello se necessario
        # Nessuna API key richiesta per questo endpoint

    def validate_result(self, company_name, source_type, scraping_result):
        """
        Valida i risultati dello scraping utilizzando Mistral

        Args:
            company_name (str): Nome dell'azienda
            source_type (str): Tipo di fonte finanziaria
            scraping_result (dict): Risultato dello scraping

        Returns:
            dict: Risultato della validazione con score e feedback
        """
        url = scraping_result.get('url')
        year = scraping_result.get('year')
        source_description = scraping_result.get('source_description')
        confidence = scraping_result.get('confidence')

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
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": validation_prompt}
                ]
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                result = response.json()
                # Il testo della risposta è in result['choices'][0]['message']['content']
                validation_text = result['choices'][0]['message']['content']
                validation_result = self._extract_json_from_text(validation_text)
                if not validation_result:
                    validation_result = {
                        "is_valid": False,
                        "validation_score": 0,
                        "feedback": "Impossibile analizzare la risposta di validazione",
                        "improvement_suggestions": "Riprova con un prompt più chiaro"
                    }
                logger.info(f"Validazione completata per {company_name}: Score {validation_result.get('validation_score')}")
                return validation_result
            else:
                logger.error(f"Errore API Mistral: {response.status_code} - {response.text}")
                return {
                    "is_valid": False,
                    "validation_score": 0,
                    "feedback": f"Errore API Mistral: {response.status_code}",
                    "improvement_suggestions": "Verifica la connessione e riprova"
                }
        except Exception as e:
            logger.error(f"Errore durante la validazione: {e}")
            return {
                "is_valid": False,
                "validation_score": 0,
                "feedback": f"Errore durante la validazione: {str(e)}",
                "improvement_suggestions": "Verifica la connessione e riprova"
            }

    def _extract_json_from_text(self, text):
        """Estrae un oggetto JSON da una risposta testuale"""
        try:
            json_pattern = r'({[\s\S]*})'
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
            
        Returns:
            dict: Risultato finale con URL, anno e metadati
        """
        logger.info(f"Avvio ricerca per {company_name} (tipo: {source_type})")
        
        # Esegui lo scraping iniziale
        url, year, source_description, confidence = self.scraper.scrape_financial_sources(company_name, source_type)
        
        # Prepara il risultato dello scraping
        scraping_result = {
            "url": url,
            "year": year,
            "source_description": source_description,
            "confidence": confidence
        }
        
        # Valida il risultato
        validation_result = self.validator.validate_result(company_name, source_type, scraping_result)
        
        # Ciclo di tuning automatico
        iteration = 0
        while (not validation_result.get("is_valid", False) or 
               validation_result.get("validation_score", 0) < self.validation_threshold) and \
              iteration < self.max_tuning_iterations:
            
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
                "confidence": confidence
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
            "feedback": validation_result.get("feedback", "")
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
        
    Returns:
        list: Risultati per il batch
    """
    results = []
    for company in companies_batch:
        try:
            result = finder.find_financial_source(company, source_type)
            results.append(result)
        except Exception as e:
            logger.error(f"Errore nell'elaborazione di {company}: {e}")
            results.append({
                "company_name": company,
                "source_type": source_type,
                "url": None,
                "year": None,
                "error": str(e)
            })
    return results


def main():
    """Funzione principale del programma"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Trova fonti finanziarie per multinazionali")
    parser.add_argument("--input", required=True, help="File CSV di input con lista di aziende")
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
        df = pd.read_csv(args.input)
        if 'company_name' not in df.columns:
            # Prova a usare la prima colonna come nome dell'azienda
            company_column = df.columns[0]
            df = df.rename(columns={company_column: 'company_name'})
            logger.warning(f"Colonna 'company_name' non trovata, uso '{company_column}' invece")
    except Exception as e:
        logger.error(f"Errore nel caricamento del CSV: {e}")
        sys.exit(1)
    
    # Inizializza il finder
    finder = FinancialSourcesFinder(
        api_key=api_key,
        max_tuning_iterations=args.max_tuning,
        validation_threshold=args.validation_threshold
    )
    
    # Prepara i batch di aziende
    companies = df['company_name'].tolist()
    batches = [companies[i:i + args.batch_size] for i in range(0, len(companies), args.batch_size)]
    
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
    valid_results = results_df[results_df['is_valid'] == True]
    logger.info(f"Totale aziende elaborate: {len(results_df)}")
    logger.info(f"Risultati validi: {len(valid_results)} ({len(valid_results)/len(results_df)*100:.1f}%)")
    
    # Salva anche un report JSON con dettagli aggiuntivi
    report_path = args.output.replace('.csv', '_report.json')
    with open(report_path, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_companies": len(results_df),
            "valid_results": len(valid_results),
            "validation_rate": len(valid_results)/len(results_df),
            "source_type": args.source_type,
            "results": all_results
        }, f, indent=2)
    logger.info(f"Report dettagliato salvato in {report_path}")


if __name__ == "__main__":
    main()