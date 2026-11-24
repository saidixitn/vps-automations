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
DB_NAME = "Hotels"


def get_zipcode_from_address(address):
    """Extracts a 5-digit US zip code from the address string."""
    if not address:
        return ""
    # Looks for 5 digits, optionally followed by a dash and 4 digits (e.g., 77046 or 77046-1234)
    match = re.search(r'\b\d{5}(?:-\d{4})?\b', address)
    return match.group(0) if match else ""


def main():
    # Connect to MongoDB
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]

    input_col = db["input"]
    api_key_col = db["api_key"]
    output_col = db["output"]

    # 1. Load API Keys
    keys_cursor = api_key_col.find({})
    api_keys = [doc.get("api_key") for doc in keys_cursor if doc.get("api_key")]

    if not api_keys:
        print("Error: No API keys found in the database.")
        return

    current_key_index = 0
    print(f"Loaded {len(api_keys)} API keys.")

    # 2. Track already scraped cities to prevent duplicates on restart
    processed_queries = output_col.distinct("query")
    print(f"Found {len(processed_queries)} already processed queries. Skipping those...")

    # 3. Fetch input cities
    cities_cursor = input_col.find({})

    url = "https://google.serper.dev/maps"

    for location in cities_cursor:
        city = location.get("city")
        state = location.get("state")

        if not city or not state:
            continue

        query = f"Hotels in {city}, {state}"

        # Skip if we already scraped this query
        if query in processed_queries:
            continue

        payload = json.dumps({"q": query})

        # Flag to track if the current city was scraped successfully
        success = False

        # Request Loop (handles API key exhaustion)
        while current_key_index < len(api_keys):
            headers = {
                'X-API-KEY': api_keys[current_key_index],
                'Content-Type': 'application/json'
            }

            try:
                response = requests.post(url, headers=headers, data=payload)
            except Exception as e:
                print(f"Network error on {query}: {e}")
                break  # Break out to move to the next city

            response_text = response.text.lower()

            # --- THE FIX: Look specifically for Serper's "Not enough credits" message ---
            is_out_of_credits = (
                response.status_code in [401, 403, 429] or
                "not enough credits" in response_text
            )

            if is_out_of_credits:
                # Mask the key for security in the console output
                masked_key = f"...{api_keys[current_key_index][-4:]}" if len(
                    api_keys[current_key_index]) > 4 else "UNKNOWN"
                print(f"Key {current_key_index + 1} ({masked_key}) exhausted. Switching to next key...")

                current_key_index += 1

                if current_key_index >= len(api_keys):
                    print("CRITICAL: All API keys have been exhausted. Exiting script.")
                    return  # Kills the script entirely because there are no keys left

                continue  # Go back to the start of the 'while' loop to retry THIS city with the NEW key

            # If successful, process data and break the retry loop
            if response.status_code == 200:
                success = True
                break
            else:
                # If it failed for a completely different reason (e.g., 500 server error)
                print(f"Failed to fetch {query}. Status Code: {response.status_code}. Response: {response.text}")
                break  # Give up on this city and move to the next one

        # If we failed to get a 200 OK after trying keys, skip to the next city in the DB
        if not success:
            continue

        # Parse and process successful response
        data = response.json()
        places = data.get("places", [])

        if not places:
            print(f"No places found for query: {query}")
            continue

        documents_to_insert = []
        for place in places:
            hotel_doc = place.copy()

            # Add our custom fields
            hotel_doc["query"] = query
            hotel_doc["city"] = city
            hotel_doc["state"] = state
            hotel_doc["zipcode"] = get_zipcode_from_address(place.get("address", ""))

            documents_to_insert.append(hotel_doc)

        # Insert all hotels for this city into MongoDB
        if documents_to_insert:
            output_col.insert_many(documents_to_insert)
            print(f"Successfully inserted {len(documents_to_insert)} hotels for: {query}")

        # Polite sleep to prevent overwhelming the API or getting rate-limited
        time.sleep(0.5)

    print("Scraping completed!")


if __name__ == "__main__":
    main()