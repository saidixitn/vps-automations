import pymongo
import requests
import json
import re
import time
import os
from dotenv import load_dotenv
load_dotenv()
# --- Configuration ---
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "serper_db"


def get_zipcode_from_address(address):
    """Extracts a 5-digit US zip code from the address string."""
    if not address:
        return ""
    match = re.search(r'\b\d{5}(?:-\d{4})?\b', address)
    return match.group(0) if match else ""


def main():
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]

    input_col = db["input"]
    api_key_col = db["api_key"]
    output_col = db["output"]

    # 1. Load API Keys
    api_keys = [doc.get("api_key") for doc in api_key_col.find({}) if doc.get("api_key")]
    if not api_keys:
        print("Error: No API keys found.")
        return

    current_key_index = 0
    print(f"Loaded {len(api_keys)} API keys.")

    # 2. Fetch inputs where status is not 'scraped'
    # This handles your "scraped or not" requirement
    query_filter = {"status": {"$ne": "scraped"}}
    total_to_process = input_col.count_documents(query_filter)
    print(f"Found {total_to_process} pending items to scrape.")

    cities_cursor = input_col.find(query_filter)
    url = "https://google.serper.dev/maps"

    for doc in cities_cursor:
        doc_id = doc.get("_id")
        city = doc.get("city")
        state = doc.get("state")
        base_query = doc.get("query")  # Example: "Aramark Stores in"

        if not all([city, state, base_query]):
            print(f"Skipping malformed row: {doc}")
            continue

        # Combine the query: "Aramark Stores in Boston, MA"
        full_search_query = f"{base_query} {city}, {state}"
        payload = json.dumps({"q": full_search_query})

        success = False
        api_exhausted = False

        while current_key_index < len(api_keys):
            headers = {
                'X-API-KEY': api_keys[current_key_index],
                'Content-Type': 'application/json'
            }

            try:
                response = requests.post(url, headers=headers, data=payload)
                response_text = response.text.lower()
            except Exception as e:
                print(f"Network error on {full_search_query}: {e}")
                break

                # Check for exhaustion
            if response.status_code in [401, 403, 429] or "not enough credits" in response_text:
                print(f"Key {current_key_index + 1} exhausted. Switching...")
                current_key_index += 1
                if current_key_index >= len(api_keys):
                    api_exhausted = True
                    break
                continue

            if response.status_code == 200:
                success = True
                break
            else:
                print(f"Failed {full_search_query}. Code: {response.status_code}")
                break

        if api_exhausted:
            print("CRITICAL: All keys exhausted. Exiting.")
            break

        if success:
            data = response.json()
            places = data.get("places", [])

            if places:
                documents_to_insert = []
                for place in places:
                    item_doc = place.copy()
                    item_doc["search_query"] = full_search_query
                    item_doc["city"] = city
                    item_doc["state"] = state
                    item_doc["zipcode"] = get_zipcode_from_address(place.get("address", ""))
                    documents_to_insert.append(item_doc)

                output_col.insert_many(documents_to_insert)
                print(f"Inserted {len(documents_to_insert)} results for: {full_search_query}")

                # Update status in input collection
                input_col.update_one({"_id": doc_id}, {"$set": {"status": "scraped"}})
            else:
                print(f"No results for: {full_search_query}")
                input_col.update_one({"_id": doc_id}, {"$set": {"status": "no_results"}})

        time.sleep(0.5)

    print("Process finished.")


if __name__ == "__main__":
    main()