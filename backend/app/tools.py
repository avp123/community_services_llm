from ddgs import DDGS
import googlemaps
import os 
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from geopy.distance import geodesic
import threading
import time

geolocator = Nominatim(user_agent="peercopilot_app")
google_maps_api = os.getenv("GOOGLE_API_KEY")
gmaps = googlemaps.Client(key=google_maps_api)

_GEOCODE_CACHE = {}

def geocode_location(location: str,organization='cspnj'):
    """
    Geocode a location using free Nominatim service.
    
    Args:
        location: City, zip code, or address
        
    Returns:
        (latitude, longitude) or (None, None)
    """
    if not location:
        return None, None
    
    cache_key = location.lower().strip()
    if cache_key in _GEOCODE_CACHE:
        cached = _GEOCODE_CACHE[cache_key]
        return cached['lat'], cached['lng']
    
    try:
        # Add NJ context if just a city/zip
        search_term = location

        if organization == 'cspnj':
            if not any(state in location.lower() for state in ['nj', 'new jersey']):
                search_term = f"{location}, New Jersey, USA"
        elif organization == 'georgia':
            if not any(state in location.lower() for state in ['ga', 'Georgia']):
                search_term = f"{location}, Georgia, USA"

        # Respect Nominatim's 1 req/sec limit
        time.sleep(1)
        
        result = geolocator.geocode(search_term, timeout=10)
        
        if result:
            _GEOCODE_CACHE[cache_key] = {'lat': result.latitude, 'lng': result.longitude}
            return result.latitude, result.longitude
        
    except GeocoderTimedOut:
        print(f"[Geocoding Timeout] {location}")
    except Exception as e:
        print(f"[Geocoding Error] {location}: {e}")
    
    return None, None

def query_resources_geo_aware(
    query: str,
    org_key: str,
    location: str = None,
    k: int = 5,
    saved_indices={},
    documents={},
    metadata={},
    geo_trees={},
    geo_indices={},
    embedding_model=None,
):
    doc_key = f'resource_{org_key}'
    
    if doc_key not in saved_indices:
        print(f"[Warning] No resources loaded for {org_key}")
        return []

    # --- Path 1: Semantic RAG ---
    query_emb = embedding_model.encode(query, convert_to_numpy=True).reshape(1, -1)
    D, I = saved_indices[doc_key].search(query_emb, k=k)
    
    semantic_results = {}
    for semantic_distance, idx in zip(D[0], I[0]):
        if idx >= len(documents[doc_key]):
            continue
        semantic_results[idx] = {
            "resource_text": documents[doc_key][idx],
            "metadata": metadata[doc_key][idx],
            "semantic_score": float(1 / (1 + semantic_distance)),
            "distance_km": None,
            "source": "semantic"
        }

    # --- Path 2: Geographic nearest neighbors ---
    geo_results = {}
    user_lat, user_lon = None, None
    
    if location:
        user_lat, user_lon = geocode_location(location,organization=org_key)
        
        print("Found lat lon {} {}".format(user_lat, user_lon))

        if user_lat and user_lon:
            tree = geo_trees.get(doc_key)
            idx_map = geo_indices.get(doc_key, [])
            
            if tree is not None:
                # Query tree for k nearest
                distances, tree_positions = tree.query([user_lat, user_lon], k=min(k, len(idx_map)))

                # tree.query returns scalar when k=1, normalize to arrays
                if k == 1:
                    distances = [distances]
                    tree_positions = [tree_positions]
                
                for tree_pos, _ in zip(tree_positions, distances):
                    doc_idx = idx_map[tree_pos]
                    meta = metadata[doc_key][doc_idx]
                    
                    dist_km = geodesic(
                        (user_lat, user_lon),
                        (meta['latitude'], meta['longitude'])
                    ).kilometers
                    
                    geo_results[doc_idx] = {
                        "resource_text": documents[doc_key][doc_idx],
                        "metadata": meta,
                        "semantic_score": None,
                        "distance_km": dist_km,
                        "source": "geo"
                    }
    # --- Merge, deduplicate, rank ---
    merged = {}
    
    for idx, r in semantic_results.items():
        merged[idx] = r
        # If this doc also appears in geo results, enrich it
        if idx in geo_results:
            merged[idx]["distance_km"] = geo_results[idx]["distance_km"]
            merged[idx]["source"] = "both"
    
    for idx, r in geo_results.items():
        if idx not in merged:
            # Compute semantic score for geo-only results
            doc_emb = embedding_model.encode(documents[doc_key][idx], convert_to_numpy=True).reshape(1, -1)
            D_single, _ = saved_indices[doc_key].search(doc_emb, k=1)
            r["semantic_score"] = float(1 / (1 + D_single[0][0]))
            merged[idx] = r

    # Sort: prioritize "both", then by distance if available, then semantic
    def sort_key(item):
        idx, r = item
        source_priority = {"both": 0, "geo": 1, "semantic": 2}[r["source"]]
        dist = r["distance_km"] if r["distance_km"] is not None else 9999
        sem = -(r["semantic_score"] or 0)
        return (source_priority, dist, sem)
    
    sorted_results = sorted(merged.items(), key=sort_key)
    return [r for _, r in sorted_results[:k]]


