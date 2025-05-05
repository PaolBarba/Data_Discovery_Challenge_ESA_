import logging
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from google.generativeai import genai
from prompts.base_prompt import base_prompt_template
from utils import laod_config_yaml

# Configurazione logging
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



class PromptGenerator:
    """Mananage the prompt generation and optimization for the financial data source finder."""

    def __init__(self):
        """Inizialize the prompt generator."""
        self.config = laod_config_yaml("src/Data_Discovery/config/model_config/config.yaml")
        # Base prompt template for generating the initial prompt
        self.base_prompt_template = base_prompt_template

        # Initial instructions for optimization
        self.optimization_instructions = ""

        # Dictionary to store company-specific prompts
        self.company_specific_prompts = {}

        # Counter for tracking the number of optimizations per company
        self.optimization_counter = {}

    def generate_prompt(self, company_name:str, source_type:str)-> str:
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
            model = genai.GenerativeModel(self.config["model_name"])
            response = model.generate_content(
                optimization_request,
                generation_config={
                    "temperature": self.config["temperature"],
                    "top_p": self.config["top_p"],
                    "max_output_tokens": self.config["max_output_tokens"],
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
        """Create the request for optimization of the prompt."""
        scraping_info = ""
        if scraping_results:
            url, year, desc, conf = scraping_results
            scraping_info = f"""
            Web scraping found the following information:
            - URL: {url if url else 'Not found'}
            - Year: {year if year else 'Not found'}
            - Source type: {desc if desc else 'Not identified'}
            - Confidence: {conf}
            """

        return f"""
        YOU ARE AN EXPERT IN PROMPT ENGINEERING specializing in optimizing prompts for artificial intelligence systems.

        TASK: Optimize the existing prompt to improve the search for financial data for the company "{company_name}".

        FEEDBACK FROM THE LAST ATTEMPT:
        - Identified issues: {feedback.get('problems', 'No data found or validated')}
        - Suggestions: {feedback.get('suggestions', 'N/A')}
        - Critical points: {feedback.get('critical_points', 'N/A')}

        {scraping_info}

        CURRENT PROMPT:
        ```
        {current_prompt}
        ```

        INSTRUCTIONS FOR OPTIMIZATION:
        1. Maintain the general structure of the prompt
        2. Add specific instructions to address the identified issues
        3. Improve the precision of requests to obtain direct URLs to documents
        4. Ensure the prompt explicitly requests the correct fiscal year
        5. Strengthen search priorities based on the type of source requested

        RETURN ONLY THE NEW OPTIMIZED PROMPT, WITHOUT ADDITIONAL EXPLANATIONS OR COMMENTS.
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
