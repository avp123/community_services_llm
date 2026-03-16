"""
RAG Utilities: Embeddings, FAISS Indexing, and Database Management.

This module handles:
1. Connecting to the Postgres database.
2. Fetching 'resources' and 'pages' (documents).
3. generating/loading FAISS indices for fast retrieval.
"""
import os
import numpy as np
import pandas as pd
import psycopg
from sentence_transformers import SentenceTransformer
import faiss
import googlemaps
import json 
import time
from scipy.spatial import cKDTree
import math 

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from dotenv import load_dotenv
load_dotenv()

from openai import AzureOpenAI
client = AzureOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_AZURE"),
    azure_endpoint=os.environ.get("OPENAI_AZURE_ENDPOINT"),
    api_version="2024-12-01-preview"
)


# Create geocoder with a user agent
geolocator = Nominatim(user_agent="peercopilot_app")


# --- Configuration ---
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"

CONNECTION_STRING = os.getenv("RESOURCE_DB_URL")
MODEL_NAME = 'sentence-transformers/all-mpnet-base-v2'
ALL_ORGS = ['cspnj', 'clhs','georgia']

# --- Global Cache ---
_CACHE = {
    "model": None,
    "saved_resources": {},
    "documents_resources": {},
    "metadata_resources": {},
    "geo_trees": {},         
    "geo_indices": {}, 
    "saved_articles": {},
    "documents_articles": {}
}

def get_db_connection():
    return psycopg.connect(CONNECTION_STRING)

def get_embedding_model():
    """Lazy loads the model."""
    if _CACHE["model"] is None:
        print("[RAG] Loading SentenceTransformer...")
        _CACHE["model"] = SentenceTransformer(MODEL_NAME, token=os.getenv('HF_TOKEN'))
    return _CACHE["model"]

def create_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    """Creates a standard FlatL2 index."""
    if len(embeddings) == 0:
        return faiss.IndexFlatL2(768)
    
    d = embeddings.shape[1]
    index = faiss.IndexFlatL2(d)
    index.add(embeddings)
    return index

# ==========================================
#  GEOCODING UTILITIES
# ==========================================

def geocode_address(address: str):
    """
    Geocode an address to lat/lon using Google Maps.
    
    Returns:
        (latitude, longitude) or (None, None) if failed
    """
    if not address:
        return None, None
    
    try:
        gmaps = googlemaps.Client(key=os.getenv('GOOGLE_API_KEY'))
        result = gmaps.geocode(address)
        if result:
            location = result[0]['geometry']['location']
            return location['lat'], location['lng']
    except Exception as e:
        print(f"[Geocoding Error] {address}: {e}")
    return None, None

def is_likely_virtual(service: str, description: str, url: str, phone: str):
    """
    Heuristically detect if a resource is virtual/online.
    """
    virtual_keywords = [
        '211', 'hotline', 'helpline', 'online', 'virtual', 'telehealth',
        'web-based', 'remote', 'statewide', 'nationwide', 'toll-free',
        'chat', 'text line', 'email support', 'crisis text'
    ]
    
    text = f"{service} {description}".lower()
    
    # Has virtual keywords
    if any(keyword in text for keyword in virtual_keywords):
        return True
    
    # Has toll-free number
    if phone:
        cleaned_phone = ''.join(filter(str.isdigit, phone))
        if len(cleaned_phone) >= 10:
            area_code = cleaned_phone[:3] if cleaned_phone[0] != '1' else cleaned_phone[1:4]
            if area_code in ['800', '888', '877', '866', '855', '844', '833']:
                return True
    
    return False

# ==========================================
#  DATABASE WRITERS (For adding content)
# ==========================================

def add_page_to_db(organization: str, category: str, title: str, content: str):
    """
    Encodes and inserts a new article/page into the DB.
    """
    model = get_embedding_model()
    text_emb = f"{title}\n{content}"
    embedding = model.encode(text_emb).tolist()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pages (organization, category, title, content, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (organization, category, title, content, str(embedding))
            )
        conn.commit()
    print(f"[DB] Saved page: {title}")

