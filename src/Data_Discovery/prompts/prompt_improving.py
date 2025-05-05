import json
def improve_prompt(self, company_name,current_prompt ,source_type, scraping_result, validation_result):
    """
    Generates an improvement prompt for optimizing the current prompt used in web scraping.

    Args:
        company_name (str): The name of the company.
        source_type (str): The type of source being scraped.
        scraping_result (dict): The result obtained from web scraping.
        validation_result (dict): The validation feedback on the scraping result.

    Returns:
        str: The improved prompt for web scraping.
    """
    
    # Constructing the improvement prompt
    return f"""
            You are an expert in prompt optimization for financial research.

            CONTEXT:
            - Company: {company_name}
            - Type of required source: {source_type}
            - Current prompt used:
            ```
            {current_prompt}
            ```

            - Web scraping result: {json.dumps(scraping_result, indent=2)}
            - Validation feedback: {json.dumps(validation_result, indent=2)}

            TASK:
            Improve the prompt to achieve more accurate results. The prompt should be optimized to:
            1. Find the direct URL to the most recent financial document
            2. Correctly identify the fiscal year
            3. Increase the precision and reliability of the results

            IMPORTANT:
            - Maintain the JSON structure of the response
            - Add specific instructions to overcome the identified issues
            - Do not completely change the prompt, but improve it incrementally

            RETURN ONLY THE NEW IMPROVED PROMPT, NOTHING ELSE.
            """