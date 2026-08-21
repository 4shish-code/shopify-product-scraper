from __future__ import annotations

SHOPIFY_IMPORT = [
    "Title", "URL handle", "Description", "Vendor", "Product category", "Type", "Tags",
    "Published on online store", "Status", "SKU", "Barcode",
    "Option1 name", "Option1 value", "Option1 Linked To",
    "Option2 name", "Option2 value", "Option2 Linked To",
    "Option3 name", "Option3 value", "Option3 Linked To",
    "Price", "Compare-at price", "Cost per item", "Charge tax", "Tax code",
    "Unit price total measure", "Unit price total measure unit",
    "Unit price base measure", "Unit price base measure unit",
    "Inventory tracker", "Inventory quantity", "Continue selling when out of stock",
    "Weight value (grams)", "Weight unit for display", "Requires shipping",
    "Fulfillment service", "Product image URL", "Image position", "Image alt text",
    "Variant image URL", "Gift card", "SEO title", "SEO description",
    "Color (product.metafields.shopify.color-pattern)",
    "Google Shopping / Google product category", "Google Shopping / Gender",
    "Google Shopping / Age group",
    "Google Shopping / Manufacturer part number (MPN)",
    "Google Shopping / Ad group name", "Google Shopping / Ads labels",
    "Google Shopping / Condition", "Google Shopping / Custom product",
    "Google Shopping / Custom label 0", "Google Shopping / Custom label 1",
    "Google Shopping / Custom label 2", "Google Shopping / Custom label 3",
    "Google Shopping / Custom label 4",
]

SHOPIFY_LEGACY = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags",
    "Published", "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value",
    "Option3 Name", "Option3 Value", "Variant SKU", "Variant Grams",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
    "Variant Fulfillment Service", "Variant Price", "Variant Compare At Price",
    "Variant Requires Shipping", "Variant Taxable", "Variant Barcode",
    "Image Src", "Image Position", "Image Alt Text", "Gift Card",
    "SEO Title", "SEO Description", "Variant Image", "Variant Weight Unit",
    "Variant Tax Code", "Cost per item", "Status",
]

RESEARCH = [
    "site", "domain", "product_id", "handle", "title", "vendor", "type", "tags",
    "variant_id", "variant_title", "sku", "barcode",
    "price", "compare_at_price", "on_sale", "discount_pct",
    "in_stock", "grams", "option1", "option2", "option3",
    "image_count", "main_image", "all_images", "variant_image",
    "created_at", "updated_at", "product_url", "description_text",
]

PROFILES = {
    "shopify-import": SHOPIFY_IMPORT,
    "shopify-legacy": SHOPIFY_LEGACY,
    "research": RESEARCH,
}

PROFILE_HELP = {
    "shopify-import": "57-column modern Shopify template (matches product_template.csv)",
    "shopify-legacy": "Classic Handle/Command Shopify CSV — widest compatibility",
    "research": "Flat one-row-per-variant sheet for price comparison",
}
