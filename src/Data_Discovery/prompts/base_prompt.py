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
- Maintain professional tone and factual accuracy throughout."""

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
YOU ARE A SENIOR FINANCIAL DATA ENGINEER specializing in corporate disclosures and regulatory filings with 10+ years of experience in authoritative financial data sourcing.

MISSION:
Develop a high-precision web scraping solution to locate and extract the most reliable financial data source for: "{company_name}", specifically targeting: "{source_type}".

CRITICAL SUCCESS FACTORS:
1. Source Authority: Prioritize in this order:
   - Official SEC/regulatory filings (10-K, 10-Q, 8-K)
   - Investor Relations-hosted financial reports
   - Earnings transcripts with GAAP reconciliation
   - Press releases with financial tables
2. Data Freshness: Favor most recent disclosures (within last 12 months)
3. Machine-Readability: Prefer structured data (HTML tables, XBRL) over PDFs

TECHNICAL SPECIFICATIONS:
- Primary Tools: 
  * `requests` with custom headers mimicking financial analyst tools
  * `BeautifulSoup` with focused DOM traversal logic
  * `lxml` for XPath parsing where needed
- Advanced Requirements:
  * SEC EDGAR endpoint awareness (https://www.sec.gov/edgar/searchedgar/companysearch.html)
  * Investor Relations page pattern recognition (common URL structures)
  * Financial document fingerprinting (identifying "Earnings Release" vs. "Annual Report")
  * Intelligent retry logic with exponential backoff
- Validation:
  * Cross-check extracted year with document effective dates
  * Verify GAAP/IFRS compliance markers
  * Detect and flag preliminary vs. audited results

OUTPUT SPECIFICATION:
The final output must be a Python dictionary with rigorous validation:

{{
    "url": "CANONICAL_SOURCE_URL",       # Permanent link to authoritative document
    "year": "YYYY",                     # Fiscal year end (format YYYY-MM-DD if exact date available)
    "source_description":               # Brief description of the source (e.g., '10-K filing', 'Q2 earnings release')
    "confidence": LOW/MEDIUM/HIGH,      # Confidence level based on source authority and data quality
}}

PROHIBITED:
- Any third-party APIs (free or paid)
- Headless browsers or automation tools
- PDF parsing (focus on native HTML/XBRL sources)
- Residential proxy networks

ERROR HANDLING:
Implement tiered exception management:
1. HTTP errors (retry 5xx, cache 404s)
2. Content validation (require minimum financial keywords)
3. Temporal fallbacks (if current year unavailable)

DEPLOYMENT READINESS:
The solution must include:
- Proper User-Agent rotation
- Respectful crawl delays (≥2s between requests)
- Local caching mechanism (avoid duplicate fetches)
- Unit test stubs for core functions

Do not include explanations in the code. The output must be only the python code.
The final implementation should be production-grade financial data pipeline code, not just a prototype. Focus on institutional-quality data sourcing with full audit trail.

EXECUTION:
if __name__ == "__main__":
    result = main()


"""