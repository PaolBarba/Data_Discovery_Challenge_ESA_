import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
from datetime import datetime
import pandas as pd

# Configuration
BASE_URL = "https://www.adeccogroup.com"
START_URL = f"{BASE_URL}/investors/results-and-reports"
OUTPUT_DIR = "adecco_reports"
MAX_RETRIES = 3
DELAY = 2  # seconds between requests

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_soup(url):
    """Fetch and parse a webpage with retries and delay."""
    for attempt in range(MAX_RETRIES):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            time.sleep(DELAY)  # Be polite
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(DELAY * 2)

def extract_report_links(soup):
    """Extract all report links from the page."""
    report_links = []
    
    # Look for common patterns in investor report pages
    selectors = [
        'a[href*="results"]', 
        'a[href*="report"]',
        'a[href*="presentation"]',
        'a[href*="financial"]',
        'a[href*="annual"]',
        'a[href*="quarterly"]',
        'a[href*="pdf"]',
        'a.document-link',
        'a.file-link'
    ]
    
    for selector in selectors:
        links = soup.select(selector)
        for link in links:
            href = link.get('href', '')
            if href and not href.startswith('javascript'):
                full_url = urljoin(BASE_URL, href)
                title = link.get_text(strip=True) or link.get('title', '') or href.split('/')[-1]
                report_links.append({
                    'title': title,
                    'url': full_url,
                    'element': str(link)[:100]  # For debugging selector effectiveness
                })
    
    return report_links

def extract_report_metadata(soup):
    """Extract metadata about reports if available."""
    metadata = []
    
    # Look for report cards or listings
    report_cards = soup.select('.report-card, .document-item, .results-item')
    
    for card in report_cards:
        try:
            title = card.select_one('.title, h3, h4').get_text(strip=True)
            date_element = card.select_one('.date, time, .document-date')
            date = date_element.get_text(strip=True) if date_element else ''
            
            # Try to parse date string into datetime object
            try:
                parsed_date = datetime.strptime(date, '%d %B %Y').strftime('%Y-%m-%d')
            except ValueError:
                parsed_date = date
            
            link = card.find('a')
            href = link.get('href') if link else ''
            full_url = urljoin(BASE_URL, href) if href else ''
            
            if full_url:
                metadata.append({
                    'title': title,
                    'date': parsed_date,
                    'url': full_url,
                    'type': 'PDF' if full_url.lower().endswith('.pdf') else 'Webpage'
                })
        except Exception as e:
            print(f"Error extracting metadata from card: {e}")
            continue
    
    return metadata

def download_pdf(url, filename):
    """Download a PDF file and save it locally."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def scrape_adecco_reports():
    """Main scraping function."""
    print(f"Starting scrape of {START_URL}")
    
    all_reports = []
    visited_urls = set()
    
    # First pass - get the main page
    soup = get_soup(START_URL)
    if not soup:
        print("Failed to fetch initial page")
        return
    
    # Extract links from main page
    report_links = extract_report_links(soup)
    metadata = extract_report_metadata(soup)
    
    print(f"Found {len(report_links)} links and {len(metadata)} metadata items on main page")
    
    # Combine and deduplicate
    combined = []
    url_set = set()
    
    for item in report_links + metadata:
        if item['url'] not in url_set:
            url_set.add(item['url'])
            combined.append(item)
    
    # Process each unique report
    for report in combined:
        try:
            url = report['url']
            if url in visited_urls:
                continue
                
            visited_urls.add(url)
            
            print(f"\nProcessing: {report.get('title', url)}")
            
            # Handle PDFs
            if url.lower().endswith('.pdf'):
                filename = os.path.join(OUTPUT_DIR, url.split('/')[-1])
                if not os.path.exists(filename):
                    print(f"Downloading PDF: {url}")
                    success = download_pdf(url, filename)
                    report['downloaded'] = success
                else:
                    print("PDF already downloaded")
                    report['downloaded'] = True
            else:
                # Follow links to potentially find more resources
                print(f"Following link: {url}")
                sub_soup = get_soup(url)
                if sub_soup:
                    sub_links = extract_report_links(sub_soup)
                    for sub_link in sub_links:
                        sub_url = sub_link['url']
                        if sub_url not in visited_urls and sub_url.lower().endswith('.pdf'):
                            visited_urls.add(sub_url)
                            filename = os.path.join(OUTPUT_DIR, sub_url.split('/')[-1])
                            if not os.path.exists(filename):
                                print(f"Downloading sub-PDF: {sub_url}")
                                success = download_pdf(sub_url, filename)
                                sub_link['downloaded'] = success
                                combined.append(sub_link)
            
            all_reports.append(report)
            
        except Exception as e:
            print(f"Error processing {report.get('url', 'unknown')}: {e}")
    
    # Save metadata to CSV
    df = pd.DataFrame(all_reports)
    csv_path = os.path.join(OUTPUT_DIR, 'adecco_reports_metadata.csv')
    df.to_csv(csv_path, index=False)
    print(f"\nScraping complete. Metadata saved to {csv_path}")
    
    return df

# Run the scraper
if __name__ == "__main__":
    report_data = scrape_adecco_reports()
    if report_data is not None:
        print("\nSummary of collected reports:")
        print(report_data[['title', 'date', 'url', 'downloaded']].head())