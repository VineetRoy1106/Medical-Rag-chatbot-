"""
Curalink Pipeline — Stage 2: Parallel Retrieval
Fetches from PubMed, OpenAlex, and ClinicalTrials.gov simultaneously.
Treats all results as a flat unranked pool — API rank order is ignored.
"""

import os
import asyncio
import hashlib
import httpx
import xmltodict
from typing import List, Tuple
from models.schemas import (
    PublicationMetadata, ClinicalTrialMetadata,
    DataSource, StudySubject, TrialStatus,
    TrialEligibility, TrialLocation, TrialContact
)
from observability.langsmith import traced

PUBMED_BASE   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE = "https://api.openalex.org"
TRIALS_BASE   = "https://clinicaltrials.gov/api/v2"
PUBMED_KEY    = os.getenv("PUBMED_API_KEY", "")


def _make_id(source: str, raw_id: str) -> str:
    return hashlib.md5(f"{source}:{raw_id}".encode()).hexdigest()[:12]


# ── PubMed ────────────────────────────────────────────────────────────────

async def _pubmed_fetch(client: httpx.AsyncClient, query: str, max_results: int = 50) -> List[PublicationMetadata]:
    papers = []
    try:
        # Step 1: search for IDs
        search_url = f"{PUBMED_BASE}/esearch.fcgi"
        params = {
            "db":      "pubmed",
            "term":    query,
            "retmax":  max_results,
            "sort":    "pub date",
            "retmode": "json",
        }
        if PUBMED_KEY:
            params["api_key"] = PUBMED_KEY

        r = await client.get(search_url, params=params, timeout=15)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        # Step 2: fetch full records
        fetch_url = f"{PUBMED_BASE}/efetch.fcgi"
        fetch_params = {
            "db":      "pubmed",
            "id":      ",".join(ids),
            "retmode": "xml",
        }
        if PUBMED_KEY:
            fetch_params["api_key"] = PUBMED_KEY

        r2 = await client.get(fetch_url, params=fetch_params, timeout=20)
        r2.raise_for_status()
        data = xmltodict.parse(r2.text)

        articles = data.get("PubmedArticleSet", {}).get("PubmedArticle", [])
        if isinstance(articles, dict):
            articles = [articles]

        for article in articles:
            try:
                medline  = article.get("MedlineCitation", {})
                art_data = medline.get("Article", {})

                # Title
                title = art_data.get("ArticleTitle", "")
                if isinstance(title, dict):
                    title = title.get("#text", "")

                # Abstract
                abstract_data = art_data.get("Abstract", {}).get("AbstractText", "")
                if isinstance(abstract_data, list):
                    abstract = " ".join(
                        (a.get("#text", a) if isinstance(a, dict) else a)
                        for a in abstract_data
                    )
                elif isinstance(abstract_data, dict):
                    abstract = abstract_data.get("#text", "")
                else:
                    abstract = abstract_data or ""

                if not abstract or len(abstract) < 50:
                    continue

                # Authors
                author_list = art_data.get("AuthorList", {}).get("Author", [])
                if isinstance(author_list, dict):
                    author_list = [author_list]
                authors = []
                for a in author_list[:8]:
                    ln = a.get("LastName", "")
                    fn = a.get("ForeName", "")
                    if ln:
                        authors.append(f"{ln} {fn}".strip())

                # Year
                pub_date = art_data.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
                year_str = pub_date.get("Year") or pub_date.get("MedlineDate", "2000")[:4]
                try:
                    year = int(str(year_str)[:4])
                except (ValueError, TypeError):
                    year = 2000

                # Journal
                journal = art_data.get("Journal", {}).get("Title", "")

                # PMID
                pmid = str(medline.get("PMID", {}).get("#text", "") or medline.get("PMID", ""))

                # MeSH terms
                mesh_list = medline.get("MeshHeadingList", {}).get("MeshHeading", [])
                if isinstance(mesh_list, dict):
                    mesh_list = [mesh_list]
                mesh_terms = [
                    m.get("DescriptorName", {}).get("#text", "")
                    for m in mesh_list if isinstance(m, dict)
                ][:15]

                # Publication types
                pub_types = art_data.get("PublicationTypeList", {}).get("PublicationType", [])
                if isinstance(pub_types, dict):
                    pub_types = [pub_types]
                pub_type_texts = [
                    (p.get("#text", p) if isinstance(p, dict) else p)
                    for p in pub_types
                ]

                pub_type = _classify_pubtype(pub_type_texts, mesh_terms)
                study_subject, weight = _classify_study_subject(abstract, title, mesh_terms)

                papers.append(PublicationMetadata(
                    id=_make_id("pubmed", pmid or title),
                    pmid=pmid,
                    source=DataSource.PUBMED,
                    title=str(title),
                    abstract=abstract,
                    authors=authors,
                    journal=journal,
                    year=year,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    publication_type=pub_type,
                    study_subject=study_subject,
                    study_subject_weight=weight,
                    mesh_terms=mesh_terms,
                ))
            except Exception as e:
                print(f"[PubMed] Error parsing article: {e}")
                continue

    except Exception as e:
        print(f"[PubMed] Fetch error for '{query}': {e}")

    return papers