def resources_tool(query: str, organization: str, location: str = None, k: int = 5,
                   saved_indices={}, documents={}, metadata={},
                   geo_trees={}, geo_indices={}, embedding_model=None):
    
    results = query_resources_geo_aware(
        query=query,
        org_key=organization.lower(),
        location=location,
        k=k,
        saved_indices=saved_indices,
        documents=documents,
        metadata=metadata,
        geo_trees=geo_trees,
        geo_indices=geo_indices,
        embedding_model=embedding_model
    )
    
    if not results:
        return "No relevant resources found."
    
    lines = []
    for r in results:
        if r['metadata'].get('is_virtual'):
            tag = "[Statewide/Online]"
        elif r['distance_km'] is not None:
            tag = f"[{r['distance_km']:.1f}km away]"
        else:
            tag = ""
        lines.append(f"- {r['resource_text']} {tag}".strip())
    
    return "\n".join(lines)


def library_tool(query: str, category: str, k: int = 3,saved_indices_peer={},documents_peer={},embedding_model=None):
    """
    Searches specialized document libraries (e.g., 'trans', 'crisis', 'legal').
    """
    doc_key = f"cat_{category.lower()}"
    
    if doc_key not in saved_indices_peer:
        return f"Error: The category '{category}' does not exist. Available: trans, crisis, housing."
    
    # Standard FAISS search (same logic as your query_resources)
    query_emb = embedding_model.encode(query, convert_to_numpy=True).reshape(1, -1)
    D, I = saved_indices_peer[doc_key].search(query_emb, k=k)
    
    results = [documents_peer[doc_key][idx] for idx in I[0] if idx < len(documents_peer[doc_key])]
    
    if not results:
        return "No specific documents found for that query."
        
    return "\n---\n".join(results)

def directions_tool(origin: str, destination: str, mode: str = "driving"):
    """
    Get detailed, step-by-step navigation instructions.
    """
    try:
        result = gmaps.directions(origin, destination, mode=mode, departure_time="now")
        if not result:
            return "No routes found."
        leg = result[0]['legs'][0]
        full_instructions = [f"Total Trip: {leg['duration']['text']} ({leg['distance']['text']})\n"]
        for i, step in enumerate(leg['steps'], 1):
            # Clean up HTML tags (like <b>) that Google returns
            import re
            instruction = re.sub('<[^<]+?>', '', step['html_instructions'])
            duration = step['duration']['text']
            # Add specific transit details if they exist
            if step.get('travel_mode') == 'TRANSIT':
                details = step.get('transit_details', {})
                line = details.get('line', {}).get('short_name', 'Transit')
                stop = details.get('arrival_stop', {}).get('name', 'destination')
                instruction += f" (Take {line} to {stop})"
            full_instructions.append(f"{i}. {instruction} [{duration}]")
        return "\n".join(full_instructions)
    except Exception as e:
        return f"Error: {str(e)}"

