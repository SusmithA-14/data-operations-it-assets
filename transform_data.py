from elasticsearch import Elasticsearch
from datetime import datetime
import time
import urllib3

# Suppress SSL warnings for cleaner output
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CONFIGURATION ===
ES_ENDPOINT = "https://my-elasticsearch-project-e5302c.es.us-central1.gcp.elastic.cloud:443"
ES_API_KEY = "ZTJod1Nab0J6dXpSVWFWeWlKdGw6VzZjT0xGbGFva1ZadUhHSTJLakxSQQ=="

# Index Configuration
SOURCE_INDEX = "it_asset"
TARGET_INDEX = "it_asset_transformed"

# === CONNECT TO ELASTIC ===
es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY,
    verify_certs=False
)

# === CHECK CONNECTION ===
print("🔌 Testing Elasticsearch connection...")
print(f"   📍 Endpoint: {ES_ENDPOINT}")

if not es.ping():
    print("❌ Connection failed! Please check endpoint or API key.")
    exit()
else:
    print("✅ Successfully connected to Elasticsearch!")

    # Get cluster info for confirmation
    try:
        info = es.info()
        print(f"   📊 Cluster: {info['cluster_name']}")
        print(f"   📋 Version: {info['version']['number']}")
    except:
        pass

# === 1️⃣ CHECK AND PREPARE TARGET INDEX ===
print(f"\n📋 Step 1: Preparing target index '{TARGET_INDEX}'")

if es.indices.exists(index=TARGET_INDEX):
    existing_count = es.count(index=TARGET_INDEX)["count"]
    print(f"   ⚠️  Target index already exists with {existing_count:,} documents")

    response = input(f"   ❓ Delete existing index '{TARGET_INDEX}'? (y/N): ")
    if response.lower() != 'y':
        print("   🛑 Operation cancelled by user")
        exit()

    es.indices.delete(index=TARGET_INDEX)
    print(f"   🗑️ Deleted existing index '{TARGET_INDEX}'")
else:
    print(f"   ℹ️  Target index '{TARGET_INDEX}' doesn't exist - will create new")

# === 2️⃣ REINDEX DATA TO ANOTHER INDEX ===
print(f"\n📦 Step 2: Reindexing data from '{SOURCE_INDEX}' to '{TARGET_INDEX}'")

# Check source data first
if not es.indices.exists(index=SOURCE_INDEX):
    print(f"   ❌ Source index '{SOURCE_INDEX}' not found!")
    exit()

source_count = es.count(index=SOURCE_INDEX)["count"]
print(f"   📊 Source index has {source_count:,} records to copy")

if source_count == 0:
    print("   ⚠️ No data to process!")
    exit()

response = input(f"   ❓ Proceed with reindexing {source_count:,} records? (Y/n): ")
if response.lower() == 'n':
    print("   🛑 Reindexing cancelled by user")
    exit()

print("   ⏳ Starting reindex operation...")

reindex_body = {
    "source": {"index": SOURCE_INDEX},
    "dest": {"index": TARGET_INDEX}
}

start_time = time.time()
reindex_result = es.reindex(body=reindex_body, wait_for_completion=True)
end_time = time.time()

print(f"   ✅ Reindex completed in {end_time - start_time:.2f} seconds")
print(f"   📊 Records copied: {reindex_result.get('total', 0):,}")

# Force refresh and wait a moment
es.indices.refresh(index=TARGET_INDEX)
time.sleep(1)

# Verify target data
target_count = es.count(index=TARGET_INDEX)["count"]
print(f"   📈 Target index now has {target_count:,} documents")

if target_count != source_count:
    print(f"   ⚠️ Record count mismatch! Expected: {source_count:,}, Got: {target_count:,}")
    response = input("   ❓ Continue despite mismatch? (y/N): ")
    if response.lower() != 'y':
        exit()

# === 3️⃣ ADD DERIVED FIELDS (risk_level + system_age_years) ===
# Painless script to calculate risk_level and system_age_years
update_script = """
// Add risk_level based on lifecycle status
if (ctx._source.containsKey('operating_system_lifecycle_status')) {
    def status = ctx._source.operating_system_lifecycle_status.toLowerCase();
    if (status == 'eol' || status == 'eos') {
        ctx._source.risk_level = 'High';
    } else {
        ctx._source.risk_level = 'Low';
    }
}

// Add system_age_years based on installation date
if (ctx._source.containsKey('operating_system_installation_date')) {
    try {
        def date_str = ctx._source.operating_system_installation_date;
        if (date_str != null && date_str.length() >= 4) {
            def install_year = Integer.parseInt(date_str.substring(0, 4));
            def current_year = 2025;
            ctx._source.system_age_years = current_year - install_year;
        }
    } catch (Exception e) {
        // ignore invalid dates
    }
}
"""

