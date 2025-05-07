"""Main script to run the entire pipeline."""

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
from scraping.financial_source_finder import FinancialSourcesFinder
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("financial_sources_finder.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


financial_sources_finder = FinancialSourcesFinder()


def main():
    """Run the financial sources finder."""
    import argparse

    parser = argparse.ArgumentParser(description="Find financial sources for multinational companies")
    parser.add_argument("--input", default="dataset/discovery.csv", help="Input CSV file with a list of companies")
    parser.add_argument("--output", default="financial_sources_results.csv", help="Output CSV file")
    parser.add_argument("--source-type", default="Annual Report", help="Type of financial source to search for")
    parser.add_argument("--api-key", help="Gemini API key (optional if set as an environment variable)")
    parser.add_argument("--threads", type=int, default=4, help="Number of threads for parallel processing")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for processing")
    parser.add_argument("--validation-threshold", type=int, default=80, help="Validation threshold (0-100)")
    parser.add_argument("--max-tuning", type=int, default=3, help="Maximum number of tuning iterations")

    args = parser.parse_args()

    # Configure the API key if provided
    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("Gemini API key not provided. Set GOOGLE_API_KEY or use --api-key")
        sys.exit(1)

    # Load the input CSV
    try:
        df = pd.read_csv(args.input, sep=";")
        if "NAME" not in df.columns:
            # Try using the first column as the company name
            company_column = df.columns[0]
            df = df.rename(columns={company_column: "NAME"})
            logger.warning(f"Column 'NAME' not found, using '{company_column}' instead")
    except Exception as e:
        logger.error(f"Error loading the CSV: {e}")
        sys.exit(1)

    # Initialize the finder
    finder = FinancialSourcesFinder(
        api_key=api_key, max_tuning_iterations=args.max_tuning, validation_threshold=args.validation_threshold
    )

    # Prepare batches of companies
    companies = df["NAME"].tolist()
    batches = [companies[i : i + args.batch_size] for i in range(0, len(companies), args.batch_size)]

    # Process batches in parallel
    all_results = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = []
        for batch in batches:
            future = executor.submit(
                financial_sources_finder.process_companies_batch(
                    companies_batch=batch,
                    source_type=args.source_type,
                    finder=finder,
                )
            )
            futures.append(future)

        # Show a progress bar
        for future in tqdm(futures, desc="Processing batches", unit="batch"):
            batch_results = future.result()
            all_results.extend(batch_results)

    # Convert results to DataFrame
    results_df = pd.DataFrame(all_results)

    # Save the results
    results_df.to_csv(args.output, index=False)
    logger.info(f"Results saved to {args.output}")

    # Print statistics
    valid_results = results_df[results_df["is_valid"] == True]
    logger.info(f"Total companies processed: {len(results_df)}")
    logger.info(f"Valid results: {len(valid_results)} ({len(valid_results)/len(results_df)*100:.1f}%)")

    # Save a detailed JSON report
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
    logger.info(f"Detailed report saved to {report_path}")


if __name__ == "__main__":
    main()
