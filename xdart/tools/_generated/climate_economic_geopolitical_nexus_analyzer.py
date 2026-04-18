TOOL_META = {
    "name": "climate_economic_geopolitical_nexus_analyzer",
    "version": "1.0",
    "purpose": "To identify and analyze the nexus between climate events, economic data, and geopolitical stability by processing world events and indicators.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}

def run(context: dict) -> dict:
    import json
    import re
    from collections import defaultdict, Counter
    
    events = context.get("events", [])
    indicators = context.get("indicators", [])
    problem = context.get("problem", "")
    
    # Keywords for climate-related events
    climate_keywords = ["climate", "weather", "drought", "flood", "temperature", "environment", "ecological", "resource scarcity", "water", "agriculture", "sahel", "africa"]
    # Keywords for geopolitical stability
    geo_keywords = ["stability", "instability", "conflict", "war", "sanctions", "diplomatic", "political", "regime", "government", "unrest"]
    # Relevant economic indicators (based on FRED data)
    econ_indicators_of_interest = ["CPIAUCSL", "GDP", "UNRATE", "DGS10", "T10YIE", "FEDFUNDS"]
    
    # Filter events
    climate_events = []
    geo_events = []
    for event in events:
        headline = event.get("headline", "").lower()
        summary = event.get("summary", "").lower() if event.get("summary") else ""
        text = headline + " " + summary
        if any(keyword in text for keyword in climate_keywords):
            climate_events.append(event)
        if any(keyword in text for keyword in geo_keywords):
            geo_events.append(event)
    
    # Filter indicators
    econ_data = []
    for ind in indicators:
        if ind.get("indicator") in econ_indicators_of_interest:
            econ_data.append(ind)
    
    # Analyze and summarize
    output_lines = []
    output_lines.append("Climate-Economic-Geopolitical Nexus Analysis:")
    output_lines.append(f"- Number of climate-related events: {len(climate_events)}")
    output_lines.append(f"- Number of geopolitical events: {len(geo_events)}")
    output_lines.append(f"- Relevant economic indicators found: {len(econ_data)}")
    
    # Extract sample data for context
    if climate_events:
        sample_climate = [e.get("headline", "N/A") for e in climate_events[:3]]
        output_lines.append(f"  Sample climate events: {sample_climate}")
    if geo_events:
        sample_geo = [e.get("headline", "N/A") for e in geo_events[:3]]
        output_lines.append(f"  Sample geopolitical events: {sample_geo}")
    if econ_data:
        sample_econ = [(i.get("indicator", "N/A"), i.get("value", "N/A")) for i in econ_data[:3]]
        output_lines.append(f"  Sample economic indicators: {sample_econ}")
    
    # Check problem relevance
    if "climate" in problem.lower() or "sahel" in problem.lower():
        output_lines.append("Problem directly involves climate or Sahel region, enhancing relevance of this analysis.")
    
    output_text = "\n".join(output_lines)
    
    metadata = {
        "climate_event_count": len(climate_events),
        "geo_event_count": len(geo_events),
        "econ_indicator_count": len(econ_data),
        "problem_keywords_matched": "climate" in problem.lower() or "sahel" in problem.lower()
    }
    
    return {
        "tool_name": TOOL_META["name"],
        "output": output_text,
        "metadata": metadata
    }
