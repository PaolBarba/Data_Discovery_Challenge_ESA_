import json
import logging
import os
import re
import sys
from datetime import datetime

import genai
from dotenv import load_dotenv

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