# === 3️⃣ ADD DERIVED FIELDS ===
print(f"\n⚙️  Step 3: Adding derived fields (risk_level, system_age_years)")

# Count documents that will be processed
total_docs = es.count(index=TARGET_INDEX)["count"]
print(f"   📊 Processing {total_docs:,} documents")

# Analyze lifecycle status before transformation
try:
    eol_eos_query = {
        "bool": {
            "should": [
                {"term": {"operating_system_lifecycle_status.keyword": "EOL"}},
                {"term": {"operating_system_lifecycle_status.keyword": "EOS"}}
            ]
        }
    }
    high_risk_count = es.count(index=TARGET_INDEX, body={"query": eol_eos_query})["count"]
    low_risk_count = total_docs - high_risk_count

    print(f"   📈 Expected risk assignments:")
    print(f"      - High risk (EOL/EOS): {high_risk_count:,} documents")
    print(f"      - Low risk (others): {low_risk_count:,} documents")
except:
    print("   ℹ️ Could not analyze lifecycle status distribution")

response = input(f"   ❓ Proceed with adding derived fields to {total_docs:,} documents? (Y/n): ")
if response.lower() == 'n':
    print("   ⏭️ Skipped adding derived fields")
else:
    print("   ⏳ Applying Painless script...")

    update_query = {
        "script": {"source": update_script, "lang": "painless"},
        "query": {"match_all": {}}
    }

    start_time = time.time()
    result = es.update_by_query(index=TARGET_INDEX, body=update_query, refresh=True)
    end_time = time.time()

    updated_count = result.get('updated', 0)
    print(f"   ✅ Added derived fields in {end_time - start_time:.2f} seconds")
    print(f"   📊 Documents updated: {updated_count:,}")

    # Verify fields were added
    sample = es.search(index=TARGET_INDEX, body={"size": 1})
    if sample['hits']['hits']:
        record = sample['hits']['hits'][0]['_source']
        has_risk = 'risk_level' in record
        has_age = 'system_age_years' in record
        print(f"   🔍 Verification: risk_level={'✅' if has_risk else '❌'}, system_age_years={'✅' if has_age else '❌'}")

# === 4️⃣ DELETE INVALID RECORDS ===
print(f"\n🧹 Step 4: Cleaning invalid records")

# Check what will be deleted
count_before = es.count(index=TARGET_INDEX)["count"]
print(f"   📊 Records before cleanup: {count_before:,}")

# Count records to be deleted
unknown_hostnames = es.count(index=TARGET_INDEX, body={"query": {"term": {"hostname.keyword": "Unknown"}}})["count"]

print(f"   🔍 Analysis of records to delete:")
print(f"      - Unknown hostnames: {unknown_hostnames:,}")

if unknown_hostnames == 0:
    print("   ✅ No invalid records found to delete")
else:
    print(f"   📊 Total records to delete: {unknown_hostnames:,}")
    print(f"   📊 Records remaining after cleanup: {count_before - unknown_hostnames:,}")

    response = input(f"   ❓ Proceed with deleting {unknown_hostnames:,} invalid records? (Y/n): ")
    if response.lower() == 'n':
        print("   ⏭️ Skipped record deletion")
    else:
        print("   ⏳ Deleting invalid records...")

        delete_query = {
            "query": {
                "term": {"hostname.keyword": "Unknown"}
            }
        }

        start_time = time.time()
        result = es.delete_by_query(index=TARGET_INDEX, body=delete_query, refresh=True)
        end_time = time.time()

        deleted_count = result.get('deleted', 0)
        print(f"   ✅ Deleted {deleted_count:,} records in {end_time - start_time:.2f} seconds")
        print("   ℹ️ Keeping records with Unknown providers (as requested)")

# === 5️⃣ FINAL SUMMARY AND CONFIRMATION ===
print(f"\n🎉 TRANSFORMATION COMPLETED!")
print("="*60)

final_count = es.count(index=TARGET_INDEX)["count"]
print(f"📊 Final Statistics:")
print(f"   📈 Transformed index '{TARGET_INDEX}': {final_count:,} documents")

# Show risk distribution
try:
    high_risk = es.count(index=TARGET_INDEX, body={"query": {"term": {"risk_level.keyword": "High"}}})["count"]
    low_risk = es.count(index=TARGET_INDEX, body={"query": {"term": {"risk_level.keyword": "Low"}}})["count"]

    print(f"\n📈 Risk Level Distribution:")
    print(f"   🔴 High Risk (EOL/EOS): {high_risk:,} ({(high_risk/final_count*100):.1f}%)")
    print(f"   🟢 Low Risk: {low_risk:,} ({(low_risk/final_count*100):.1f}%)")
except:
    print("   ℹ️ Could not calculate risk distribution")

print(f"\n✅ All transformation steps completed successfully!")
print(f"🎯 Your enhanced IT asset data is ready for analysis!")