# ── OpenAlex ──────────────────────────────────────────────────────────────

async def _openalex_fetch(client: httpx.AsyncClient, query: str, max_results: int = 50) -> List[PublicationMetadata]:
    papers = []
    try:
        params = {
            "search":   query,
            "per-page": min(max_results, 100),
            "page":     1,
            "sort":     "relevance_score:desc",
            "filter":   "from_publication_date:2010-01-01",
        }
        r = await client.get(f"{OPENALEX_BASE}/works", params=params, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])

        for work in results:
            try:
                title = work.get("title") or work.get("display_name") or ""
                if not title:
                    continue

                # Abstract (inverted index → reconstruct)
                inv_index = work.get("abstract_inverted_index") or {}
                abstract = _reconstruct_abstract(inv_index)
                if not abstract or len(abstract) < 50:
                    continue

                # Authors
                authors = []
                for auth in (work.get("authorships") or [])[:8]:
                    name = auth.get("author", {}).get("display_name", "")
                    if name:
                        authors.append(name)

                # Year
                year = work.get("publication_year") or 2000

                # OpenAlex ID
                oa_id = work.get("id", "").replace("https://openalex.org/", "")

                # DOI
                doi = work.get("doi", "")

                # URL
                url = work.get("primary_location", {}).get("landing_page_url") or \
                      (f"https://doi.org/{doi}" if doi else f"https://openalex.org/{oa_id}")

                # Credibility
                cited_by  = work.get("cited_by_count", 0)
                is_oa     = work.get("open_access", {}).get("is_oa", False)

                # Keywords
                concepts = work.get("concepts") or []
                keywords = [c.get("display_name", "") for c in concepts[:10] if c.get("score", 0) > 0.3]

                study_subject, weight = _classify_study_subject(abstract, title, [])

                papers.append(PublicationMetadata(
                    id=_make_id("openalex", oa_id),
                    openalex_id=oa_id,
                    doi=doi,
                    source=DataSource.OPENALEX,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    year=year,
                    url=url,
                    cited_by_count=cited_by,
                    is_open_access=is_oa,
                    keywords=keywords,
                    study_subject=study_subject,
                    study_subject_weight=weight,
                ))
            except Exception as e:
                print(f"[OpenAlex] Error parsing work: {e}")
                continue

    except Exception as e:
        print(f"[OpenAlex] Fetch error for '{query}': {e}")

    return papers


# ── ClinicalTrials.gov ────────────────────────────────────────────────────

