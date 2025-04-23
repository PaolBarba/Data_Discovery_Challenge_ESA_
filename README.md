# Starting Kit

This starting kit is here to help you with preparing the submission.zip file.

It contains the following files:

- This `README.md` file

- A `discovery.csv` file containing a sample of the discovery.csv file
  that you will have to submit

- A `discovery_approach_description.docx` file, used to describe the
  approach you used to generate the `discovery.csv` file

## Structure of the `submission.zip` file

The submission.zip file should only contain the following files:

```
submission.zip
├── discovery.csv
├── discovery_approach_description.docx
└── code.zip
```

Where the `code.zip` file contains the code used to generate the `discovery.csv`
file.

> NOTE: DO NOT CHANGE THE NAMES OF THE FILES OR THE STRUCTURE OF THE `submission.zip`
> FILE.

To compete for the Accuracy, Reusability and Innovativeness Awards, you need to submit the
`discovery.csv` file, the `discovery_approach_description.docx` file, and the `code.zip` file. All three files are required to compete for either of the awards.


## Structure of the `discovery.csv` file

The `discovery.csv` file should contain the following columns:

- `ID`: the technical ID of the Multinational Enterprise (MNE) group
- `NAME`: the name of the Multinational Enterprise (MNE) group
- `TYPE`: the type of the source (FIN_REP - financial report, OTHER - other)
- `SRC`: the source of the data in URL format
- `REFYEAR`: the reference year of the source

> NOTE: The `discovery.csv` file SHOULD contain the header.

The first three fields of the dataset - the ID, NAME and TYPE fields - will contain data while the last two fields (SRC and REFYEAR) will be empty placeholders – the challenge for the team is to populate them. Participants are required to develop a method which automatically identifies sources of annual financial data and provide up to 6 of these sources for each MNE Group along with the reference year.

Teams are required to identify sources of annual financial data and the reference year of the data for 200 MNE Group cases with unique technical IDs and NAMEs. Each ID appears in 6 consecutive rows.

- The 1st row must identify a source of the annual financial report for that MNE Group. The source (URL) identified as the financial report must point directly to the file of the report, i.e., when the URL is pasted on a browser, it must show the financial report (in .pdf or other format).

- The remaining 5 rows are used for the discovery and identification of other sources of financial data. A team can identify up to 5 other sources which contain annual financial data for that ID (MNE Group) case. Other sources are left to the discretion of the team, with the aim of discovering and identifying the most recent and valuable financial data. If no additional sources are identified, these rows remain empty.

- Relevant data which should be available in additional sources of financial data includes:

    - Country of the MNE Group (specifically, the country where the headquarter of the MNE Group is established).
    - Reference year T of financial data. Year T means the Financial Year for the purposes of which any calculation falls to be made.
    - Number of employees of the MNE Group worldwide for the reference year T.
    - Net Turnover of the MNE Group for the reference year T.
    - Total assets of the MNE group for reference year T.

- The teams are requested to automatically identify values for the SRC and REFYEAR columns. The other columns (ID, NAME, TYPE) should not be altered, this data is part of the template and provided for the teams.

- The REFYEAR indicated should be the year of the final month of the annual report or financial data and should be automatically extracted during the identification and discovery of financial data sources.
  - Examples:
    - For financial reports (TYPE: FIN_REP):
      - If the annual financial report is from Jan. 2022 – Dec. 2022, the REFYEAR is indicated as 2022.
      - If the annual financial report is from Nov. 2022 – Nov. 2023, the REFYEAR is indicated as 2023.
      - If the annual financial report is from Feb. 2023 – Feb. 2024, the REFYEAR is indicated as 2024.
    - For Other sources (TYPE: OTHER):
      - If the financial data is from Jan.2022-Dec.2022, the REFYEAR is indicated as 2022
      - Etc.