def add_resource_to_db(organization: str, service: str, description: str, 
                       url: str, phone: str, address: str = None):
    """
    Encodes and inserts a new Resource into the DB with geocoding.
    """
    model = get_embedding_model()
    text_emb = f"{service} {description} {url}"
    embedding = model.encode(text_emb).tolist()

    # Determine if virtual
    is_virtual = is_likely_virtual(service, description, url, phone)
    
    # Geocode the address if not virtual
    latitude, longitude, city = None, None, None
    if address and not is_virtual:
        latitude, longitude = geocode_address(address)
        # Extract city from address (simple heuristic)
        if ',' in address:
            city = address.split(',')[0].strip()
        print(f"[Geocoding] {service}: {latitude}, {longitude}")
    
    coverage_area = 'statewide' if is_virtual else None

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO resources 
                (organization, service, description, url, phone, address, 
                 latitude, longitude, city, is_virtual, coverage_area, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (organization, service, description, url, phone, address, 
                 latitude, longitude, city, is_virtual, coverage_area, str(embedding))
            )
        conn.commit()
    print(f"[DB] Saved resource: {service} (virtual={is_virtual})")

# ==========================================
#  DATABASE READERS (Fetching for RAG)
# ==========================================

def fetch_data_from_db(table_name: str, org_list: list):
    """
    Generic fetcher. Returns (indices_dict, documents_dict, metadata_dict).
    """
    indices = {}
    documents = {}
    metadata = {}  # NEW

    with get_db_connection() as conn:
        for org in org_list:
            query = f"SELECT * FROM {table_name} WHERE organization = %s"
            df = pd.read_sql_query(query, conn, params=[org])
            
            if df.empty:
                indices[org] = create_faiss_index(np.empty((0, 768)))
                documents[org] = []
                metadata[org] = []
                continue

            # Parse Embeddings
            if isinstance(df.iloc[0]['embedding'], str):
                df['embedding'] = df['embedding'].apply(
                    lambda x: [float(n) for n in x.strip("[]").split(",")]
                )
            
            emb_matrix = np.array(df['embedding'].tolist()).astype('float32')
            
            # Format documents and metadata
            docs_list = []
            meta_list = []
            
            for _, row in df.iterrows():
                if table_name == "resources":
                    text = (f"Resource: {row['service']}, "
                            f"Desc: {row['description']}, "
                            f"Phone: {row['phone']}, URL: {row['url']}")
                    
                    # Auto-detect virtual if not already flagged
                    is_virtual = row.get('is_virtual', False)
                    if not is_virtual:
                        is_virtual = is_likely_virtual(
                            row['service'], 
                            row.get('description', ''), 
                            row.get('url', ''), 
                            row.get('phone', '')
                        )
                    
                    meta_list.append({
                        'service': row['service'],
                        'latitude': row.get('latitude'),
                        'longitude': row.get('longitude'),
                        'address': row.get('address'),
                        'city': row.get('city'),
                        'is_virtual': is_virtual,
                        'coverage_area': row.get('coverage_area')
                    })
                    
                elif table_name == "pages":
                    text = (f"Article: {row['title']} (Category: {row['category']})\n"
                            f"Content: {row['content']}")
                    meta_list.append({})
                
                docs_list.append(text)

            # Store results
            if table_name == "resources":
                key = f"resource_{org}"
                documents[key] = docs_list
                metadata[key] = meta_list
                indices[key] = create_faiss_index(emb_matrix)
                coords = []
                coord_to_doc_idx = []
                for idx, meta in enumerate(meta_list):
                    lat = meta.get('latitude')
                    lon = meta.get('longitude')
                    if (not meta.get('is_virtual') and 
                        lat is not None and lon is not None and
                        not math.isnan(float(lat)) and not math.isnan(float(lon))):
                        coords.append([float(lat), float(lon)])
                        coord_to_doc_idx.append(idx)

                print("We have {} coordinates for {}".format(len(coords),org_list))
                for x,y in coords:
                    from geopy.distance import geodesic
                    dist = geodesic(
                        (33.5841835,-83.8609535),
                        (x, y)
                    ).kilometers
                    if dist < 100:
                        print("Distance {}".format(dist))


                if coords:
                    _CACHE["geo_trees"][key] = cKDTree(np.array(coords))
                    _CACHE["geo_indices"][key] = coord_to_doc_idx
                else:
                    _CACHE["geo_trees"][key] = None
                    _CACHE["geo_indices"][key] = []


            elif table_name == "pages":
                for cat in df['category'].unique():
                    cat_df = df[df['category'] == cat]
                    cat_key = f"cat_{cat}"
                    
                    cat_matrix = np.array(cat_df['embedding'].tolist()).astype('float32')
                    cat_docs = []
                    cat_meta = []
                    for _, r in cat_df.iterrows():
                        cat_docs.append(f"Article: {r['title']}\n{r['content']}")
                        cat_meta.append({})
                    
                    if cat_key in documents:
                        documents[cat_key].extend(cat_docs)
                        metadata[cat_key].extend(cat_meta)
                    else:
                        documents[cat_key] = cat_docs
                        metadata[cat_key] = cat_meta
                        indices[cat_key] = create_faiss_index(cat_matrix)

    return indices, documents, metadata

