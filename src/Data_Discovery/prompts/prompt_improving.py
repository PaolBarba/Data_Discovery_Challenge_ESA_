"""Prompt improving module for financial data scraping."""

improve_prompt = """The following URL returns a "Page Not Found" error: {report_url} for the company {company_name}.
This URL is supposed to contain the annual report or financial document for the company.
Please identify the correct or updated URL that provides the equivalent content. If the content has been
relocated, renamed, or archived, provide the most relevant and current URL from the official website.
Remember that the Response format must be:
RESPONSE FORMAT:

{{
    "url": "Direct URL to the financial document (not the page containing it)",
    "year": "Fiscal year of the report (YYYY)",
    "confidence": "HIGH/MEDIUM/LOW",
    "notes": "Brief explanation of your choice"
}}

IMPORTANT:
- Always prefer direct links to PDFs or specific documents
- The URL must be from the official website of the company
- The URL must be in English
- The URL must be riched in content and not a landing page or a search result
- Verify that the URL is accessible and does not require login
- Indicate the most recent available fiscal year
"""
