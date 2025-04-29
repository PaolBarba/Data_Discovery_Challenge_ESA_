Script di Web Scraping Finanziario Automatizzato
Funzionamento dello Script
Questo script automatizza l'estrazione di dati finanziari da siti web aziendali. Ecco come funziona:
1. Input e Setup

Lo script accetta un file CSV contenente nomi di aziende
Utilizza Google Gemini API per generare script di web scraping personalizzati
Richiede una API key di Google Gemini impostata come variabile d'ambiente o direttamente nel codice

2. Processo principale
Per ogni azienda nel CSV, lo script:

Genera un prompt specifico che descrive i dati finanziari da estrarre (bilanci, report trimestrali, prezzi azioni, ecc.)
Invia il prompt a Google Gemini per ottenere uno script Python di web scraping personalizzato
Salva lo script nella directory scrapers/ con un nome basato sul nome dell'azienda
Esegue lo script dinamicamente per estrarre i dati finanziari
Salva i dati estratti in formato CSV nella directory financial_data/

3. Caratteristiche implementate

Multithreading: Elabora più aziende contemporaneamente (configurabile con max_workers)
Riutilizzo degli script: Se uno script per un'azienda esiste già, viene riutilizzato
Logging completo: Tutte le operazioni e gli errori sono registrati in un file di log
Gestione errori: Errori nelle API o nell'esecuzione degli script sono gestiti in modo sicuro

4. Utilizzo base
bashpython financial_scraper_generator.py percorso/al/file.csv [max_workers]
Dove:

percorso/al/file.csv: il file CSV contenente i nomi delle aziende
max_workers: (opzionale) il numero di thread paralleli da utilizzare (default: 4)

5. Struttura delle classi e metodi principali

FinancialScraperGenerator: Classe principale che gestisce l'intero processo

load_companies(): Carica i nomi delle aziende dal CSV
generate_prompt(): Crea il prompt per Gemini per una specifica azienda
query_gemini(): Interroga l'API di Gemini e ottiene lo script
save_script(): Salva lo script generato in un file
execute_script(): Esegue lo script e raccoglie i dati
process_company(): Gestisce l'intero flusso per una singola azienda
run(): Avvia l'elaborazione per tutte le aziende



6. Flusso dei dati
[File CSV] → [Estrazione nomi aziende] → [Generazione prompt] → [API Gemini] → 
[Script Python] → [Esecuzione script] → [Web scraping] → [Dati finanziari in CSV]
7. Requisiti tecnici

Python 3.8+
Librerie: pandas, requests, tqdm, google-generativeai
API key di Google Gemini
Connessione Internet

8. Considerazioni pratiche

Gli script generati effettueranno richieste a siti web finanziari, rispettando pause tra le richieste
Gli script includono gestione degli errori per problemi come cambiamenti nella struttura delle pagine
I dati estratti saranno in formato standardizzato, pronti per l'analisi predittiva

Per avviare lo script:
bash# Imposta la API key (sostituisci con la tua key)
export GOOGLE_API_KEY="your-api-key-here"

# Esegui lo script
python financial_scraper_generator.py companies.csv