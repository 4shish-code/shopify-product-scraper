# shopscrape

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Shopify Compatibility](https://img.shields.io/badge/Shopify-57--Column%20Import%20Ready-96bf48.svg)](https://help.shopify.com/en/manual/products/import-export/using-csv)
[![CLI](https://img.shields.io/badge/CLI-shopctl-informational.svg)](#cli-reference)

A high-performance CLI utility and Python package to extract product catalogs from public Shopify storefronts and export them directly into Shopify-compatible import CSV files (57-column modern template), Excel spreadsheets (`.xlsx`), or JSON.

---

## Features

- **Shopify 57-Column Import Compatibility**: Generates structured CSVs matching Shopify's modern product import specification byte-for-byte.
- **Variant and Image Expansion**: Accurately maps product options (Size, Color, Material), prices, SKUs, barcodes, and secondary gallery images via Shopify handle continuations.
- **Adaptive Rate Limiting & Backoff**: Exponential backoff with jitter and `Retry-After` header support for non-disruptive, polite scraping.
- **Local SQLite Storage**: Stores extracted catalogs locally to enable fast querying, filtering, transformations, and offline re-exporting.
- **Price History & Diff Tracking**: Detects price changes between scrape runs across variants (`shopctl diff`).
- **Data Transformation Pipeline**: Supports custom price multipliers, price rounding rules (`.99`, `9`, `10`), vendor overrides, tag injection, and custom publish states (`Draft` / `Active`).
- **Multi-Format Export Engine**: Exports to Shopify 57-column CSV, Shopify legacy CSV, flat analytics sheets for Excel, or raw JSON.

---

## Requirements & Installation

Requires **Python 3.10** or newer.

```bash
# Clone the repository
git clone https://github.com/4shish-code/shopify-product-scraper.git
cd shopify-product-scraper

# Install dependencies
pip install -r requirements.txt
```

To install as a system-wide executable:
```bash
pip install -e .
```

---

## Quickstart

### 1. Verify store connectivity
```bash
./shopctl doctor
```

### 2. Scrape storefront catalogs
```bash
# Scrape a single store
./shopctl scrape --site bobogears

# Scrape all configured stores
./shopctl scrape all
```

### 3. Export to CSV

Export separate CSV files for each store (ready for Shopify import):
```bash
./shopctl export all --split-by-site --status Draft
```

Export a specific store:
```bash
./shopctl export --site bobogears
```

Files are saved in the `exports/` directory.

To import into Shopify:
> **Shopify Admin** -> **Products** -> **Import** -> Upload CSV.

---

## CLI Reference

### Site Registry (`sites`)

```bash
# List registered stores and cached product counts
./shopctl sites list

# Register a new store (validates Shopify compatibility)
./shopctl sites add example.com

# Register store with collection-specific targeting
./shopctl sites add example.com --key example --collection helmets --collection accessories

# Inspect collections on a remote store
./shopctl sites collections bobogears

# Update site parameters
./shopctl sites set bobogears --vendor "Custom Brand" --add-tag imported
./shopctl sites set mototorque --disable

# Unregister a store
./shopctl sites remove example.com --purge
```

---

### Catalog Extraction (`scrape`)

```bash
# Scrape all active stores
./shopctl scrape all

# Scrape selected stores
./shopctl scrape --site fleettrack --site bobogears

# Test run with sample limit and dry-run mode
./shopctl scrape all --limit 10 --dry-run
```

---

### Export & Transforms (`export`)

#### Split Files by Store
```bash
./shopctl export all --split-by-site
```

#### Price Adjustments & Rounding
```bash
# Apply a 20% markup and round to .99
./shopctl export --site bobogears --markup 1.20 --round-to 0.99
```

#### Catalog Filtering
```bash
# Export in-stock products with images for a given vendor
./shopctl export all --vendor "Bobo" --in-stock --with-images

# Filter by price bounds and search term
./shopctl export all --query "holder" --min-price 500 --max-price 3000
```

#### Excel & Business Intelligence Export
```bash
# Export flat one-row-per-variant Excel spreadsheet for market analysis
./shopctl export all -p research -f xlsx -o catalog_analysis.xlsx
```

#### High-Resolution Image Manifest
```bash
# Export flat CSV containing all image URLs
./shopctl export all --images-manifest
```

---

### Inspection & Diagnostics

```bash
# View database statistics and data quality metrics
./shopctl stats

# Search and inspect individual product objects
./shopctl inspect "phone holder"

# Compare price changes between consecutive scrapes
./shopctl diff

# Review historical scrape sessions
./shopctl runs
```

---

## Export Profiles

| Profile | Target | Description |
|---|---|---|
| `shopify-import` *(default)* | Shopify Store Import | 57-column layout complying with Shopify's product import specification |
| `shopify-legacy` | Legacy Apps & Integrations | 36-column Handle/Title layout |
| `research` | Spreadsheets & Analysis | Flat one-row-per-variant layout including product URLs, stock flags, and discount percentages |

---

## Configuration

Settings are stored in `~/.shopscrape/config.yml` and can be adjusted via CLI:

```bash
# Display active settings
./shopctl config show

# Set request rate limiter delay (seconds)
./shopctl config set delay 1.0

# Set default in-stock inventory quantity
./shopctl config set default_qty_in_stock 50
```

---

## Directory Layout

```text
shopify-product-scraper/
├── shopctl                 # CLI entrypoint executable
├── pyproject.toml          # Project package definitions
├── requirements.txt        # Runtime dependencies
└── shopscrape/
    ├── cli.py              # Click command-line interface
    ├── columns.py          # Export column specifications
    ├── config.py           # Configuration and registry manager
    ├── detect.py           # Platform fingerprinting engine
    ├── exporter.py         # CSV, XLSX, and JSON writers
    ├── fetcher.py          # Rate-limited HTTP client with backoff
    ├── models.py           # Normalized product and variant data structures
    ├── source.py           # Shopify endpoint catalog extractor
    ├── store.py            # SQLite cache and price history engine
    ├── transform.py        # Pipeline filters and rules
    └── ui.py               # Console output and table formatter
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
