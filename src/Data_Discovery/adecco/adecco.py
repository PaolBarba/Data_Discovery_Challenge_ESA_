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
response.raise_for_status() 

# Parse the HTML content
soup = BeautifulSoup(response.text, 'html.parser')

section = soup.find("section", class_ = "p0 callout")

results_and_reports = section.find_all("div", class_=lambda x: x and "ResultsandReports" in x)

# Extract the links to the reports
links = []
for report in results_and_reports:
    results_and_reports2 = report.find("span", class_= lambda x: x and "accordion" in x)

print(results_and_reports2)