# ==========================================
#  MAIN ENTRY POINT
# ==========================================

def get_model_and_indices():
    """
    Returns the 6 objects expected by main.py:
    1. embedding_model
    2. saved_resources (FAISS indices for resources)
    3. documents_resources (Text lists for resources)
    4. metadata_resources (Location metadata for resources) - NEW
    5. saved_articles (FAISS indices for pages)
    6. documents_articles (Text lists for pages)
    """
    # Return cached if populated
    if _CACHE["model"] is not None and _CACHE["saved_resources"]:
        return (_CACHE["model"], 
                _CACHE["saved_resources"], 
                _CACHE["documents_resources"],
                _CACHE["metadata_resources"],
                _CACHE["saved_articles"], 
                _CACHE["documents_articles"])

    # Load Model
    model = get_embedding_model()

    # Fetch Resources
    print("[RAG] Fetching Resources from DB...")
    res_indices, res_docs, res_metadata = fetch_data_from_db("resources", ALL_ORGS)
    _CACHE["saved_resources"] = res_indices
    _CACHE["documents_resources"] = res_docs
    _CACHE["metadata_resources"] = res_metadata

    # Fetch Pages (Articles)
    print("[RAG] Fetching Pages from DB...")
    page_indices, page_docs, page_metadata = fetch_data_from_db("pages", ALL_ORGS)
    _CACHE["saved_articles"] = page_indices
    _CACHE["documents_articles"] = page_docs

    print("[RAG] Initialization Complete.")
    
    return (model, 
            _CACHE["saved_resources"], 
            _CACHE["documents_resources"],
            _CACHE["metadata_resources"],
            _CACHE["geo_trees"],  
            _CACHE["geo_indices"],
            _CACHE["saved_articles"], 
            _CACHE["documents_articles"])

