"""Financial Scraper Generator using Google Gemini API."""

import importlib.util
import logging
import os
import sys

# Add src folder to Python pathimport time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import google.generativeai as genai
import pandas as pd
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
load_dotenv(dotenv_path="src/Data_Discovery/config/.env")
API_KEY = os.environ.get("GOOGLE_API_KEY")


genai.configure(api_key=API_KEY)

class FinancialScraperGenerator:
    """Financial Scraper Class."""

    def __init__(self, csv_path: str, output_dir : str ="scrapers", data_dir: str ="financial_data"):
        """Init Class fot the Scraper Generator.

        Args:
            csv_path (str): Path for the csv file with all the company names
            output_dir (str, optional): Directory where to save the scripts. Defaults to "scrapers".
            data_dir (str, optional): Directory where to store the financial data. Defaults to "financial_data".
        """
        self.csv_path = csv_path
        self.output_dir = output_dir
        self.data_dir = data_dir

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    def load_companies(self) -> dict[str,str]:
        """Load the company names."""
        df = pd.read_csv(self.csv_path)

        # TODO the csv will be formatted so does not make sense to look for the name column
        company_names = df.iloc[:, 0].tolist() if "name" not in df.columns else df["name"].tolist()
        logger.info(f"Caricate {len(company_names)} aziende dal CSV")  # noqa: G004
        return company_names

    def generate_prompt(self, company_name: str) -> str:
        """
        It genereate a prompt fot the comany selected by using google gemini.

        Args:
            company_name (str): Nome dell'azienda.

        Returns
        -------
            str: Prompt da inviare a Gemini
        """  # noqa: D401
        return generate_scraping_prompt(company_name)

    def query_gemini(self, prompt:str) -> str:
        """
            Query the gemini AI.
        Args:
            prompt (str): Prompt to send.

        Returns
        -------
            str: Gemini Answer
        """  # noqa: D205
        try:
            # COnfigure the model
            model = genai.GenerativeModel("gemini-pro")
            # Invia la richiesta
            response = model.generate_content(prompt)
            # Get the full text
            result = response.text
            # if the answer contains the md code, extract it
            if "```python" in result:
                code_blocks = result.split("```python")
                if len(code_blocks) > 1:
                    return code_blocks[1].split("```")[0].strip()
            return result
        except Exception as e:
            logger.error(f"Errore durante la query a Gemini: {e}")
            return None

    def save_script(self, company_name: str, script_content: str)-> str | None:
        """
        Save the python script generate in a file.

        Args:
            company_name (str): Nome dell'azienda
            script_content (str): Contenuto dello script Python

        Returns
        -------
            str: Percorso dello script salvato
        """
        # Sostituisci spazi e caratteri speciali nel nome dell'azienda
        safe_name = "".join(c if c.isalnum() else "_" for c in company_name)
        file_path = os.path.join(self.output_dir, f"{safe_name}_scraper.py")  # noqa: PTH118

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            logger.info(f"Script per {company_name} salvato in {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Errore nel salvare lo script per {company_name}: {e}")
            return None

    def execute_script(self, script_path: str, company_name: str) -> pd.DataFrame | None:
        """
        Execute the script generated.

        Args:
            script_path (str): Path of the script to execute
            company_name (str): Nome dell'azienda

        Returns
        -------
            pd.DataFrame | None: DataFrame with the data
        """
        try:
            # Importa lo script dinamicamente
            spec = importlib.util.spec_from_file_location("scraper_module", script_path)
            scraper_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scraper_module)

            safe_name = "".join(c if c.isalnum() else "" for c in company_name)
            class_name = f"{safe_name}Scraper"

            # Look for the class into the script
            if hasattr(scraper_module, class_name):
                scraper_class = getattr(scraper_module, class_name)
                scraper = scraper_class()

                # Execute extracted data
                if hasattr(scraper, "extract_data"):
                    df = scraper.extract_data()

                    # Save the data
                    # TODO Classe save
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

    def process_company(self, company_name: str)-> tuple[str,pd.DataFrame]:
        """
        Execute the all pipeline to extract the company finanical Data.
        
        Args:
            company_name (str): Name of the company
            
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

    def run(self, max_workers: int = 4)-> dict[str, pd.DataFrame]:
        """
        Run the pipeline for all the companies
        
        Args:
            max_workers (int): Maximum number of threds to be used
            
        Returns:
            dict: Dictonary name of the company and dataframe.
        """
        # Carica le aziende
        company_names = self.load_companies()
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
    # if len(sys.argv) < 2:
    #     print("Utilizzo: python financial_scraper_generator.py percorso/al/file.csv [max_workers]")
    #     sys.exit(1)
    csv_path = "dataset\discovery.csv" # TODO: to be load from a yaml file.
    csv_path = sys.argv[1]
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    # Crea ed esegui il generatore
    generator = FinancialScraperGenerator(csv_path)
    results = generator.run(max_workers=max_workers)

    # Report finale
    print(":")
    print(f"- Company processed succesfully: {len(results)}")
    print(f"- Data save in the directory: {generator.data_dir}")
    print(f"- Script generati nella direttori: {generator.output_dir}")

# TODO: Basterebbe un solo script che generiamo e possiamo mettere il nome della company come varibile 
# TODO: Funzioni di load e save dovrebbero essere a parte.
# TODO: Add the financialscraper.log in a new folder
# TODO: Add a function that popolates the df to send as as output.
# TODO: The url with the financial data must be according with the reference year, wheter in the same step or in post processing by openin the file.
