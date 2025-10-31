from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import pandas as pd
import os
from datetime import datetime
import json

# === CONFIGURATION ===
ES_ENDPOINT = "https://my-elasticsearch-project-e5302c.es.us-central1.gcp.elastic.cloud:443"
ES_API_KEY = "eHVqR0xwb0JKcEtTakJBRXRzbzI6YjhnQ0lhb2U1ZE45RzRTd3VGU3FJQQ=="

# CSV Configuration
CSV_FILE_PATH = "it_asset_inventory_cleaned.csv"  # Change this to your CSV file path
TARGET_INDEX = "it_asset"  # Change this to your desired Elasticsearch index name

# === CONNECT TO ELASTIC ===
es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY,
    verify_certs=True
)

# === CHECK CONNECTION ===
if not es.ping():
    print("❌ Connection failed! Please check endpoint or API key.")
    exit()
else:
    print("✅ Connected to Elasticsearch!")

# === VALIDATE CSV FILE ===
if not os.path.exists(CSV_FILE_PATH):
    print(f"❌ CSV file not found: {CSV_FILE_PATH}")
    print("Please update the CSV_FILE_PATH in the configuration section.")
    exit()

print(f"📁 Found CSV file: {CSV_FILE_PATH}")
print(f"🎯 Target index: {TARGET_INDEX}")

# === FUNCTION TO PREPARE DOCUMENTS FOR BULK UPLOAD ===
def prepare_docs(df, index_name):
    """Convert DataFrame rows to Elasticsearch documents"""
    docs = []
    for _, row in df.iterrows():
        # Convert row to dictionary
        doc = row.to_dict()

        # Handle NaN values
        for key, value in doc.items():
            if pd.isna(value):
                doc[key] = None

        # Create the document structure for bulk upload
        docs.append({
            "_index": index_name,
            "_source": doc
        })

    return docs

# === UPLOAD CSV TO ELASTICSEARCH ===
print(f"\n📤 Processing CSV file...")

try:
    # Read CSV file
    df = pd.read_csv(CSV_FILE_PATH)
    print(f"📊 Found {len(df)} records in CSV file")

    # Use the configured target index
    index_name = TARGET_INDEX

    print(f"🎯 Target index: {index_name}")

    # Ask for confirmation
    confirm = input(f"👉 Upload to index '{index_name}'? (y/n): ").strip().lower()
    if confirm != 'y':
        print("⏭️ Upload cancelled.")
        exit()

    # Create index with proper mapping (optional - Elasticsearch can auto-detect)
    # You can customize this mapping based on your data structure
    mapping = {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                "date": {"type": "date"},
                "transaction_id": {"type": "keyword"},
                "country": {"type": "keyword"},
                "sales_person": {"type": "keyword"},
                "product_name": {"type": "text"},
                "product_category": {"type": "keyword"},
                "region": {"type": "keyword"},
                "unit_price": {"type": "float"},
                "units_sold": {"type": "integer"},
                "total_sales": {"type": "float"},
                "customer_rating": {"type": "float"},
                "profit_margin": {"type": "float"}
            }
        }
    }

    # Check if index exists
    if es.indices.exists(index=index_name):
        overwrite = input(f"⚠️ Index '{index_name}' already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite == 'y':
            es.indices.delete(index=index_name)
            print(f"🗑️ Deleted existing index: {index_name}")
        else:
            print("⏭️ Upload cancelled.")
            exit()

    # Create the index
    es.indices.create(index=index_name, body=mapping, ignore=400)
    print(f"✅ Created index: {index_name}")

    # Prepare documents for bulk upload
    docs = prepare_docs(df, index_name)

    # Upload documents in batches
    print(f"⬆️ Uploading {len(docs)} documents...")

    # Use bulk helper for efficient upload
    try:
        success_count, failed_docs = bulk(es, docs, chunk_size=1000, request_timeout=60)
        print(f"✅ Successfully uploaded {success_count} documents")

        if failed_docs:
            print(f"⚠️ Failed to upload {len(failed_docs)} documents")
            for failed_doc in failed_docs[:5]:  # Show first 5 failures
                print(f"❌ Failed document: {failed_doc}")

    except Exception as bulk_error:
        print(f"❌ Bulk upload error: {str(bulk_error)}")
        # Try alternative approach with individual documents
        print("🔄 Trying individual document upload...")
        success_count = 0
        failed_count = 0

        for doc in docs:
            try:
                es.index(index=doc["_index"], body=doc["_source"])
                success_count += 1
            except Exception as e:
                failed_count += 1
                if failed_count <= 5:  # Show first 5 failures
                    print(f"❌ Failed to index document: {str(e)}")

        print(f"✅ Successfully uploaded {success_count} documents")
        if failed_count > 0:
            print(f"⚠️ Failed to upload {failed_count} documents")

    # Refresh the index to make documents searchable immediately
    es.indices.refresh(index=index_name)

    # Verify the upload
    count_result = es.count(index=index_name)
    print(f"🔍 Verification: Index '{index_name}' now contains {count_result['count']} documents")

except Exception as e:
    print(f"❌ Error processing CSV file: {str(e)}")
    exit()

print("\n🎉 Upload process complete!")

# === SHOW FINAL STATUS ===
print("\n📊 Current indices:")
try:
    indices = es.cat.indices(format="json")
    for idx in indices:
        if not idx['index'].startswith('.'):  # Skip system indices
            print(f"  - {idx['index']}: {idx['docs.count']} documents ({idx['store.size']})")
except Exception as e:
    print(f"❌ Error retrieving indices info: {str(e)}")