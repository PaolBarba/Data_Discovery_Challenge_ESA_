"""Financial Scraper Generator using Google Gemini API."""

import importlib.util
import json
import logging
import os
import sys

# Add src folder to Python pathimport time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import google.generativeai as genai
import pandas as pd
import requests
from dotenv import load_dotenv
from generating_prompt import generate_scraping_prompt
from tqdm import tqdm

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("financial_scraper.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

env_path = Path(__file__).parent / ".env"


if env_path.exists():
    load_dotenv(env_path)
else:
    logger.error(f"File .env non trovato in {env_path}")  # noqa: G004

API_KEY = os.environ.get("GOOGLE_API_KEY")  # Inserisci la tua API key se non è impostata come variabile d'ambiente

genai.configure(api_key=API_KEY)

class FinancialScraperGenerator:
    def __init__(self, csv_path, output_dir="scrapers", data_dir="financial_data"):
        """
        Inizializza il generatore di scraper finanziari.

        Args:
            csv_path (str): Percorso al file CSV contenente i nomi delle aziende
            output_dir (str): Directory dove salvare gli script di scraping generati
            data_dir (str): Directory dove salvare i dati finanziari estratti
        """
        self.csv_path = csv_path
        self.output_dir = output_dir
        self.data_dir = data_dir

        # Crea le directory se non esistono
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        
    def load_companies(self):
        """Carica i nomi delle aziende dal CSV"""
        try:
            df = pd.read_csv(self.csv_path)
            if "name" not in df.columns:
                # Se non esiste una colonna "name", usa la prima colonna disponibile
                company_names = df.iloc[:, 0].tolist()
                logger.warning(f"Colonna 'name' non trovata, utilizzando la prima colonna: {df.columns[0]}")
            else:
                company_names = df["name"].tolist()
            
            logger.info(f"Caricate {len(company_names)} aziende dal CSV")
            return company_names
        except Exception as e:
            logger.error(f"Errore durante il caricamento del CSV: {e}")
            return []

    def generate_prompt(self, company_name):
        """
        Genera un prompt per Gemini per creare uno script di web scraping per l'azienda specificata.

        Args:
            company_name (str): Nome dell'azienda

        Returns
        -------
            str: Prompt da inviare a Gemini
        """
        return generating_prompt(company_name)

    
    def query_gemini(self, prompt):
        """
        Invia un prompt a Google Gemini e ottiene la risposta
        
        Args:
            prompt (str): Prompt da inviare
            
        Returns:
            str: Risposta di Gemini
        """
        try:
            # Configura il modello
            model = genai.GenerativeModel('gemini-pro')
            
            # Invia la richiesta
            response = model.generate_content(prompt)
            
            # Estrai il testo della risposta
            result = response.text
            
            # Se la risposta contiene blocchi di codice con markdown, estraiamo solo il codice
            if "```python" in result:
                code_blocks = result.split("```python")
                if len(code_blocks) > 1:
                    code = code_blocks[1].split("```")[0].strip()
                    return code
            
            return result
        except Exception as e:
            logger.error(f"Errore durante la query a Gemini: {e}")
            return None
    
    def save_script(self, company_name, script_content):
        """
        Salva lo script generato su file
        
        Args:
            company_name (str): Nome dell'azienda
            script_content (str): Contenuto dello script Python
            
        Returns:
            str: Percorso dello script salvato
        """
        # Sostituisci spazi e caratteri speciali nel nome dell'azienda
        safe_name = ''.join(c if c.isalnum() else '_' for c in company_name)
        file_path = os.path.join(self.output_dir, f"{safe_name}_scraper.py")
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            logger.info(f"Script per {company_name} salvato in {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Errore nel salvare lo script per {company_name}: {e}")
            return None
    
    def execute_script(self, script_path, company_name):
        """
        Esegue lo script di scraping generato
        
        Args:
            script_path (str): Percorso allo script da eseguire
            company_name (str): Nome dell'azienda
            
        Returns:
            pd.DataFrame: DataFrame con i dati estratti o None in caso di errore
        """
        try:
            # Importa lo script dinamicamente
            spec = importlib.util.spec_from_file_location("scraper_module", script_path)
            scraper_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scraper_module)
            
            # Ottieni il nome della classe principale (assumendo che segua la convenzione)
            safe_name = ''.join(c if c.isalnum() else '' for c in company_name)
            class_name = f"{safe_name}Scraper"
            
            # Cerca la classe nello script
            if hasattr(scraper_module, class_name):
                scraper_class = getattr(scraper_module, class_name)
                scraper = scraper_class()
                
                # Esegui il metodo di estrazione dati
                if hasattr(scraper, "extract_data"):
                    df = scraper.extract_data()
                    
                    # Salva i dati
                    output_path = os.path.join(self.data_dir, f"{safe_name}_financial_data.csv")
                    df.to_csv(output_path, index=False)
                    logger.info(f"Dati per {company_name} salvati in {output_path}")
                    
                    return df
                else:
                    logger.error(f"Il metodo extract_data() non trovato nello script per {company_name}")
            else:
                logger.error(f"Classe {class_name} non trovata nello script per {company_name}")
        except Exception as e:
            logger.error(f"Errore nell'esecuzione dello script per {company_name}: {e}")
        
        return None
    
    def process_company(self, company_name):
        """
        Processa una singola azienda: genera il prompt, ottiene lo script,
        lo salva ed esegue il web scraping
        
        Args:
            company_name (str): Nome dell'azienda
            
        Returns:
            tuple: (nome_azienda, dataframe) con i dati estratti o None
        """
        logger.info(f"Elaborazione dell'azienda: {company_name}")
        
        try:
            # Controlla se esiste già uno script per questa azienda
            safe_name = ''.join(c if c.isalnum() else '_' for c in company_name)
            existing_script_path = os.path.join(self.output_dir, f"{safe_name}_scraper.py")
            
            if not os.path.exists(existing_script_path):
                # Genera il prompt
                prompt = self.generate_prompt(company_name)
                
                # Ottieni lo script da Gemini
                logger.info(f"Richiesta a Gemini per {company_name}...")
                script_content = self.query_gemini(prompt)
                
                if not script_content:
                    logger.error(f"Nessuno script generato per {company_name}")
                    return company_name, None
                
                # Salva lo script
                script_path = self.save_script(company_name, script_content)
            else:
                logger.info(f"Script esistente trovato per {company_name}")
                script_path = existing_script_path
            
            if script_path:
                # Esegui lo script
                logger.info(f"Esecuzione script per {company_name}...")
                df = self.execute_script(script_path, company_name)
                return company_name, df
            
        except Exception as e:
            logger.error(f"Errore durante l'elaborazione di {company_name}: {e}")
        
        return company_name, None
    
    def run(self, max_workers=4):
        """
        Esegue il processo completo per tutte le aziende
        
        Args:
            max_workers (int): Numero massimo di thread da utilizzare
            
        Returns:
            dict: Dizionario {nome_azienda: dataframe} con i dati estratti
        """
        # Carica le aziende
        company_names = self.load_companies()
        if not company_names:
            logger.error("Nessuna azienda trovata nel CSV")
            return {}
        
        results = {}
        
        # Processa le aziende in parallelo
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.process_company, name) for name in company_names]
            
            for future in tqdm(futures, desc="Elaborazione aziende", total=len(company_names)):
                company_name, df = future.result()
                if df is not None:
                    results[company_name] = df
        
        logger.info(f"Elaborazione completata. {len(results)}/{len(company_names)} aziende processate con successo.")
        return results

if __name__ == "__main__":
    # Controlla se l'API key è stata impostata
    if not API_KEY:
        print("ERRORE: API_KEY non impostata. Imposta la variabile d'ambiente GOOGLE_API_KEY o inseriscila direttamente nello script.")
        sys.exit(1)
    
    # Verifica che il percorso del CSV sia fornito come argomento
    if len(sys.argv) < 2:
        print("Utilizzo: python financial_scraper_generator.py percorso/al/file.csv [max_workers]")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    
    # Crea ed esegui il generatore
    generator = FinancialScraperGenerator(csv_path)
    results = generator.run(max_workers=max_workers)
    
    # Report finale
    print("\nRiepilogo:")
    print(f"- Aziende processate con successo: {len(results)}")
    print(f"- Dati salvati nella directory: {generator.data_dir}")
    print(f"- Script generati nella directory: {generator.output_dir}")