def generate_scraping_prompt(company_name: str) -> str:
    """
    Generates a prompt for web scraping financial data for a given company.

    Args:
        company_name (str): The name of the company to scrape data for.

    Returns
    -------
        str: The generated prompt for web scraping.
    """
    # Prompt template
    generating_prompt = f"""  Scrivi uno script Python completo per eseguire web scraping di dati finanziari per l'azienda {company_name}.

         REQUISITI:
         1. Lo script deve cercare e scaricare i seguenti dati finanziari (se disponibili):
            - Bilanci degli ultimi 3-5 anni
            - Report trimestrali
            - Dati di prezzo delle azioni
            - Indicatori finanziari chiave (P/E ratio, EPS, ecc.)

         2. Lo script deve:
            - Utilizzare requests e BeautifulSoup o Selenium dove appropriato
            - Avere gestione degli errori robusta
            - Salvare i dati in formato CSV e/o JSON
            - Essere ben commentato e seguire le best practice PEP 8
            - Gestire i rate limiting (attese tra le richieste)
            - Avere una classe principale chiamata '{company_name}Scraper'
            - Avere un metodo principale 'extract_data()' che restituisce un DataFrame pandas

         3. Possibili fonti di dati:
            - Sito ufficiale dell'azienda (sezione investor relations)
            - Yahoo Finance
            - MarketWatch
            - Altri siti finanziari pubblicamente accessibili

         4. Il codice deve essere completo e funzionante, non solo frammenti o pseudocodice.

         FORNISCI SOLO IL CODICE PYTHON, SENZA SPIEGAZIONI AGGIUNTIVE.
         """
    return generating_prompt
