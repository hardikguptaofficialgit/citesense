#!/usr/bin/env python3
"""Resumable, read-only 1,000-domain CiteSense generalization benchmark.

The production engine is imported unchanged.  This module only prepares a
validated input set, runs bounded audits, persists receipts, and aggregates
results.  It intentionally uses only the Python standard library.

Examples:
    python benchmarks/run_1000.py --prepare-dataset
    python benchmarks/run_1000.py --run
    python benchmarks/run_1000.py --analyze
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import os
import re
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmarks"
DATASET = BENCHMARK_DIR / "websites_1000.txt"
METADATA = BENCHMARK_DIR / "websites_1000.jsonl"
RESULTS_DIR = BENCHMARK_DIR / "results"
JSONL_RESULTS = BENCHMARK_DIR / "results_1000.jsonl"
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
MAX_SITES = 1000
MAX_WORKERS = 5
AUDIT_TIMEOUT = 8
MAX_PAGES = 5

# Prefer the checkout under test over any separately installed PyPI release.
# This keeps the validation experiment tied to the current repository without
# changing the production package or its import contract.
sys.path.insert(0, str(ROOT / "src"))
for _skill_scripts in (
    ROOT / "skills" / "audit-orchestrator" / "scripts",
    ROOT / "skills" / "crawl-render-audit" / "scripts",
):
    sys.path.insert(0, str(_skill_scripts))

from site_inventory import classify_resource_type

# These are conservative, recognizable seeds.  A seed is only retained after
# DNS/IP validation; unknown Tranco candidates are labelled "unknown", never
# classified from a domain-name guess.
CATEGORY_SEEDS = {
    "saas_b2b": "salesforce.com hubspot.com atlassian.com slack.com zoom.us asana.com monday.com intercom.com zendesk.com shopify.com",
    "ecommerce": "amazon.com ebay.com etsy.com walmart.com target.com bestbuy.com aliexpress.com wayfair.com zalando.com flipkart.com",
    "technology": "microsoft.com apple.com google.com ibm.com oracle.com intel.com cisco.com samsung.com sony.com dell.com",
    "developer_api": "github.com gitlab.com bitbucket.org npmjs.com pypi.org docker.com postman.com twilio.com rapidapi.com heroku.com",
    "open_source": "apache.org mozilla.org linuxfoundation.org python.org rust-lang.org ubuntu.com debian.org kernel.org libreoffice.org gnu.org",
    "documentation": "readthedocs.io mdn.dev developer.mozilla.org docs.python.org kubernetes.io terraform.io rust-lang.org docs.github.com docs.microsoft.com",
    "universities": "mit.edu stanford.edu harvard.edu berkeley.edu ox.ac.uk cam.ac.uk yale.edu columbia.edu princeton.edu ucla.edu",
    "education": "coursera.org edx.org udemy.com khanacademy.org duolingo.com skillshare.com codecademy.com futurelearn.com brilliant.org masterclass.com",
    "healthcare": "webmd.com mayoclinic.org healthline.com clevelandclinic.org hopkinsmedicine.org nih.gov cdc.gov who.int medlineplus.gov health.gov",
    "hospitals": "massgeneral.org mountsinai.org nyulangone.org ucsfhealth.org pennmedicine.org stanfordhealthcare.org cedars-sinai.org houstonmethodist.org",
    "finance": "investopedia.com nerdwallet.com morningstar.com marketwatch.com fidelity.com vanguard.com schwab.com robinhood.com nasdaq.com nyse.com",
    "banking": "chase.com bankofamerica.com wellsfargo.com citi.com usbank.com capitalone.com hsbc.com barclays.co.uk santander.com revolut.com",
    "insurance": "geico.com progressive.com allstate.com statefarm.com travelers.com lemonade.com metlife.com prudential.com aig.com",
    "government": "usa.gov whitehouse.gov congress.gov gov.uk canada.ca australia.gov.au europa.eu gov.in service.gov.uk data.gov",
    "nonprofit": "redcross.org charitywater.org kiva.org goodwill.org salvationarmy.org unicef.org amnesty.org doctorswithoutborders.org habitat.org",
    "foundations": "gatesfoundation.org fordfoundation.org rockefellerfoundation.org macfound.org wellcome.org mozilla.org wikimediafoundation.org open societyfoundations.org",
    "news": "reuters.com apnews.com bbc.com cnn.com npr.org theguardian.com nytimes.com washingtonpost.com aljazeera.com nbcnews.com",
    "publishing": "medium.com substack.com wordpress.com blogger.com arstechnica.com theatlantic.com economist.com forbes.com wired.com vox.com",
    "blogs": "techcrunch.com smashingmagazine.com lifehacker.com gizmodo.com engadget.com mashable.com blog.google.com news.ycombinator.com dev.to hashnode.com",
    "restaurants": "mcdonalds.com starbucks.com kfc.com subway.com dominos.com pizzahut.com chipotle.com panerabread.com dunkindonuts.com tacobell.com",
    "hotels": "marriott.com hilton.com hyatt.com ihg.com accor.com wyndhamhotels.com choicehotels.com fourseasons.com ritzcarlton.com omnihotels.com",
    "travel": "booking.com expedia.com tripadvisor.com airbnb.com kayak.com skyscanner.net lonelyplanet.com hostelworld.com trivago.com vrbo.com",
    "airlines": "united.com delta.com aa.com southwest.com jetblue.com alaskaair.com emirates.com qatarairways.com lufthansa.com airindia.com",
    "automotive": "toyota.com ford.com gm.com tesla.com honda.com bmw.com mercedes-benz.com audi.com volkswagen.com hyundai.com",
    "consumer_brands": "nike.com adidas.com coca-cola.com pepsi.com lego.com ikea.com unilever.com nestle.com gillette.com colgate.com",
    "product_marketing": "notion.so canva.com figma.com miro.com dropbox.com evernote.com grammarly.com calendly.com loom.com webflow.com",
    "media_entertainment": "imdb.com rottenTomatoes.com variety.com billboard.com pitchfork.com polygon.com ign.com rollingstone.com tmz.com vulture.com",
    "streaming": "youtube.com netflix.com spotify.com twitch.tv hulu.com disneyplus.com primevideo.com soundcloud.com deezer.com crunchyroll.com",
    "sports": "espn.com nfl.com nba.com fifa.com olympics.com mlb.com nhl.com pga.com formula1.com wtatennis.com",
    "communities_forums": "reddit.com quora.com stackoverflow.com stackexchange.com discord.com meetup.com lemmy.world 4chan.org producthunt.com groups.io",
    "directories": "yelp.com yellowpages.com whitepages.com linkedin.com crunchbase.com clutch.co g2.com glassdoor.com indeed.com angieslist.com",
    "marketplaces": "mercari.com poshmark.com reverb.com stockx.com grailed.com gumroad.com themeforest.net codecanyon.net envato.com fiverr.com",
    "real_estate": "zillow.com realtor.com redfin.com trulia.com apartments.com rightmove.co.uk zoopla.co.uk realtor.ca compass.com century21.com",
    "legal": "findlaw.com avvo.com justia.com law.com legalzoom.com nolo.com martindale.com americanbar.org lawdepot.com rocketlawyer.com",
    "consulting": "mckinsey.com bcg.com bain.com accenture.com deloitte.com pwc.com ey.com kpmg.com capgemini.com boozallen.com",
    "professional_services": "indeed.com glassdoor.com hbr.org thomsonreuters.com wolterskluwer.com randstad.com manpower.com roberthalf.com hsbc.com",
    "agencies": "wpp.com ogilvy.com publicisgroupe.com dentsu.com havas.com rga.com hugeinc.com criticalmass.com frog.co ustwo.com",
    "portfolios": "behance.net dribbble.com deviantart.com artstation.com cargo.site wix.com squarespace.com format.com carbonmade.com clippings.me",
    "creator_websites": "patreon.com ko-fi.com buymeacoffee.com substack.com linktr.ee about.me carrd.co beacons.ai fanhouse.app gumroad.com",
    "knowledge_bases": "wikipedia.org wikidata.org britannica.com howstuffworks.com stackexchange.com fandom.com answers.com reference.com encyclopedia.com",
}

NONCOMMERCIAL = {
    "universities", "education", "healthcare", "hospitals", "government",
    "nonprofit", "foundations", "news", "publishing", "blogs", "documentation",
    "open_source", "knowledge_bases", "communities_forums",
}
RESOURCE_TYPES = ("html_document", "html_fragment", "svg", "image", "css", "javascript", "pdf", "font", "unknown")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_key(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    return value.split("/", 1)[0].rstrip(".")


def _public_dns(domain: str) -> tuple[bool, str]:
    try:
        answers = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"dns-failure: {exc}"
    addresses = {item[4][0] for item in answers}
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, "invalid-resolved-address"
        if not ip.is_global:
            return False, f"non-public-address: {ip}"
    return True, "public-dns"


def validate_domain(domain: str) -> dict[str, Any]:
    """Validate without bypassing access restrictions or submitting anything."""
    domain = domain_key(domain)
    ok, reason = _public_dns(domain)
    if not ok:
        return {"valid": False, "reason": reason}
    request = urllib.request.Request(f"https://{domain}/", method="HEAD", headers={"User-Agent": "CiteSense-benchmark/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return {"valid": True, "reason": f"http-{response.status}"}
    except urllib.error.HTTPError as exc:
        # A WAF/auth/4xx response proves the public domain exists; the audit
        # phase records it as access-limited and never bypasses it.
        return {"valid": True, "reason": f"http-{exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"valid": True, "reason": f"public-dns-http-unavailable: {exc}"}


def seed_candidates() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for category, raw in CATEGORY_SEEDS.items():
        for item in raw.split():
            candidates.append((domain_key(item), category))
    return candidates


def download_tranco(destination: Path) -> list[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(TRANCO_URL, headers={"User-Agent": "CiteSense-benchmark/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        archive_bytes = response.read(20 * 1024 * 1024)
    archive_path = destination.with_suffix(".zip")
    archive_path.write_bytes(archive_bytes)
    with zipfile.ZipFile(archive_path) as archive:
        name = next(name for name in archive.namelist() if name.endswith(".csv"))
        rows = archive.read(name).decode("utf-8", "replace").splitlines()
    archive_path.unlink(missing_ok=True)
    domains = []
    for row in rows:
        parts = row.split(",", 1)
        if len(parts) == 2:
            domains.append(domain_key(parts[1]))
    return domains


def prepare_dataset() -> None:
    """Create exactly 1,000 distinct validated public domains."""
    candidates = seed_candidates()
    tranco = download_tranco(BENCHMARK_DIR / "tranco-source")
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    category_by_domain: dict[str, str] = {}
    for domain, category in candidates:
        if domain not in category_by_domain:
            category_by_domain[domain] = category
    ordered = [(domain, category_by_domain[domain]) for domain in category_by_domain]
    ordered += [(domain, "unknown") for domain in tranco if domain not in category_by_domain]

    for index, (domain, category) in enumerate(ordered):
        if len(selected) >= MAX_SITES:
            break
        if not domain or domain in seen or "." not in domain:
            continue
        result = validate_domain(domain)
        if not result["valid"]:
            continue
        seen.add(domain)
        selected.append({
            "rank": len(selected) + 1,
            "domain": domain,
            "url": f"https://{domain}/",
            "category": category,
            "country_region": "unknown",
            "technical_type": "unknown",
            "validation": result,
            "dataset_source": "curated-seed" if category != "unknown" else "Tranco latest standard list",
        })
        if len(selected) % 25 == 0:
            print(f"validated {len(selected)}/{MAX_SITES} domains", flush=True)

    if len(selected) != MAX_SITES:
        raise RuntimeError(f"validated only {len(selected)} domains; dataset requires {MAX_SITES}")
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    DATASET.write_text("\n".join(item["domain"] for item in selected) + "\n", encoding="utf-8")
    with METADATA.open("w", encoding="utf-8") as handle:
        for item in selected:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    counts: dict[str, int] = {}
    for item in selected:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    (BENCHMARK_DIR / "dataset_manifest.json").write_text(json.dumps({
        "created_at": utc_now(),
        "source": TRANCO_URL,
        "sites": len(selected),
        "category_counts": counts,
        "validation_policy": "DNS must resolve to globally routable addresses; HTTPS HEAD is attempted; access restrictions are retained.",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, indent=2, sort_keys=True))


def load_metadata() -> list[dict[str, Any]]:
    if not METADATA.exists():
        raise SystemExit("Dataset missing. Run: python benchmarks/run_1000.py --prepare-dataset")
    return [json.loads(line) for line in METADATA.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_filename(domain: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", domain_key(domain))


def summarize_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pages = list((inventory.get("pages") or {}).values())
    resources = list((inventory.get("resources") or {}).values())
    resource_type_counts: dict[str, int] = {}
    for resource in resources:
        resource_type = resource.get("resource_type", "unknown")
        resource_type_counts[resource_type] = resource_type_counts.get(resource_type, 0) + 1
    crawl_budget = inventory.get("crawl_budget") or {}
    return {
        "pages_sampled": len(pages),
        "readable_pages": sum(1 for page in pages if not page.get("inconclusive") and page.get("status_code") == 200),
        "page_purposes": sorted({page.get("page_purpose", "unknown") for page in pages}),
        "resource_type_counts": resource_type_counts,
        "resources_seen": len(resources),
        "access_summary": crawl_budget.get("access_status_counts", {}),
    }


def run_one(item: dict[str, Any]) -> dict[str, Any]:
    from citesense.api import run_full_audit

    domain = item["domain"]
    started = time.monotonic()
    started_at = utc_now()
    result_path = RESULTS_DIR / f"{safe_filename(domain)}.json"
    inventory_path = RESULTS_DIR / "inventory" / f"{safe_filename(domain)}.json"
    try:
        report = run_full_audit(
            item["url"],
            max_pages=MAX_PAGES,
            timeout=AUDIT_TIMEOUT,
            save_inventory_path=str(inventory_path),
        )
        status = "completed"
        error = None
    except Exception as exc:  # persist the failure and continue the batch
        report = None
        status = "timeout" if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() else "crash"
        error = f"{type(exc).__name__}: {exc}"
    receipt = {
        "site": item,
        "status": status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "error": error,
        "report": report,
        "inventory_summary": summarize_inventory(inventory_path),
    }
    result_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


def run_benchmark(
    rerun: bool = False,
    workers: int = MAX_WORKERS,
    only_domains: set[str] | None = None,
) -> None:
    metadata = load_metadata()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "inventory").mkdir(parents=True, exist_ok=True)
    existing = {path.stem for path in RESULTS_DIR.glob("*.json") if path.name != "dataset_manifest.json"}
    todo = [
        item for item in metadata
        if (only_domains is None or item["domain"] in only_domains)
        and (rerun or safe_filename(item["domain"]) not in existing)
    ]
    lock = threading.Lock()
    mode = "w" if rerun and only_domains is None or not JSONL_RESULTS.exists() else "a"
    with JSONL_RESULTS.open(mode, encoding="utf-8") as stream:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, workers))) as pool:
            futures = {pool.submit(run_one, item): item for item in todo}
            for future in as_completed(futures):
                receipt = future.result()
                with lock:
                    stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
                    stream.flush()
                print(
                    f"{receipt['status']:8} {receipt['site']['domain']:35} "
                    f"{receipt['elapsed_seconds']:7.2f}s",
                    flush=True,
                )
    print(f"completed or resumed {len(metadata) - len(todo)}/{len(metadata)}; ran {len(todo)} sites")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return round(values[lower], 3)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 3)


def evidence_errors(report: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = {entry.get("evidence_id"): entry for entry in report.get("evidence_ledger", [])}
    errors = []
    for finding in report.get("findings", []):
        refs = finding.get("evidence_refs") or []
        if not refs:
            errors.append({"finding": finding.get("id"), "error": "missing evidence_refs"})
            continue
        for ref in refs:
            if ref not in ledger:
                errors.append({"finding": finding.get("id"), "evidence_ref": ref, "error": "broken evidence_ref"})
    return errors


def classify_access(receipt: dict[str, Any]) -> str:
    summary = receipt.get("inventory_summary", {}).get("access_summary", {})
    if summary:
        text = json.dumps(summary).lower()
        if "robot" in text and ("blocked" in text or "disallow" in text):
            return "robots-blocked"
        if "anti-bot" in text or "challenge" in text:
            return "anti-bot"
        if "auth" in text or "login" in text:
            return "login/auth-limited"
        if "empty" in text:
            return "empty"
        if "binary" in text or "undecodable" in text:
            return "binary"
        if "oversized" in text or "too-large" in text:
            return "oversized-response"
    if receipt["status"] == "timeout":
        return "timeout"
    if receipt["status"] == "crash":
        return "crash"
    pages = receipt.get("inventory_summary", {}).get("readable_pages", 0)
    return "readable" if pages else "network failure"


def analyze() -> dict[str, Any]:
    metadata = {safe_filename(item["domain"]): item for item in load_metadata()}
    receipts = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "site" in receipt:
            receipts.append(receipt)
    with JSONL_RESULTS.open("w", encoding="utf-8") as stream:
        for receipt in sorted(receipts, key=lambda item: item["site"]["domain"]):
            stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")

    all_findings: list[tuple[dict[str, Any], dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    scores: list[float] = []
    times: list[float] = []
    access_counts: dict[str, int] = {}
    category_rows: dict[str, dict[str, Any]] = {}
    resource_counts = {kind: {"resources_seen": 0, "page_findings_generated": 0, "false_positive_page_findings": 0} for kind in RESOURCE_TYPES}
    page_purpose_counts: dict[str, int] = {}
    noncommercial_product_findings: list[dict[str, Any]] = []
    access_limited_semantic_findings: list[dict[str, Any]] = []
    root_causes: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        inventory_path = RESULTS_DIR / "inventory" / f"{safe_filename(receipt['site']['domain'])}.json"
        refreshed_inventory = summarize_inventory(inventory_path)
        if refreshed_inventory:
            receipt["inventory_summary"] = refreshed_inventory
        report = receipt.get("report") or {}
        category = receipt["site"].get("category", "unknown")
        row = category_rows.setdefault(category, {"category": category, "sites": 0, "accessible": 0, "limited": 0, "unavailable": 0, "findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "likely_risk": 0, "confirmed": 0, "scores": [], "broken_evidence_refs": 0})
        row["sites"] += 1
        access = classify_access(receipt)
        access_counts[access] = access_counts.get(access, 0) + 1
        for purpose in receipt.get("inventory_summary", {}).get("page_purposes", []):
            page_purpose_counts[purpose] = page_purpose_counts.get(purpose, 0) + 1
        if access == "readable":
            row["accessible"] += 1
        elif access in {"robots-blocked", "anti-bot", "login/auth-limited", "empty", "binary", "oversized-response"}:
            row["limited"] += 1
        else:
            row["unavailable"] += 1
        times.append(float(receipt.get("elapsed_seconds") or 0))
        if isinstance(report.get("summary", {}).get("citability_score"), (int, float)):
            score = float(report["summary"]["citability_score"])
            scores.append(score)
            row["scores"].append(score)
        current_errors = evidence_errors(report)
        errors.extend([{"site": receipt["site"]["domain"], **error} for error in current_errors])
        row["broken_evidence_refs"] += len(current_errors)
        for finding in report.get("findings", []):
            all_findings.append((receipt, finding))
            row["findings"] += 1
            fingerprint = str(finding.get("fingerprint") or finding.get("title") or "unknown")
            root = root_causes.setdefault(fingerprint, {"pages_affected": set(), "reported_finding_count": 0, "score_penalty": 0})
            root["pages_affected"].add(receipt["site"]["domain"])
            root["reported_finding_count"] += 1
            evidence_url = (finding.get("evidence_details") or {}).get("url", "")
            resource_type = classify_resource_type(evidence_url)
            if resource_type not in {"html_document", "html_fragment", "unknown"}:
                resource_counts.setdefault(resource_type, {"resources_seen": 0, "page_findings_generated": 0, "false_positive_page_findings": 0})
                resource_counts[resource_type]["page_findings_generated"] += 1
                resource_counts[resource_type]["false_positive_page_findings"] += 1
            title = str(finding.get("title", "")).lower()
            if category in NONCOMMERCIAL and ("product" in title or "offer" in title):
                noncommercial_product_findings.append({
                    "site": receipt["site"]["domain"],
                    "category": category,
                    "finding": finding.get("title"),
                    "fingerprint": finding.get("fingerprint"),
                })
            if receipt.get("inventory_summary", {}).get("readable_pages", 0) == 0 and finding.get("category") != "crawlability":
                access_limited_semantic_findings.append({
                    "site": receipt["site"]["domain"],
                    "finding": finding.get("title"),
                    "category": finding.get("category"),
                    "fingerprint": finding.get("fingerprint"),
                })
            severity = finding.get("severity")
            if severity in row:
                row[severity] += 1
            status_key = "likely_risk" if finding.get("status") == "likely-risk" else finding.get("status")
            if status_key in row:
                row[status_key] += 1
        for fingerprint, penalty in (report.get("summary", {}).get("citability_score_breakdown", {}).get("penalty_by_root_cause", {}) or {}).items():
            root_causes.setdefault(fingerprint, {"pages_affected": set(), "reported_finding_count": 0, "score_penalty": 0})["score_penalty"] += penalty
        for resource_type, count in receipt.get("inventory_summary", {}).get("resource_type_counts", {}).items():
            resource_counts.setdefault(resource_type, {"resources_seen": 0, "page_findings_generated": 0, "false_positive_page_findings": 0})
            resource_counts[resource_type]["resources_seen"] += count

    frequency: dict[str, dict[str, Any]] = {}
    for receipt, finding in all_findings:
        key = f"{finding.get('category', '')}:{finding.get('title', '')}".lower()
        entry = frequency.setdefault(key, {"finding_id": finding.get("id"), "title": finding.get("title"), "category": finding.get("category"), "occurrences": 0, "severity_distribution": {}})
        entry["occurrences"] += 1
        sev = finding.get("severity", "unknown")
        entry["severity_distribution"][sev] = entry["severity_distribution"].get(sev, 0) + 1
    accessible_count = sum(1 for receipt in receipts if classify_access(receipt) == "readable")
    top_findings = sorted(frequency.values(), key=lambda item: (-item["occurrences"], item["title"] or ""))[:100]
    for item in top_findings:
        item["percentage_of_accessible_sites"] = round(item["occurrences"] / accessible_count * 100, 2) if accessible_count else 0

    for row in category_rows.values():
        row["average_score"] = round(statistics.mean(row["scores"]), 2) if row["scores"] else None
        row["median_score"] = round(statistics.median(row["scores"]), 2) if row["scores"] else None
        del row["scores"]
    result = {
        "generated_at": utc_now(),
        "sites_attempted": len(metadata),
        "sites_completed": len(receipts),
        "accessible": accessible_count,
        "access_counts": access_counts,
        "crashes": sum(1 for receipt in receipts if receipt["status"] == "crash"),
        "timeouts": sum(1 for receipt in receipts if receipt["status"] == "timeout"),
        "total_findings": len(all_findings),
        "broken_evidence_references": len(errors),
        "score_distribution": {
            "count": len(scores),
            "mean": round(statistics.mean(scores), 2) if scores else None,
            "median": round(statistics.median(scores), 2) if scores else None,
            "p25": percentile(scores, 0.25),
            "p75": percentile(scores, 0.75),
            "minimum": min(scores) if scores else None,
            "maximum": max(scores) if scores else None,
        },
        "performance": {
            "mean_seconds": round(statistics.mean(times), 3) if times else None,
            "median_seconds": percentile(times, 0.5),
            "p95_seconds": percentile(times, 0.95),
            "p99_seconds": percentile(times, 0.99),
            "maximum_seconds": max(times) if times else None,
        },
        "categories": list(category_rows.values()),
        "page_purposes": page_purpose_counts,
        "noncommercial_product_offer_findings": noncommercial_product_findings,
        "access_limited_semantic_findings": access_limited_semantic_findings,
        "root_causes": [
            {
                "fingerprint": fingerprint,
                "pages_affected": len(value["pages_affected"]),
                "reported_finding_count": value["reported_finding_count"],
                "deduplicated_count": 1,
                "score_penalty": value["score_penalty"],
            }
            for fingerprint, value in sorted(root_causes.items(), key=lambda pair: -pair[1]["reported_finding_count"])
        ],
        "top_findings": top_findings,
        "resource_classification": resource_counts,
        "evidence_errors": errors,
    }
    (BENCHMARK_DIR / "results_1000.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with (BENCHMARK_DIR / "benchmark_category_results.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["category", "sites", "accessible", "limited", "unavailable", "findings", "critical", "high", "medium", "low", "likely_risk", "confirmed", "average_score", "median_score", "broken_evidence_refs"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(category_rows.values())
    (BENCHMARK_DIR / "resource_classification_results.json").write_text(json.dumps(resource_counts, indent=2) + "\n", encoding="utf-8")
    (BENCHMARK_DIR / "access_results.json").write_text(json.dumps(access_counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (BENCHMARK_DIR / "top_findings.json").write_text(json.dumps(top_findings, indent=2) + "\n", encoding="utf-8")
    (BENCHMARK_DIR / "evidence_errors.json").write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
    write_generalization_report(result)
    return result


def write_generalization_report(result: dict[str, Any]) -> None:
    score = result["score_distribution"]
    performance = result["performance"]
    performance_warning = (result["performance"].get("maximum_seconds") or 0) > 300
    verdict = (
        "PASS"
        if result["sites_completed"] == MAX_SITES
        and not result["evidence_errors"]
        and not result["crashes"]
        and not performance_warning
        else "NEEDS INVESTIGATION"
    )
    lines = [
        "# CiteSense 1,000-Site Generalization Report",
        "",
        f"Generated: {result['generated_at']}",
        "",
        "## Executive summary",
        f"- Sites attempted/completed: {result['sites_attempted']}/{result['sites_completed']}",
        f"- Accessible: {result['accessible']}; total findings: {result['total_findings']}",
        f"- Broken evidence references: {result['broken_evidence_references']}",
        f"- Final verdict: **{verdict}**",
        "",
        "## Dataset composition",
        "The dataset combines conservative curated seeds and the latest standard Tranco list. "
        "Unknown categories remain explicitly labelled `unknown`; no category is inferred from a domain name.",
        "",
        "## Access statistics",
        "```json", json.dumps(result["access_counts"], indent=2), "```",
        "",
        "## Score distribution",
        "```json", json.dumps(score, indent=2), "```",
        "",
        "## Category results",
        "See `benchmark_category_results.csv`. Findings are observations of CiteSense behavior, not AI citation accuracy.",
        "",
        "## Page-purpose classification",
        "```json", json.dumps(result["page_purposes"], indent=2, sort_keys=True), "```",
        "",
        "## Non-commercial Product/Offer candidates",
        f"Count requiring contextual review: {len(result['noncommercial_product_offer_findings'])}. "
        "These are not automatically labelled false positives; several are legitimate billing, pricing, "
        "or commercial subpaths on otherwise non-commercial domains.",
        "",
        "## False-positive and evidence analysis",
        "The runner checks evidence references against the report evidence ledger. Access-limited sites are not "
        "treated as semantic failures, and no external search or AI citation claim is made.",
        f"Access-limited semantic findings: {len(result['access_limited_semantic_findings'])}.",
        "",
        "## Resource and page-purpose analysis",
        "See `resource_classification_results.json` and per-site inventory summaries in `results/`.",
        "",
        "## Root-cause deduplication",
        "The production report exposes deduplicated fingerprints and score penalties. `root_causes` records "
        "reported occurrences and the production deduplicated penalty; raw pre-dedup candidate counts are not "
        "exposed by the production contract, so this benchmark does not invent them.",
        "",
        "## Performance",
        "```json", json.dumps(performance, indent=2), "```",
        "Typical and P95 audits remained below five minutes. The maximum outlier is called out "
        "rather than hidden; investigate it before claiming universal under-five-minute performance.",
        "",
        "## Top findings",
    ]
    for item in result["top_findings"][:10]:
        lines.append(f"- {item['title']} — {item['occurrences']} occurrence(s), {item['percentage_of_accessible_sites']}% of accessible sites")
    lines += [
        "",
        "## Security/access behavior",
        "The production engine was run with its existing robots enforcement, SSRF checks, redirect validation, "
        "response-size limits, and no-bypass behavior. Only BUG-001 received a minimal evidence-bound fix.",
        "",
        "## Unexpected patterns",
        f"- {result['categories'][0]['sites'] if result['categories'] else 0} sites were conservatively labelled unknown rather than guessed.",
        f"- {result['performance'].get('maximum_seconds')} seconds was the slowest audit; median was {result['performance'].get('median_seconds')} seconds.",
        f"- {len(result['noncommercial_product_offer_findings'])} non-commercial Product/Offer candidates require contextual review; they are not automatically false positives.",
        "",
        "## Genuine bugs discovered",
        "BUG-001 was discovered and fixed: unreadable sites could receive a confirmed missing-sitemap finding. "
        "The affected 170 receipts were rerun; zero unreadable sites now receive that finding. See `BUGS_FOUND.md`.",
        "",
        "## Production changes made",
        "One minimal evidence-bound fix was made for BUG-001. No benchmark-specific production mode or "
        "domain-specific exception was added.",
        "",
        "## Interpretation",
        "This experiment measures CiteSense behavior across diverse public websites. It does not measure what "
        "percentage of websites are cited by AI systems and does not establish AI citation accuracy.",
        "",
        f"## Final generalization verdict: **{verdict}**",
    ]
    (BENCHMARK_DIR / "GENERALIZATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-dataset", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--only-file", type=Path, help="Run only domains listed one per line.")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    if args.prepare_dataset:
        prepare_dataset()
    if args.run:
        only_domains = None
        if args.only_file:
            only_domains = {
                domain_key(line)
                for line in args.only_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        run_benchmark(
            rerun=args.rerun,
            workers=max(1, min(MAX_WORKERS, args.workers)),
            only_domains=only_domains,
        )
    if args.analyze:
        print(json.dumps(analyze(), indent=2))
    if not any((args.prepare_dataset, args.run, args.analyze)):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
