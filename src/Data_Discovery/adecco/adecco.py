import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Define the base URL
base_url = "https://www.adeccogroup.com"
url = f"{base_url}/investors/results-and-reports"

# Set headers to mimic a browser visit
headers = {"User-Agent": "Mozilla/5.0"}

# Send a GET request to the URL
response = requests.get(url, headers=headers)
response.raise_for_status()  # Raise an error for bad status codes

# Parse the HTML content
soup = BeautifulSoup(response.text, 'html.parser')


# Find the span with class "accordion-title" and text starting with "2023"
accordion_title = soup.find('span', class_='accordion-title', string=lambda text: text and '2023' in text)

# Alternative approach using more flexible matching
accordion_title = soup.find('span', class_='accordion-title')
if accordion_title and '2023' in accordion_title.text:
    print(accordion_title)
