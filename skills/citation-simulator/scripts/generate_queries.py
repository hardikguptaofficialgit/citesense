#!/usr/bin/env python3
"""generate_queries.py -- deterministic query generation for the citation simulator.
Generates the QUESTIONS only; answering them requires the calling agent's own live
search/fetch tools (see SKILL.md). Usage: python3 generate_queries.py '<json ground-truth facts>'"""
import sys, json

def build_queries(facts):
    name = facts.get("brand_name", "the brand")
    category = facts.get("category", "").strip()
    location = facts.get("location", "").strip()
    category_phrase = f" ({category})" if category else ""
    location_phrase = f" in {location}" if location else ""
    queries = [
        {"category": "identity", "query": f"What is {name}{category_phrase}?"},
        {"category": "offering", "query": f"What products or services does {name} offer?"},
    ]
    key_facts = facts.get("key_facts", {}) or {}
    # Do not manufacture transactional or ownership expectations for an informational,
    # public-sector, or open-source entity. Each question must test a confirmed site fact.
    if key_facts.get("owner") or key_facts.get("ownership"): queries.append({"category":"identity","query":f"Who owns or governs {name}?"})
    if key_facts.get("pricing") or key_facts.get("price"): queries.append({"category":"transactional","query":f"How much does {name} cost?"})
    if key_facts.get("return_policy") or key_facts.get("cancellation_policy"): queries.append({"category":"transactional","query":f"What is {name}'s return or cancellation policy?"})
    if key_facts.get("contact") or location: queries.append({"category":"transactional","query":f"How do I contact {name}{location_phrase}?"})
    if key_facts.get("differentiator") or key_facts.get("competitors"): queries.append({"category":"differentiation","query":f"How does {name} compare to alternatives?"})
    if key_facts.get("reviews") or key_facts.get("certification"): queries.append({"category":"credibility","query":f"What independent evidence supports {name}'s credibility?"})
    return queries

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: generate_queries.py '<json ground-truth facts>'"})); sys.exit(1)
    try:
        facts = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON input: {e}"})); sys.exit(1)
    print(json.dumps({"brand_name": facts.get("brand_name"), "queries": build_queries(facts)}, indent=2))

if __name__ == "__main__":
    main()
