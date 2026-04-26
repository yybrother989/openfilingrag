# Sample filings

Drop a real 10-K, 10-Q, annual report, or earnings document into this
directory and run `make ingest-sample`.

## Supported formats

| Extension | Parser | Notes |
|---|---|---|
| `.pdf`    | PyMuPDF + pdfplumber | Page-aware; tables extracted with pdfplumber |
| `.html` / `.htm` | BeautifulSoup (`lxml`) | Strips nav/footer chrome; treated as one logical page |
| `.txt`    | Plain text | Single page; whole file ingested |

Only the **first** file (alphabetically) found here is ingested by
`make ingest-sample`. Use `--path` to override:

```bash
python -m scripts.ingest_sample --path /absolute/path/to/some-10k.pdf \
    --ticker MSFT --company "Microsoft Corporation" \
    --fiscal-year 2024 --filing-date 2024-08-01
```

## Where to get real filings

* SEC EDGAR full-text search: <https://efts.sec.gov/LATEST/search-index?q=>
* Direct 10-K HTML: e.g. Apple — <https://www.apple.com/investor/>
* Investor-relations PDFs from any public company

## Privacy

This folder is git-ignored (`.gitignore` excludes everything except this
README) so your downloaded filings stay local.

## Mock fallback

If the directory is empty, `scripts/ingest_sample.py` writes a tiny
synthetic 10-K (`synthetic_10k.txt`) and ingests that instead. Useful for
zero-config demos but **not** representative of real-world filing structure.
