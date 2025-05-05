# Financial Source Finder - README

This document briefly describes the main functions of the Python script for the automatic search of financial sources for multinational enterprises (MNEs).

## Project Objective

The script aims to automatically identify, for a provided list of companies:

1. The **direct URL** to the most recent and specific financial source (e.g., annual report PDF, SEC filing page).
2. The **fiscal year** associated with the retrieved data.

It uses an iterative approach that combines Web Scraping and AI model calls (Google Gemini) for search, validation, and automatic prompt optimization.

## Main Components (Classes)

The code is structured into the following main classes:

### `WebScraperModule`

- **Purpose:** Handle all web scraping operations.
- **Key Functions:** 
  - Find the company's official website.
  - Locate the "Investor Relations" (IR) page.
  - Extract links to financial reports (PDFs, etc.) from web pages.
  - Search for SEC filings (e.g., 10-K, 10-Q) on EDGAR.
  - Utilizes `requests` and `BeautifulSoup`, with retry handling and user-agent rotation.

### `PromptGenerator`

- **Purpose:** Dynamically create and optimize prompts sent to the AI for source searching.
- **Key Functions:** 
  - Generates the initial prompt based on a template and company-specific information (if available).
  - Iteratively modifies the prompt (`optimize_prompt`) based on feedback received from the `Validator`, asking another AI instance to suggest improvements.

### `Validator`

- **Purpose:** Assess the accuracy and specificity of the results (URL and year) returned by the search AI.
- **Key Functions:** 
  - Uses a specific “judge” prompt to ask Gemini whether the URL is correct, relevant, specific to the request, and whether the year is accurate and the most recent.
  - Provides structured feedback (`validate_result`) used for prompt optimization.

### `FinancialSourceFinder`

- **Purpose:** Orchestrate the entire workflow.
- **Key Functions:** 
  - Initializes the other modules.
  - Loads the list of companies from a CSV file.
  - Manages parallel execution (`run`, `ThreadPoolExecutor`) for each company (`process_company`).
  - Coordinates the search → validation → optimization loop.
  - Saves the final results (`save_results`) in a CSV file.

## General Workflow

For each company in the input list:

1. **(Setup):** An initial prompt is generated and preliminary scraping is performed to gather reference data.
2. **(Iterative Loop - max `N` times):**
   - **Search:** The AI (`gemini-pro`) is queried with the current prompt to find the URL and year.
   - **Parsing:** The AI’s JSON response is parsed.
   - **Validation:** If the AI returned a result, the `Validator` (a separate AI call) evaluates the result's quality:
     - Is the URL accessible?
     - Relevant?
     - Specific?
     - Is the year correct and recent?
   - **Decision:**
     - If **Validated**: The result is accepted and the loop stops for that company.
     - If **Not Validated**: The `PromptGenerator` uses the validator's feedback to ask the AI to *optimize* the prompt. The loop restarts from step (a) with the new prompt.
3. **(Output):** The result (validated or the latest obtained after N iterations) is saved along with the validation status, received feedback, and scraping data.
4. **(Final Save):** All results are consolidated and saved into a CSV file.

## Key Functions (Main Methods)

- `FinancialSourceFinder.run()`: Starts the entire process.
- `FinancialSourceFinder.process_company(company_data)`: Executes the complete cycle for a single company.
- `WebScraperModule.scrape_financial_sources(company_name, source_type)`: Main scraper function for finding URL/year.
- `PromptGenerator.generate_prompt(company_name, source_type)`: Creates/retrieves the search prompt.
- `PromptGenerator.optimize_prompt(...)`: Requests prompt optimization from the AI.
- `Validator.validate_result(...)`: Performs result validation through the "judge" AI.

## How to Run the Script

The script is executed from the command line:

```bash
python your_script_name.py <input_csv_path> [options]
