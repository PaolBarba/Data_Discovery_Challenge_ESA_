def generate_validation_prompt(company_name, source_type, url, year, source_description, confidence):
    return f"""
            You are an EXPERT VALIDATOR of financial sources for multinational companies.

            CONTEXT:
            - Company: {company_name}
            - Type of source requested: {source_type}

            RESULT TO VALIDATE:
            - URL: {url}
            - Fiscal year: {year}
            - Source description: {source_description}
            - Declared confidence level: {confidence}

            TASK:
            Evaluate the accuracy and reliability of this result. Consider:
            1. Does the URL appear to be an official source and directly point to the requested document?
            2. Is the fiscal year plausible and recent?
            3. Is the source appropriate for the requested type?

            RETURN YOUR EVALUATION IN THIS JSON FORMAT:
            {{
                "is_valid": true/false,
                "validation_score": 0-100,
                "feedback": "Detailed explanation of your evaluation",
                "improvement_suggestions": "Specific suggestions to improve the search"
            }}
            """