async def _trials_fetch(
    client: httpx.AsyncClient,
    disease: str,
    query: str,
    location: str = "",
    max_results: int = 50
) -> List[ClinicalTrialMetadata]:
    trials = []
    try:
        params = {
            "query.cond": disease,
            "query.term": query,
            "pageSize":   min(max_results, 100),
            "format":     "json",
        }
        r = await client.get(f"{TRIALS_BASE}/studies", params=params, timeout=15)
        r.raise_for_status()
        studies = r.json().get("studies", [])

        for study in studies:
            try:
                proto   = study.get("protocolSection", {})
                id_mod  = proto.get("identificationModule", {})
                status  = proto.get("statusModule", {})
                desc    = proto.get("descriptionModule", {})
                elig    = proto.get("eligibilityModule", {})
                contacts_mod = proto.get("contactsLocationsModule", {})
                design  = proto.get("designModule", {})
                conds   = proto.get("conditionsModule", {})
                arms    = proto.get("armsInterventionsModule", {})

                nct_id = id_mod.get("nctId", "")
                title  = id_mod.get("briefTitle", "")
                if not nct_id or not title:
                    continue

                # Status
                raw_status = status.get("overallStatus", "UNKNOWN")
                try:
                    trial_status = TrialStatus(raw_status)
                except ValueError:
                    trial_status = TrialStatus.UNKNOWN

                # Phase
                phases = design.get("phases", [])
                phase  = phases[0] if phases else None

                # Conditions
                conditions   = conds.get("conditions", [])

                # Interventions
                interventions_raw = arms.get("interventions", [])
                interventions = [i.get("name", "") for i in interventions_raw if i.get("name")][:5]

                # Dates
                start_date      = status.get("startDateStruct", {}).get("date", "")
                completion_date = status.get("completionDateStruct", {}).get("date", "")

                # Enrollment
                enrollment = design.get("enrollmentInfo", {}).get("count")

                # Eligibility (rich)
                elig_criteria = elig.get("eligibilityCriteria", "")
                inclusion_lines, exclusion_lines = _parse_eligibility(elig_criteria)

                eligibility = TrialEligibility(
                    min_age=elig.get("minimumAge"),
                    max_age=elig.get("maximumAge"),
                    gender=elig.get("sex", "All"),
                    criteria_text=elig_criteria[:1000] if elig_criteria else None,
                    inclusion=inclusion_lines[:8],
                    exclusion=exclusion_lines[:8],
                )

                # Locations (rich)
                locations = []
                for loc in contacts_mod.get("locations", [])[:10]:
                    locations.append(TrialLocation(
                        facility=loc.get("facility"),
                        city=loc.get("city"),
                        state=loc.get("state"),
                        country=loc.get("country"),
                        zip=loc.get("zip"),
                    ))

                # Contacts (rich)
                contacts = []
                for c in contacts_mod.get("centralContacts", [])[:3]:
                    contacts.append(TrialContact(
                        name=c.get("name"),
                        email=c.get("email"),
                        phone=c.get("phone"),
                        role=c.get("role"),
                    ))

                trials.append(ClinicalTrialMetadata(
                    id=_make_id("trial", nct_id),
                    nct_id=nct_id,
                    url=f"https://clinicaltrials.gov/study/{nct_id}",
                    title=title,
                    brief_summary=desc.get("briefSummary", "")[:500],
                    conditions=conditions,
                    interventions=interventions,
                    status=trial_status,
                    phase=phase,
                    start_date=start_date,
                    completion_date=completion_date,
                    enrollment=enrollment,
                    eligibility=eligibility,
                    locations=locations,
                    contacts=contacts,
                ))
            except Exception as e:
                print(f"[Trials] Error parsing study: {e}")
                continue

    except Exception as e:
        print(f"[Trials] Fetch error: {e}")

    return trials


# ── Main retrieval orchestrator ───────────────────────────────────────────

