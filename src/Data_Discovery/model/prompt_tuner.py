import json
import logging
import os
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
