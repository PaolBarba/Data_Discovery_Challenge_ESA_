# Data Discovery Challenge - ESA

A modular pipeline for dataset discovery and submission, built for the European Space Agency's data challenge. This project integrates scraping, prompt engineering, model interaction, and a submission framework.

---

## 📁 Project Structure

```text

Data_Discovery_Challenge_ESA_/
├── src/
│   ├── Data_Discovery/
│   │   ├── cleaning/                   # Cleaning files
│   │   │   ├── cleaning.py
│   │   ├── config/                     # Configuration files
│   │   │   ├── data_preparation_config/
│   │   │   │   └── config.yaml
│   │   │   ├── model_config/
│   │   │   │   └── config.yaml
│   │   │   │   └── .env
│   │   │   ├── scraping_config/
│   │   │   │   └── config.yaml
│   │   │   └── submission_config/
│   │   │       └── config.yaml
│   │   ├── model/                      # Model scripts
│   │   │   ├── __init__.py
│   │   │   ├── prompt_generator.py
│   │   │   ├── prompt_tuner.py
│   │   │   └── result_validator.py
│   │   ├── notebooks/                  # Jupyter notebooks
│   │   │   └── eda.ipynb
│   │   ├── prompts/                    # Prompt engineering scripts
│   │   │   ├── __init__.py
│   │   │   ├── base_prompt.py
│   │   │   ├── prompt_improving.py
│   │   │   └── validation_prompt.py
│   │   ├── scraping/                   # Web scraping logic
│   │   │   ├── __init__.py
│   │   │   ├── financial_source_finder.py
│   │   │   ├── scraping_challenge.py
│   │   │   └── web_scarper.py
│   │   │   └── README.md
│   │   ├── submission/                 # Submission-related code
│   │   │   ├── __init__.py
│   │   │   ├── submission.py
│   │   ├── main.py                     # Main entry point
│   │   ├── submit.py                   # Submission script
│   │   └── utils.py                    # Shared utility functions
├── submission/                         # Submission files
│   ├── submission.csv                  # Submission CSV file
├── .gitignore
├── LICENSE                             # Project license
├── .gitlab-ci.yml                      # GitLab CI/CD configuration
├── .pre-commit-config.yaml             # Pre-commit configuration
├── CONTRIBUTING.md                     # Contribution guidelines
├── discovery_approach.docx             # Discovery approach documentation
├── LICENSE                             # Project license
├── pyproject.toml                      # Project metadata and dependencies
└── README.md                           # Project documentation

```



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
  - Utilizes `requests` and `BeautifulSoup`, with retry handling and user-agent rotation.

### `PromptGenerator`

- **Purpose:** Dynamically create and optimize prompts sent to the AI for source searching.
- **Key Functions:**
  - Generates the initial prompt based on a template and company-specific information (if available).
  - Iteratively modifies the prompt (`optimize_prompt`) based on feedback received from the `Validator`, asking another AI instance to suggest improvements.

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
     - **Case 1**: The url is valid -> Save in a specific Folder
     - **Case 2**: The url is not valid -> Re-Query the model with the errors
     If after some retry the url is not identified try another approach:
     - **Generate a Scraping Script with AI**: Not yet implemented
        It will query the model in order to generate a script to scrape financial data and save in the specific folder
    If after some retry the url is not valid try another approach:
    - **Naive search** Not yet implemented
   - **Parsing:** The AI’s JSON response is parsed.

   - **Validation:** If the AI returned a result
     - Is the URL accessible?
     - Relevant?
     - Specific?
     - Is the year correct and recent?
   - **Decision:**
     - If **Validated**: The result is accepted and the loop stops for that company.
     - If **Not Validated**: The `PromptGenerator` uses the validator's feedback to ask the AI to *optimize* the prompt. The loop restarts from step (a) with the new prompt.
3. **(Output):** The result (validated or the latest obtained after N iterations) is saved along with the validation status, received feedback, and scraping data.
4. **Generalization**: If more than one url is valid, generalize the code in order to give more than 1 ulr.
5. **(Final Save):** All results are consolidated and saved into a CSV file.
