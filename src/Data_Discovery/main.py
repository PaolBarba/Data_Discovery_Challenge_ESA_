import json
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import genai
import pandas as pd
from dotenv import load_dotenv
from model.prompt_tuner import PromptTuner
from model.result_validator import ResultValidator
from scraping.claude_challenge_code import WebScraperModule
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)



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
        "--input", default="dataset/discovery.csv", help="File CSV di input con lista di aziende"
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

