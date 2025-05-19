"""Prompt generator for financial data source finder."""

import logging
import sys
import time
from urllib.parse import urlparse

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from utils import load_config_yaml

from Data_Discovery.prompts.base_prompt import base_prompt_template, web_scraping_prompt

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class PromptGenerator:
    """Mananage the prompt generation and optimization for the financial data source finder."""

    def __init__(self):
        """Inizialize the prompt generator."""
        self.config = load_config_yaml("src/Data_Discovery/config/model_config/config.yaml")
        # Base prompt template for generating the initial prompt
        self.base_prompt_template = base_prompt_template

        # Dictionary to store company-specific prompts
        self.company_specific_prompts = {}
        self.web_scraping_prompt_template = web_scraping_prompt

        # Counter for tracking the number of optimizations per company
        self.optimization_counter = {}
        self.model = genai.GenerativeModel(self.config["model_name"])

    def generate_prompt(self, company_name: str, source_type: str) -> str:
        """
        Generate the prompt for the given company name and source type.

        Args:
            company_name (str): Name of the company
            source_type (str): Type of financial source (e.g., "Annual Report", "Quarterly Report", "Consolidated").

        Returns
        -------
            str: Prompt optimize.
        """
        optimization_text = ""

        # Enrich the prompt with additional information if available
        company_info = self._get_company_additional_info(company_name)
        if company_info:
            optimization_text += f"\n\nAdditioanl Information: {company_info}"

        # Generate the final prompt
        return self.base_prompt_template.format(company_name=company_name, source_type=source_type, optimization_instructions=optimization_text)

    def optimize_prompt(self, company_name: str, feedback: dict, current_prompt: str, scraping_results: tuple) -> str:
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
        optimization_request = self._create_optimization_request(company_name, feedback, current_prompt, scraping_results)

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
                optimized_prompt,
            )

            return optimized_prompt  # noqa: TRY300

        except Exception:
            logger.exception("Error during prompt optimization for %s", company_name)
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

    def _generate_scraping_based_prompt(self, company_name: str, scraping_results: str) -> str:
        """Generate a prompt based on scraping results when optimization fails."""
        if not scraping_results or not any(scraping_results):
            # No usable scraping results, use an improved generic prompt
            return self.base_prompt_template.format(
                company_name=company_name,
                source_type="Annual Report",
                optimization_instructions="Be careful to search thoroughly, previous attempts have not produced valid results.",
            )

        url, year, desc, conf = scraping_results

        # Create a prompt that incorporates scraping results as suggestions
        domain_hint = ""
        if url:
            try:
                domain = urlparse(url).netloc
                domain_hint = f"\n- Consider the domain {domain} which seems promising for this search"
            except Exception as e:
                logger.exception("Error parsing URL domain: %s", e)  # noqa: TRY401

        year_hint = ""
        if year:
            year_hint = f"\n- The fiscal year {year} appears to be available, but check if more recent reports exist"

        optimization_text = f"""
        SUGGESTIONS BASED ON PREVIOUS SEARCHES:
        - The source type '{desc}' seems appropriate for this company{domain_hint}{year_hint}
        - The previous search had a confidence level of '{conf}', try to improve it
        """

        return self.base_prompt_template.format(company_name=company_name, source_type=desc or "Annual Report", optimization_instructions=optimization_text)

    def _get_company_additional_info(self, company_name: str) -> str:
        """
        Provide predefined specific information (hints) for certain companies.

        These are heuristic suggestions based on common suffixes and well-known names.
        Accuracy is not guaranteed, and the list is not exhaustive.
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
            "h & m hennes & mauritz": "H&M. Azienda Svedese (AB). Cerca 'Investors'. FY finisce Novembre.",
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
            "apple inc.": "Azienda USA. Focus su SEC filings (10-K per Annual, 10-Q per Quarterly) e pagina IR ufficiale: investor.apple.com. Anno fiscale termina a fine Settembre.",  # noqa: E501
            # Siemens già coperto sopra
            # Toyota già coperto sopra
            # Unilever già coperto sopra
        }

        # Cerca una corrispondenza (case-insensitive)
        normalized_company_name = company_name.lower()
        for key, value in known_info.items():
            # Match if the key is contained in the normalized company name
            # Should we prioritize longer/more complete matches if multiple keys are possible?
            # For now, we use the first match found.
            if key in normalized_company_name:
                logger.debug(f"Found specific hint for '{company_name}' based on the key '{key}'")  # noqa: G004
                return value  # Ritorna l'hint trovato

        return None  # No info found for this company

    def generate_web_scraping_prompt(self, company_name: str, source_type: str) -> str:
        """Generate a web scraping prompt based on the company name and source type."""
        return self.web_scraping_prompt_template.format(company_name=company_name, source_type=source_type)

    def call(self, prompt: str) -> str:
        """ "Call the model with retry logic for handling quota issues."""  # noqa: D210
        retries = 0
        max_retries = 5

        while retries < max_retries:
            response = None
            try:
                response = self.model.generate_content(prompt)
            except ResourceExhausted as e:
                logger.warning("Quota exceeded: %s", e.message)
                # Try to extract retry delay from exception, or default to 60 seconds
                delay = getattr(e, "retry_delay", 60)
                delay = delay.seconds if hasattr(delay, "seconds") else 60
                logger.info("Retrying in %d seconds... (attempt %d of %d)", delay, retries + 1, max_retries)
                time.sleep(delay)
            except Exception:
                logger.exception("Unhandled exception during model call")
                break

            if response:
                logger.info("Response received successfully.")
                return response

            retries += 1

        logger.error("Failed to get a response after %d retries.", max_retries)
        return None