def check_eligibility(program: str, household_size: int, monthly_income: float, location: str = None):
    """
    Checks eligibility for SNAP, TANF, Medicaid, SSDI, SSI, Section 8 based on official limits.
    """
    program = program.lower()

    # 2026 NJ SNAP Gross Income Limits (185% Federal Poverty Level)
    # Source: NJ Dept of Human Services / USDA
    snap_limits = {
        1: 2413,
        2: 3261,
        3: 4109,
        4: 4957,
        5: 5805,
        6: 6653,
        7: 7501,
        8: 8349
    }

    # WFNJ/TANF Initial Maximum Allowable Income Levels (monthly), Jan 2025
    tanf_limits = {
        1: 321,
        2: 638,
        3: 839,
        4: 966,
        5: 1092,
        6: 1221,
        7: 1341,
        8: 1442
    }

    # NJFamilyCare Adults (Age 19-64) 0-138% FPL, effective Jan 1 2025
    medicaid_limits = {
        1: 1800,
        2: 2433,
        3: 3065,
        4: 3698,
        5: 4330,
        6: 4963
    }

    # SSA Substantial Gainful Activity (SGA) 2026 — earnings above = generally not disabled for SSDI
    SGA_NON_BLIND_2026 = 1690
    SGA_BLIND_2026 = 2830

    # SSI Federal Benefit Rate 2026 + NJ Optional State Supplement (~$32, SSA-administered)
    SSI_MAX_INDIVIDUAL = 994
    SSI_MAX_COUPLE = 1491
    SSI_NJ_SUPPLEMENT = 32

    # Section 8 HCV Very Low Income Limits (50% AMI) — FY2025 HUD, effective June 1 2025
    # Source: HUD FY2025 Adjusted HOME Income Limits, State of New Jersey
    section8_limits = {
        # Warren County
        "warren":           {1: 44000, 2: 50300, 3: 56550, 4: 62850, 5: 67900, 6: 72950, 7: 77950, 8: 83000},
        # Atlantic City-Hammonton
        "atlantic":         {1: 35100, 2: 40100, 3: 45100, 4: 50100, 5: 54150, 6: 58150, 7: 62150, 8: 66150},
        "hammonton":        {1: 35100, 2: 40100, 3: 45100, 4: 50100, 5: 54150, 6: 58150, 7: 62150, 8: 66150},
        # Cape May
        "cape may":         {1: 42250, 2: 48250, 3: 54300, 4: 60350, 5: 65200, 6: 70000, 7: 74850, 8: 79650},
        # Bergen-Passaic
        "bergen":           {1: 48000, 2: 54850, 3: 61700, 4: 68550, 5: 74050, 6: 79550, 7: 85050, 8: 90500},
        "passaic":          {1: 48000, 2: 54850, 3: 61700, 4: 68550, 5: 74050, 6: 79550, 7: 85050, 8: 90500},
        # Jersey City
        "jersey city":      {1: 46900, 2: 53600, 3: 60300, 4: 67000, 5: 72400, 6: 77750, 7: 83100, 8: 88450},
        "hudson":           {1: 46900, 2: 53600, 3: 60300, 4: 67000, 5: 72400, 6: 77750, 7: 83100, 8: 88450},
        # Middlesex-Somerset-Hunterdon
        "middlesex":        {1: 53700, 2: 61400, 3: 69050, 4: 76700, 5: 82850, 6: 89000, 7: 95150, 8: 101250},
        "somerset":         {1: 53700, 2: 61400, 3: 69050, 4: 76700, 5: 82850, 6: 89000, 7: 95150, 8: 101250},
        "hunterdon":        {1: 53700, 2: 61400, 3: 69050, 4: 76700, 5: 82850, 6: 89000, 7: 95150, 8: 101250},
        # Monmouth-Ocean
        "monmouth":         {1: 47900, 2: 54750, 3: 61600, 4: 68400, 5: 73900, 6: 79350, 7: 84850, 8: 90300},
        "ocean":            {1: 47900, 2: 54750, 3: 61600, 4: 68400, 5: 73900, 6: 79350, 7: 84850, 8: 90300},
        # Newark
        "newark":           {1: 47400, 2: 54150, 3: 60900, 4: 67650, 5: 73100, 6: 78500, 7: 83900, 8: 89300},
        "essex":            {1: 47400, 2: 54150, 3: 60900, 4: 67650, 5: 73100, 6: 78500, 7: 83900, 8: 89300},
        # Philadelphia-Camden-Wilmington
        "philadelphia":     {1: 41800, 2: 47800, 3: 53750, 4: 59700, 5: 64500, 6: 69300, 7: 74050, 8: 78850},
        "camden":           {1: 41800, 2: 47800, 3: 53750, 4: 59700, 5: 64500, 6: 69300, 7: 74050, 8: 78850},
        "gloucester":       {1: 41800, 2: 47800, 3: 53750, 4: 59700, 5: 64500, 6: 69300, 7: 74050, 8: 78850},
        "burlington":       {1: 41800, 2: 47800, 3: 53750, 4: 59700, 5: 64500, 6: 69300, 7: 74050, 8: 78850},
        # Trenton-Princeton
        "trenton":          {1: 44450, 2: 50800, 3: 57150, 4: 63450, 5: 68550, 6: 73650, 7: 78700, 8: 83800},
        "princeton":        {1: 44450, 2: 50800, 3: 57150, 4: 63450, 5: 68550, 6: 73650, 7: 78700, 8: 83800},
        "mercer":           {1: 44450, 2: 50800, 3: 57150, 4: 63450, 5: 68550, 6: 73650, 7: 78700, 8: 83800},
        # Vineland
        "vineland":         {1: 32450, 2: 37100, 3: 41750, 4: 46350, 5: 50100, 6: 53800, 7: 57500, 8: 61200},
        "cumberland":       {1: 32450, 2: 37100, 3: 41750, 4: 46350, 5: 50100, 6: 53800, 7: 57500, 8: 61200},
        "bridgeton":        {1: 32450, 2: 37100, 3: 41750, 4: 46350, 5: 50100, 6: 53800, 7: 57500, 8: 61200},
    }

    if "snap" in program or "food stamp" in program:
        # Get limit (add $848 for each person beyond 8)
        if household_size <= 8:
            limit = snap_limits.get(household_size)
        else:
            limit = 8349 + (848 * (household_size - 8))

        if monthly_income <= limit:
            return f"✅ LIKELY ELIGIBLE. Household income (${monthly_income}) is BELOW the NJ SNAP gross limit (${limit}) for {household_size} people."
        else:
            return f"❌ LIKELY INELIGIBLE. Household income (${monthly_income}) is ABOVE the NJ SNAP gross limit (${limit})."

    if "tanf" in program or "work first" in program or "wfnj" in program:
        if household_size <= 8:
            limit = tanf_limits.get(household_size)
        else:
            limit = 1442 + (99 * (household_size - 8))
        if monthly_income <= limit:
            return f"✅ LIKELY ELIGIBLE. Household income (${monthly_income}) is BELOW the NJ TANF (WFNJ) initial maximum allowable income (${limit}) for {household_size} people."
        else:
            return f"❌ LIKELY INELIGIBLE. Household income (${monthly_income}) is ABOVE the NJ TANF (WFNJ) limit (${limit})."

    if "medicaid" in program or "njfamilycare" in program or "familycare" in program:
        if household_size <= 6:
            limit = medicaid_limits.get(household_size)
        else:
            limit = 4963 + (633 * (household_size - 6))
        if monthly_income <= limit:
            return f"✅ LIKELY ELIGIBLE. Household income (${monthly_income}) is BELOW the NJ Medicaid (NJFamilyCare adults 0-138% FPL) limit (${limit}) for {household_size} people."
        else:
            return f"❌ LIKELY INELIGIBLE. Household income (${monthly_income}) is ABOVE the NJ Medicaid limit (${limit})."

    if "ssdi" in program:
        sga = SGA_BLIND_2026 if "blind" in program else SGA_NON_BLIND_2026
        if monthly_income > sga:
            return f"❌ From an earnings standpoint, LIKELY NOT ELIGIBLE. Gross monthly earnings (${monthly_income}) are ABOVE the SSA Substantial Gainful Activity (SGA) limit (${sga}/month). SSDI also requires work credits and medical eligibility."
        else:
            return f"✅ From an earnings standpoint, they may meet the SGA test. Gross monthly earnings (${monthly_income}) are at or below the SGA limit (${sga}/month). SSDI also requires sufficient work credits and medical eligibility (SSA determination)."

    if "ssi" in program and "ssdi" not in program:
        is_couple = household_size >= 2
        max_benefit = SSI_MAX_COUPLE + SSI_NJ_SUPPLEMENT if is_couple else SSI_MAX_INDIVIDUAL + SSI_NJ_SUPPLEMENT
        benefit_label = "couple" if is_couple else "individual"

        countable_income = max(0, monthly_income - 20)

        if countable_income >= max_benefit:
            return (
                f"❌ LIKELY INELIGIBLE for SSI. Countable income (~${countable_income:.0f}/mo after $20 exclusion) "
                f"meets or exceeds the NJ SSI maximum benefit (${max_benefit}/mo for a {benefit_label}). "
                f"SSI also requires resources under $2,000 (individual) or $3,000 (couple), and a qualifying disability or age 65+. "
                f"SSA makes the final determination."
            )
        else:
            return (
                f"✅ POTENTIALLY ELIGIBLE for SSI. Countable income (~${countable_income:.0f}/mo) is below the "
                f"NJ SSI maximum benefit (${max_benefit}/mo for a {benefit_label}, including NJ's ~$32 state supplement). "
                f"Must also have resources under $2,000 (individual) or $3,000 (couple), "
                f"be age 65+ OR have a qualifying disability, and be a U.S. citizen or qualifying non-citizen. "
                f"SSA makes the final determination."
            )

    if "section 8" in program or "section8" in program or "hcv" in program or "housing choice" in program:
        # Match location to known HMFA region
        location_lower = location.lower().strip() if location else ""
        limits = None

        for region, region_limits in section8_limits.items():
            if region in location_lower:
                limits = region_limits
                region_name = region.title()
                break

        # Default to Newark if no match found
        if not limits:
            limits = section8_limits["newark"]
            region_name = "Newark (default — limits vary by county)"

        annual_income = monthly_income * 12
        if household_size <= 8:
            annual_limit = limits.get(household_size)
        else:
            annual_limit = limits[8] + (5000 * (household_size - 8))

        monthly_limit = annual_limit / 12

        if annual_income <= annual_limit:
            return (
                f"✅ LIKELY INCOME-ELIGIBLE for Section 8 HCV. Annual income (~${annual_income:,.0f}) is at or below "
                f"50% AMI for {household_size} people in the {region_name} area (${annual_limit:,}/yr or ~${monthly_limit:,.0f}/mo). "
                f"Eligibility also requires U.S. citizenship or qualifying immigration status, passing a background check, "
                f"and waitlists are often CLOSED — contact the local Housing Authority to apply."
            )
        else:
            return (
                f"❌ LIKELY INCOME-INELIGIBLE for Section 8 HCV. Annual income (~${annual_income:,.0f}) exceeds "
                f"50% AMI for {household_size} people in the {region_name} area (${annual_limit:,}/yr or ~${monthly_limit:,.0f}/mo). "
                f"Contact the local Housing Authority to confirm limits for their specific county."
            )

    return "Error: Unknown benefit program. Currently supporting: SNAP, TANF, Medicaid, SSDI, SSI, Section 8."


