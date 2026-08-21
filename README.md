# shopscrape 🛍️

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Shopify Compatible](https://img.shields.io/badge/Shopify-57--Column%20Import%20Ready-96bf48.svg)](https://help.shopify.com/en/manual/products/import-export/using-csv)
[![CLI](https://img.shields.io/badge/CLI-shopctl-informational.svg)](#cli-usage)

A high-performance, resilient CLI tool and Python engine designed to extract product catalogs from any public Shopify storefront and export them directly into **100% Shopify-compatible import CSVs (57-column modern template)**, Excel spreadsheets (`.xlsx`), or JSON.

---

## ⚡ Highlights

- **Direct Shopify Import Ready**: Outputs strictly formatted CSVs matching Shopify's 57-column product import template byte-for-byte. No re-formatting or manual cleanup required.
- **Variant & Multi-Image Expansion**: Accurately maps parent products, multiple options (Size/Color/Material), pricing, SKU, barcodes, and multiple product images with exact handle continuations.
- **Smart Rate Limiting & Backoff**: Built-in exponential backoff, jitter, and automatic `Retry-After` header handling for reliable scraping without getting blocked.
- **Local SQLite Caching**: Saves scraped catalogs locally so you can filter, transform, re-export, and compare prices without re-scraping.
- **Price Diff & History Tracking**: Tracks price changes across consecutive runs (`shopctl diff`).
- **Flexible Data Transforms**: Apply price markups (e.g. +15%), price rounding (e.g. `.99`, `9`, `10`), tag prefixes, vendor overrides, and custom draft statuses during export.
- **Multi-Format Export**: Generates Shopify 57-column CSVs, classic Shopify legacy CSVs, flat research spreadsheets for Excel/Sheets, and JSON.

---

## 📦 Installation & Setup

Requires **Python 3.10** or newer.

```bash
# Clone the repository
git clone https://github.com/4shish-code/shopify-product-scraper.git
cd shopify-product-scraper

# Install dependencies
pip install -r requirements.txt
```

*(Optional) Install globally as a CLI utility:*
```bash
pip install -e .
```

---

## 🚀 Quickstart

### 1. Verify configured stores
```bash
./shopctl doctor
```

### 2. Scrape stores
```bash
# Scrape a single store
./shopctl scrape --site bobogears

# Scrape all configured stores
./shopctl scrape all
```

### 3. Export to CSV

**Export individual CSV files for every store:**
```bash
./shopctl export all --split-by-site --status Draft
```

**Export a specific store:**
```bash
./shopctl export --site bobogears
```

Files are automatically generated in the `exports/` directory.

To import into Shopify:
> **Shopify Admin** → **Products** → **Import** → Upload your CSV.

---

## 🛠️ CLI Reference

### Store Management (`sites`)

```bash
# List all registered stores and catalog counts
./shopctl sites list

# Add a new store (validates Shopify compatibility automatically)
./shopctl sites add mystore.com

# Add store with custom key and collection filters
./shopctl sites add mystore.com --key mycustom --collection helmets --collection jackets

# Inspect public collections for a store
./shopctl sites collections bobogears

# Update store settings or disable a store
./shopctl sites set bobogears --vendor "Custom Vendor" --add-tag imported
./shopctl sites set mototorque --disable

# Remove a store
./shopctl sites remove mystore.com --purge
```

---

### Scraping (`scrape`)

```bash
# Scrape all active stores
./shopctl scrape all

# Scrape specific stores
./shopctl scrape --site fleettrack --site bobogears

# Test run with limit and dry-run (no DB write)
./shopctl scrape all --limit 10 --dry-run
```

---

### Exporting & Transformations (`export`)

#### 1. Split files per store
```bash
./shopctl export all --split-by-site
```

#### 2. Apply price markups & rounding
```bash
# Apply a 20% markup and round prices to .99
./shopctl export --site bobogears --markup 1.20 --round-to 0.99
```

#### 3. Filtering options
```bash
# Export only in-stock products with images for a specific vendor
./shopctl export all --vendor "Bobo" --in-stock --with-images

# Export by price range and search term
./shopctl export all --query "holder" --min-price 500 --max-price 3000
```

#### 4. Research & Excel output
```bash
# Export flat one-row-per-variant Excel spreadsheet for market analysis
./shopctl export all -p research -f xlsx -o catalog_analysis.xlsx
```

#### 5. Image manifest export
```bash
# Generate flat CSV containing all high-res image URLs
./shopctl export all --images-manifest
```

---

### Catalog Inspection & Diagnostics

```bash
# View stored database stats & data quality breakdown
./shopctl stats

# Search and inspect details of specific products
./shopctl inspect "helmet mount"

# View price fluctuations between scrapes
./shopctl diff

# Review historical scraping runs
./shopctl runs
```

---

## 📊 Export Column Profiles

| Profile | Target / Use Case | Format Details |
|---|---|---|
| `shopify-import` *(default)* | Modern Shopify Store Import | Exact 57-column schema matching official Shopify product import specification |
| `shopify-legacy` | Legacy Shopify stores / Apps | 36-column classic Handle/Title layout |
| `research` | Market research & BI | Flat one-row-per-variant layout with direct URLs, sale flags, and discount % |

---

## ⚙️ Configuration

Configuration is stored in `~/.shopscrape/config.yml`. You can inspect or update settings at any time:

```bash
# View configuration
./shopctl config show

# Adjust request rate limiter delay
./shopctl config set delay 1.0

# Set default in-stock inventory count for exported products
./shopctl config set default_qty_in_stock 50
```

---

## 📁 Project Structure

```text
shopify-product-scraper/
├── shopctl                 # Executable CLI launcher
├── pyproject.toml          # Package build configuration
├── requirements.txt        # Python dependencies
└── shopscrape/
    ├── cli.py              # Click CLI command definitions
    ├── columns.py          # Shopify & Research column schemas
    ├── config.py           # YAML config manager & registry
    ├── detect.py           # Storefront fingerprinting engine
    ├── exporter.py         # CSV, XLSX, and JSON writers & validator
    ├── fetcher.py          # Rate-limited HTTP client with backoff
    ├── models.py           # Normalized product and variant models
    ├── source.py           # Shopify storefront catalog source
    ├── store.py            # SQLite cache & price history store
    ├── transform.py        # Rule-based transformers & filters
    └── ui.py               # Rich terminal formatting & tables
```

---

## 📄 License

Distributed under the MIT License.