@traced(name="Parallel Retrieval", metadata={"stage": 2})
async def run_retrieval(
    query_variants: List[str],
    disease: str,
    original_query: str,
    location: str = "",
) -> Tuple[List[PublicationMetadata], List[ClinicalTrialMetadata]]:
    """
    Fire all APIs in parallel across all query variants.
    Deduplicates by ID. Returns flat unranked pools.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "Curalink/1.0 (medical-research-assistant)"},
        follow_redirects=True
    ) as client:

        tasks = []

        # Publications: run each variant against both PubMed + OpenAlex
        for variant in query_variants[:4]:
            tasks.append(_pubmed_fetch(client, variant, max_results=15))
            tasks.append(_openalex_fetch(client, variant, max_results=15))

        # Trials: use disease + original query (one call, rich results)
        tasks.append(_trials_fetch(client, disease, original_query, location, max_results=20))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers: List[PublicationMetadata] = []
    all_trials: List[ClinicalTrialMetadata] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"[Retrieval] Task {i} failed: {result}")
            continue
        if not result:
            continue
        if isinstance(result[0], ClinicalTrialMetadata) if result else False:
            all_trials.extend(result)
        else:
            all_papers.extend(result)

    # Deduplicate papers by title hash
    seen_titles: set = set()
    unique_papers: List[PublicationMetadata] = []
    for p in all_papers:
        title_key = p.title.lower().strip()[:80]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_papers.append(p)

    # Deduplicate trials by NCT ID
    seen_ncts: set = set()
    unique_trials: List[ClinicalTrialMetadata] = []
    for t in all_trials:
        if t.nct_id not in seen_ncts:
            seen_ncts.add(t.nct_id)
            unique_trials.append(t)

    print(f"[Retrieval] {len(unique_papers)} unique papers, {len(unique_trials)} unique trials")
    return unique_papers, unique_trials


# ── Helpers ───────────────────────────────────────────────────────────────

def _reconstruct_abstract(inv_index: dict) -> str:
    if not inv_index:
        return ""
    word_positions = []
    for word, positions in inv_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)

def _classify_pubtype(pub_types: list, mesh_terms: list) -> str:
    combined = " ".join(pub_types + mesh_terms).lower()
    if "randomized controlled trial" in combined:   return "RCT"
    if "systematic review" in combined:              return "systematic-review"
    if "meta-analysis" in combined:                  return "meta-analysis"
    if "clinical trial" in combined:                 return "clinical-trial"
    if "cohort" in combined:                         return "cohort-study"
    if "case report" in combined:                    return "case-report"
    if "review" in combined:                         return "review"
    return "research-article"

def _classify_study_subject(abstract: str, title: str, mesh_terms: list):
    text = (abstract + " " + title + " " + " ".join(mesh_terms)).lower()

    # Animal signals — heavy penalty
    if any(t in text for t in ["mouse model", "rat model", "murine", "rodent", "animal model", "primate model", "zebrafish", "drosophila"]):
        return StudySubject.ANIMAL, 0.15

    # In vitro signals
    if any(t in text for t in ["in vitro", "cell line", "petri dish", "cell culture", "in-vitro"]):
        return StudySubject.IN_VITRO, 0.10

    # Human study signals
    if any(t in text for t in ["randomized controlled", "rct", "double-blind", "placebo-controlled"]):
        return StudySubject.HUMAN_RCT, 1.00
    if any(t in text for t in ["systematic review", "meta-analysis", "cochrane"]):
        return StudySubject.HUMAN_SYSTEMATIC, 0.95
    if any(t in text for t in ["cohort study", "prospective cohort", "retrospective cohort"]):
        return StudySubject.HUMAN_COHORT, 0.80
    if any(t in text for t in ["case-control", "case control"]):
        return StudySubject.HUMAN_CASE_CONTROL, 0.75
    if any(t in text for t in ["patients", "participants", "subjects enrolled", "clinical study"]):
        return StudySubject.HUMAN_OBSERVATIONAL, 0.70
    if any(t in text for t in ["case report", "case series"]):
        return StudySubject.HUMAN_CASE_REPORT, 0.55

    return StudySubject.UNKNOWN, 0.50

def _parse_eligibility(criteria_text: str):
    if not criteria_text:
        return [], []
    inclusion, exclusion = [], []
    lines = criteria_text.split("\n")
    mode = "inclusion"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "exclusion" in line.lower():
            mode = "exclusion"
            continue
        if "inclusion" in line.lower():
            mode = "inclusion"
            continue
        if line.startswith(("-", "•", "*", "·")) or (len(line) > 2 and line[0].isdigit()):
            if mode == "inclusion":
                inclusion.append(line.lstrip("-•*· 0123456789.").strip())
            else:
                exclusion.append(line.lstrip("-•*· 0123456789.").strip())
    return inclusion, exclusion