def migrate_folders():
    """Migrate files from library_resources folder to database."""
    base_path = "../library_resources"
    
    for org in ['cspnj', 'clhs']:
        org_path = os.path.join(base_path, org)
        print(org_path, os.path.exists(org_path))
        if not os.path.exists(org_path): 
            continue
        
        for category in os.listdir(org_path):
            cat_path = os.path.join(org_path, category)
            if not os.path.isdir(cat_path): 
                continue
            
            for filename in os.listdir(cat_path):
                filepath = os.path.join(cat_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    add_page_to_db(
                        organization=org,
                        category=category,
                        title=filename,
                        content=content
                    )


def geocode_address_nominatim(address: str, retry=3):
    """
    Geocode using free Nominatim service.
    
    Args:
        address: Address to geocode
        retry: Number of retries on failure
        
    Returns:
        (latitude, longitude) or (None, None)
    """
    if not address:
        return None, None
    
    for attempt in range(retry):
        try:
            # Add a small delay to respect Nominatim's usage policy (1 req/sec)
            time.sleep(1)
            
            location = geolocator.geocode(address, timeout=10)
            
            if location:
                return location.latitude, location.longitude
            else:
                print(f"[Nominatim] No results for: {address}")
                return None, None
                
        except GeocoderTimedOut:
            print(f"[Nominatim] Timeout for {address}, attempt {attempt+1}/{retry}")
            if attempt == retry - 1:
                return None, None
            time.sleep(2)
            
        except GeocoderServiceError as e:
            print(f"[Nominatim] Service error: {e}")
            return None, None
            
        except Exception as e:
            print(f"[Nominatim] Error: {e}")
            return None, None
    
    return None, None


def extract_location_with_gpt(service: str, description: str, url: str, phone: str):
    """
    Use GPT to extract location info, then Nominatim to geocode.
    Best of both worlds: GPT for extraction, Nominatim for accurate coordinates.
    """
    
    prompt = f"""
Analyze this community resource and extract location information.

Resource Name: {service}
Description: {description}
URL: {url}
Phone: {phone}

Determine:
1. Is this a VIRTUAL/ONLINE-ONLY resource? (Yes if hotline, online service, statewide program with no physical location)
2. If physical, what is the complete address? Extract full street address if available.
3. What city is it in?

Respond ONLY with valid JSON:
{{
  "is_virtual": true/false,
  "address": "full street address with city, state, zip" or null,
  "city": "city name" or null,
  "confidence": "high/medium/low",
  "reasoning": "brief explanation"
}}

Rules:
- For virtual resources: is_virtual=true, address=null, city=null
- For physical locations: extract complete address if present
- If only city mentioned: provide city name
- Always include "NJ" or "New Jersey" in addresses

Examples:
- "211 NJ Helpline" → {{"is_virtual": true, "address": null, "city": null}}
- "Located at 2 Market St, Paterson, NJ 07501" → {{"is_virtual": false, "address": "2 Market St, Paterson, NJ 07501", "city": "Paterson", "confidence": "high"}}
- "Serves Glassboro area" → {{"is_virtual": false, "address": null, "city": "Glassboro", "confidence": "medium"}}
"""

    try:        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a location extraction assistant. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean markdown
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        result = json.loads(content)
        
        # Validate
        if not isinstance(result.get('is_virtual'), bool):
            result['is_virtual'] = False
        
        # If physical, geocode the address
        if not result['is_virtual']:
            address_to_geocode = result.get('address')
            
            # Try full address first
            if address_to_geocode:
                print(f"  → Geocoding address: {address_to_geocode}")
                lat, lon = geocode_address_nominatim(address_to_geocode)
                
                if lat and lon:
                    result['latitude'] = lat
                    result['longitude'] = lon
                    return result
            
            # Fallback to city
            city = result.get('city')
            if city:
                city_address = f"{city}, New Jersey, USA"
                print(f"  → Geocoding city: {city_address}")
                lat, lon = geocode_address_nominatim(city_address)
                
                if lat and lon:
                    result['latitude'] = lat
                    result['longitude'] = lon
                    result['confidence'] = 'medium'  # Lower confidence for city-level
                    return result
            
            # No geocoding possible
            result['latitude'] = None
            result['longitude'] = None
        
        return result
        
    except Exception as e:
        print(f"[GPT Extraction Error] {service}: {e}")
        is_virt = is_likely_virtual(service, description, url, phone)
        return {
            'is_virtual': is_virt,
            'address': None,
            'city': None,
            'latitude': None,
            'longitude': None,
            'confidence': 'low',
            'reasoning': f'Error: {str(e)}'
        }

def migrate_existing_resources_geocode():
    """
    Use GPT to extract, Nominatim to geocode (respecting rate limits).
    """
    print("[Migration] Starting location extraction (this will be slow due to rate limits)...")
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, service, description, url, phone 
                FROM resources 
                WHERE latitude IS NULL
            """)
            
            resources = cur.fetchall()
            total = len(resources)
            print(f"[Migration] Found {total} resources to process")
            print(f"[Estimate] This will take ~{total} seconds (1 req/sec limit)")
            
            stats = {
                'virtual': 0,
                'geocoded_high': 0,
                'geocoded_medium': 0,
                'geocoded_low': 0,
                'failed': 0,
                'skipped': 0
            }
            
            start_time = time.time()
            
            for i, resource in enumerate(resources[:25]):
                res_id, service, description, url, phone = resource
                
                print(f"\n[{i+1}/{total}] {service}")
                
                if not description or description.strip() == '':
                    is_virt = is_likely_virtual(service, '', url or '', phone or '')
                    if is_virt:
                        cur.execute("""
                            UPDATE resources 
                            SET is_virtual = TRUE, coverage_area = 'statewide'
                            WHERE id = %s
                        """, (res_id,))
                        stats['virtual'] += 1
                    else:
                        stats['skipped'] += 1
                    continue
                
                # Extract with GPT + geocode with Nominatim
                location_data = extract_location_with_gpt(
                    service, 
                    description or '', 
                    url or '', 
                    phone or ''
                )
                
                print(f"  → {location_data.get('reasoning')}")
                
                if location_data['is_virtual']:
                    cur.execute("""
                        UPDATE resources 
                        SET is_virtual = TRUE, coverage_area = 'statewide'
                        WHERE id = %s
                    """, (res_id,))
                    print(f"  ✓ Virtual")
                    stats['virtual'] += 1
                
                elif location_data.get('latitude') and location_data.get('longitude'):
                    cur.execute("""
                        UPDATE resources 
                        SET latitude = %s, longitude = %s, 
                            address = %s, city = %s, is_virtual = FALSE
                        WHERE id = %s
                    """, (
                        location_data['latitude'],
                        location_data['longitude'],
                        location_data.get('address'),
                        location_data.get('city'),
                        res_id
                    ))
                    
                    conf = location_data.get('confidence', 'medium')
                    print(f"  ✓ Geocoded ({conf}): {location_data['latitude']:.4f}, {location_data['longitude']:.4f}")
                    
                    if conf == 'high':
                        stats['geocoded_high'] += 1
                    elif conf == 'medium':
                        stats['geocoded_medium'] += 1
                    else:
                        stats['geocoded_low'] += 1
                
                else:
                    print(f"  → No location")
                    cur.execute("UPDATE resources SET is_virtual = FALSE WHERE id = %s", (res_id,))
                    stats['failed'] += 1
                
                # Commit every 10 to avoid losing progress
                if (i + 1) % 10 == 0:
                    conn.commit()
                    elapsed = time.time() - start_time
                    remaining = total - (i + 1)
                    eta = (elapsed / (i + 1)) * remaining
                    print(f"\n  [Progress] {i+1}/{total} done, ETA: {eta/60:.1f} minutes\n")
        
        conn.commit()
    
    print("\n" + "="*60)
    print("[Migration Complete]")
    print(f"  Virtual: {stats['virtual']}")
    print(f"  Geocoded (high): {stats['geocoded_high']}")
    print(f"  Geocoded (medium): {stats['geocoded_medium']}")
    print(f"  Geocoded (low): {stats['geocoded_low']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Skipped: {stats['skipped']}")
    print("="*60)

if __name__ == "__main__":
    migrate_existing_resources_geocode()
