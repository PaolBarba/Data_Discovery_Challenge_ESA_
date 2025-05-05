# Financial Source Finder - README

Questo documento descrive brevemente le funzioni principali dello script Python per la ricerca automatica di fonti finanziarie di aziende multinazionali (MNE).

## Obiettivo del Progetto

Lo script mira a identificare automaticamente, per un elenco di aziende fornito in input:
1.  L'**URL diretto** alla fonte finanziaria più recente e specifica (es. report annuale PDF, pagina filing SEC).
2.  L'**anno fiscale di riferimento** dei dati trovati.

Utilizza un approccio iterativo che combina Web Scraping, chiamate a modelli AI (Google Gemini) per ricerca, validazione e ottimizzazione automatica dei prompt.

## Componenti Principali (Classi)

Il codice è strutturato nelle seguenti classi principali:

1.  `WebScraperModule`:
    * **Scopo:** Gestire tutte le operazioni di web scraping.
    * **Funzioni Chiave:** Trovare il sito web ufficiale dell'azienda, localizzare la pagina "Investor Relations" (IR), estrarre link a report finanziari (PDF, etc.) da pagine web, cercare filing SEC (es. 10-K, 10-Q) su EDGAR. Utilizza `requests` e `BeautifulSoup`, con gestione di retry e user-agent rotation.

2.  `PromptGenerator`:
    * **Scopo:** Creare e ottimizzare dinamicamente i prompt inviati all'AI per la ricerca delle fonti.
    * **Funzioni Chiave:** Genera il prompt iniziale basato su un template e informazioni specifiche dell'azienda (se note). Modifica iterativamente il prompt (`optimize_prompt`) basandosi sul feedback ricevuto dal `Validator`, chiedendo a un'altra istanza AI di suggerire miglioramenti.

3.  `Validator`:
    * **Scopo:** Valutare l'accuratezza e la specificità dei risultati (URL e anno) forniti dall'AI di ricerca.
    * **Funzioni Chiave:** Utilizza un prompt specifico ("giudice") per chiedere a Gemini di valutare se l'URL è corretto, pertinente, specifico per la richiesta e se l'anno è accurato e il più recente. Fornisce un feedback strutturato (`validate_result`) usato per l'ottimizzazione del prompt.

4.  `FinancialSourceFinder`:
    * **Scopo:** Orchestare l'intero flusso di lavoro.
    * **Funzioni Chiave:** Inizializza gli altri moduli, carica l'elenco delle aziende dal CSV, gestisce l'esecuzione parallela (`run`, `ThreadPoolExecutor`) per ogni azienda (`process_company`), coordina il ciclo di ricerca -> validazione -> ottimizzazione, e salva i risultati finali (`save_results`) in un file CSV.

## Flusso di Lavoro Generale

Per ogni azienda nell'elenco di input:
1.  **(Setup):** Viene generato un prompt iniziale e viene eseguito uno scraping preliminare per avere dati di riferimento.
2.  **(Ciclo Iterativo - max `N` volte):**
    a.  **Ricerca:** L'AI (`gemini-pro`) viene interrogata con il prompt corrente per trovare URL e anno.
    b.  **Parsing:** La risposta JSON dell'AI viene analizzata.
    c.  **Validazione:** Se l'AI ha fornito un risultato, il `Validator` (un'altra chiamata AI) giudica la qualità del risultato (URL accessibile? Pertinente? Specifico? Anno corretto e recente?).
    d.  **Decisione:**
        * Se **Validato**: Il risultato viene accettato, il ciclo si interrompe per questa azienda.
        * Se **Non Validato**: Il `PromptGenerator` usa il feedback del validatore per chiedere all'AI di *ottimizzare* il prompt. Il ciclo ricomincia dal punto (a) con il nuovo prompt.
3.  **(Output):** Il risultato (validato o l'ultimo ottenuto dopo N iterazioni) viene salvato insieme allo stato di validazione, al feedback ricevuto e ai dati di scraping.
4.  **(Salvataggio Finale):** Tutti i risultati vengono consolidati e salvati in un file CSV.

## Funzioni Chiave (Metodi Principali)

* `FinancialSourceFinder.run()`: Avvia l'intero processo.
* `FinancialSourceFinder.process_company(company_data)`: Esegue il ciclo completo per una singola azienda.
* `WebScraperModule.scrape_financial_sources(company_name, source_type)`: Funzione principale dello scraper per trovare URL/anno.
* `PromptGenerator.generate_prompt(company_name, source_type)`: Crea/recupera il prompt per la ricerca.
* `PromptGenerator.optimize_prompt(...)`: Richiede l'ottimizzazione del prompt all'AI.
* `Validator.validate_result(...)`: Esegue la validazione del risultato tramite AI "giudice".

## Come Eseguire lo Script

Lo script viene eseguito da riga di comando:

```bash
python tuo_nome_script.py <percorso_csv_input> [opzioni]
