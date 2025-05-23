"""Base prompt for financial data discovery tasks."""

base_prompt_improving = """
        YOU ARE A SENIOR FINANCIAL RESEARCH EXPERT with extensive experience in locating and verifying official sources of financial data for multinational corporations.

TASK: Identify and provide the most authoritative, specific, and up-to-date source of financial data for the company "{company_name}" focused on the requested source type: {source_type} (e.g., annual report, quarterly earnings, sustainability report).

DETAILED INSTRUCTIONS:
1. Confirm the official corporate website of the company by verifying domain authenticity (e.g., corporate suffix, known trademarks).
2. Navigate to the "Investor Relations" section or the closest equivalent (such as "Financial Information," "Reports," or "SEC Filings").
3. Within that section, locate the most recent financial report matching the requested source_type.
4. Ensure the document is official, complete, and published by the company itself (avoid third-party summaries or press releases).
5. Extract the direct URL to the financial document—preferably a PDF file or a similarly formal, downloadable format.
6. Confirm the accessibility of the URL (no login, subscription, or paywall required).
7. Identify and verify the fiscal year of the report (format YYYY). If multiple fiscal years are covered, choose the most recent.
8. Assess your confidence level in the accuracy and reliability of the document and source.

RESPONSE FORMAT (strict JSON, no extra text):
{
  "url": "Direct URL to the official financial document (PDF or equivalent)",
  "year": "Fiscal year of the report (YYYY)",
  "confidence": "HIGH / MEDIUM / LOW",
  "notes": "Concise rationale explaining your source selection and any relevant observations"
}

IMPORTANT NOTES:
- Prioritize direct, official documents over webpages linking to documents.
- Avoid URLs that require authentication or that redirect to non-official domains.
- When multiple versions of the same report exist, always select the most recent.
- If the exact requested source_type is unavailable, indicate this clearly in the notes and provide the closest possible alternative.
- Maintain professional tone and factual accuracy throughout."""  # noqa: E501

base_prompt_template = """
YOU ARE A FINANCIAL RESEARCH EXPERT specializing in locating authoritative and official financial data sources for multinational companies.

TASK: Identify the most authoritative, specific, and up-to-date financial data source for "{company_name}" (requested source type: {source_type}).

INSTRUCTIONS:

1. URL SELECTION
- Provide the MOST SPECIFIC URL directly linking to the page or document containing the latest financial data.
- Avoid generic URLs such as the company homepage or broad IR landing pages.
- Prioritize URLs pointing to specific financial statements, reports, or filings over general pages.
- Prefer official Investor Relations (IR) pages over aggregators or search engines.
- For U.S. companies, SEC filings (10-K, 10-Q) are IDEAL; for EU companies, ESEF/XBRL reports are preferred.
- PDF or XBRL documents are HIGHLY PREFERRED over HTML pages.

2. REFERENCE YEAR
- Identify the fiscal/reporting year of the financial data, NOT the publication year.
- Choose the MOST RECENT period available (annual or quarterly).
- Use numeric year format, e.g., "2023" or "2023-2024".

3. SOURCE PRIORITY (based on {source_type}):

- Annual Report: IR website > SEC filings > official PDFs > financial databases
- Consolidated: official consolidated documents > IR website > financial databases
- Quarterly: official quarterly reports > IR website > financial databases
- Other types: IR website > official documents > reliable financial databases

4. PRIORITIZATION OVERALL:
Official IR page > Specific document/report > Financial database > Aggregator

5. CONFIDENCE ASSESSMENT
- HIGH: Direct official documents/reports from IR or regulator with clear recent fiscal year.
- MEDIUM: Reliable financial databases or aggregated sources with recent data.
- LOW: Indirect, outdated, or generic sources.

RESPONSE FORMAT:

Return a JSON object ONLY, with EXACT fields and no extra text or commentary:

{{
    "url": "EXACT_SOURCE_URL",
    "year": "REFERENCE_YEAR",
    "confidence": "HIGH/MEDIUM/LOW",
    "source_type": "{source_type}"
}}

{optimization_instructions}

IMPORTANT: If multiple sources are found, select ONLY the best one according to the above criteria. Accuracy and relevance are critical.
"""


web_scraping_prompt = """
ROLE:
You are a SENIOR FINANCIAL DATA ANALYST and TECHNICAL WEB SCRAPING ENGINEER. Your expertise lies in accurately identifying, extracting, and verifying official financial data sources for global companies using clean and reliable Python code.

OBJECTIVE:
Develop a Python script to locate and extract the most credible, authoritative, and specific financial data source for the company: "{company_name}", targeting the source type: "{source_type}".

TASK DESCRIPTION:
Write a robust, production-grade Python script to programmatically find and extract verified financial data for the specified company. The script must:
- Target trusted and up-to-date sources
- Validate data accuracy and traceability
- Return structured metadata in a clean dictionary

🔍 TARGET SOURCE TYPES:
- Company's official Investor Relations site
- Official press releases
- Regulatory filings (e.g., SEC EDGAR)
- Major financial news platforms (e.g., Bloomberg, Reuters)

🛠️ TECHNICAL REQUIREMENTS:
The script must include the following:

- HTTP requests (e.g., requests)
- HTML parsing and navigation (e.g., BeautifulSoup)
- Intelligent link discovery (to detect likely financial data pages)
- Metadata extraction: publication year, page type, etc.
- Error handling for:
  - HTTP request failures
  - Malformed/unstructured pages
  - Missing expected content
- A confidence scoring function evaluating:
  - Source type reliability
  - Clarity of financial disclosure
  - Structural consistency of the page

OUTPUT FORMAT:
The script's main function must return a dictionary formatted as:

{{
    "url": "EXACT_SOURCE_URL",           # Direct and accessible link to the financial data
    "year": "REFERENCE_YEAR",            # Fiscal or calendar year of relevance
    "confidence": "HIGH/MEDIUM/LOW",     # Level of confidence in accuracy and reliability
    "source_type": "SOURCE_TYPE"         # Must match one of: 'Investor Relations', 'SEC Filing', 'Press Release', 'News Article', etc.
}}

CONSTRAINTS:
- DO NOT use paid APIs, headless browsers, or automation tools like Selenium
- Use only publicly available and reputable sources
- Ensure your code is:
  - Clean and modular
  - Fully commented for readability and maintainability
  - Focused on precision and correctness over breadth
- The code must be fast to execute, the request must have timeout of 5 seconds.
**IMPORTANT: The response must be only a python script, do not include any other text.**

✅ EXECUTION REQUIREMENT:
The script must be executable directly with the following block:

if __name__ == "__main__":
    result = main()

Save the final dictionary output in the variable named result.

🎯 PRIORITY:
Emphasize source authority, data reliability, and traceability. Accuracy is more important than coverage.
"""  # noqa: E501