# Brave's free tier allows roughly one query per second. A single response makes
# 5-8 search calls, and eval runs fire several responses in parallel, so without
# pacing about half of all searches came back 429 and the model was told "Search
# failed" -- silently degrading every answer that depends on a live lookup.
# Measured before this fix: 3 of 6 back-to-back calls failed; spaced 1.2s, 0 of 6.
_BRAVE_MIN_INTERVAL = 1.2
_brave_lock = threading.Lock()
_brave_last_call = [0.0]


def _brave_throttle():
    """Serialise Brave calls process-wide, at most one per _BRAVE_MIN_INTERVAL."""
    with _brave_lock:
        wait = _BRAVE_MIN_INTERVAL - (time.monotonic() - _brave_last_call[0])
        if wait > 0:
            time.sleep(wait)
        _brave_last_call[0] = time.monotonic()


def web_search_tool(query: str, max_results: int = 4, _max_retries: int = 3):
    """
    Performs a live web search using Brave Search API.

    Paced and retried on 429 -- see _brave_throttle above.
    """

    try:
        # Get API key from environment variable
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key:
            return "Error: BRAVE_API_KEY environment variable not set"
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        }
        
        params = {
            "q": query,
            "count": max_results,
            "safesearch": "moderate"  # Options: off, moderate, strict
        }
        
        for attempt in range(_max_retries):
            _brave_throttle()
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params=params,
                timeout=10
            )
            if response.status_code != 429:
                break
            # Rate limited: back off and try again rather than reporting failure
            # to the model, which makes it withhold resources it could have given.
            time.sleep(_BRAVE_MIN_INTERVAL * (attempt + 1))
        response.raise_for_status()
        
        data = response.json()
        
        # Check if we got results
        results = data.get("web", {}).get("results", [])
        if not results:
            return "No results found."
        
        # Format results nicely for the LLM
        formatted = f"Search results for: {query}\n\n"
        for i, r in enumerate(results[:max_results], 1):
            formatted += f"{i}. {r['title']}\n"
            formatted += f"   URL: {r['url']}\n"
            formatted += f"   {r.get('description', '')}\n"
        
        return formatted
        
    except requests.exceptions.RequestException as e:
        return f"Search failed: {str(e)}"
    except Exception as e:
        return f"Search failed: {str(e)}"

def calculator_tool(expression: str):
    """
    A safe calculator for basic arithmetic. 
    Supports +, -, *, /, and round().
    """
    allowed_chars = "0123456789+-*/(). "
    if any(char not in allowed_chars for char in expression):
        return "Error: Invalid characters. Only numbers and basic math (+-*/) allowed."
    
    try:
        # Evaluate using a restricted scope to prevent code injection
        # (For production, consider libraries like 'simpleeval')
        result = eval(expression, {"__builtins__": None}, {})
        return str(result)
    except Exception as e:
        return f"Error calculating '{expression}': {str(e)}"