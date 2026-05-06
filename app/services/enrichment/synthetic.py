import json
import random
from pathlib import Path
from app.services.enrichment.base import EnrichmentProvider

_DOMAINS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "company_domains.json"

with open(_DOMAINS_PATH) as f:
    KNOWN_DOMAINS: dict = json.load(f)

SENIORITY_LEVELS = ["Junior", "Mid-Level", "Senior", "Manager", "Director", "VP", "C-Suite"]
SENIORITY_WEIGHTS = [5, 20, 30, 20, 12, 8, 5]

JOB_TITLES_BY_SENIORITY = {
    "Junior": ["Junior Software Engineer", "Associate Engineer", "Junior Developer"],
    "Mid-Level": ["Software Engineer", "Product Manager", "Data Analyst", "Backend Engineer"],
    "Senior": ["Senior Software Engineer", "Senior Product Manager", "Senior Data Engineer", "Staff Engineer"],
    "Manager": ["Engineering Manager", "Product Manager", "Head of Engineering", "Technical Lead"],
    "Director": ["Director of Engineering", "Director of Product", "Director of Data"],
    "VP": ["VP of Engineering", "VP of Product", "VP of Sales", "VP of Marketing"],
    "C-Suite": ["CTO", "CEO", "COO", "CPO", "CFO"],
}

TECH_STACKS = [
    ["AWS", "React", "PostgreSQL"],
    ["GCP", "Vue.js", "MySQL"],
    ["Azure", "Angular", "SQL Server"],
    ["AWS", "Python", "FastAPI", "Redis"],
    ["GCP", "Go", "Kubernetes", "BigQuery"],
    ["AWS", "Node.js", "MongoDB", "Docker"],
    ["AWS", "TypeScript", "Next.js", "PostgreSQL"],
    ["Vercel", "React", "Supabase"],
    ["AWS", "Python", "Django", "PostgreSQL", "Redis"],
    ["GCP", "Java", "Spring Boot", "BigQuery"],
]

TLD_INDUSTRY_MAP = {
    ".io": "SaaS",
    ".ai": "AI/ML",
    ".dev": "DevTools",
    ".tech": "Technology",
    ".app": "SaaS",
    ".co": "Technology",
    ".bank": "Finance",
    ".edu": "Education",
    ".gov": "Government",
    ".org": "Non-Profit",
    ".health": "Healthcare",
    ".finance": "Finance",
}

SIZE_TO_REVENUE = {
    "1-10": "$0-$1M",
    "10-50": "$1M-$5M",
    "50-200": "$5M-$20M",
    "200-500": "$20M-$100M",
    "500-1000": "$100M-$500M",
    "1000-2000": "$500M-$1B",
    "2000-5000": "$1B-$5B",
    "5000-10000": "$5B+",
    "10000+": "$10B+",
}

FALLBACK_SIZE_RANGES = ["10-50", "50-200", "200-500", "500-1000"]
FALLBACK_SIZE_WEIGHTS = [15, 35, 35, 15]


class SyntheticEnrichmentProvider(EnrichmentProvider):
    def __init__(self):
        self._cache = {}  # Cache for domain enrichments
        
    def enrich(self, email: str, company: str) -> dict:
        domain = self._extract_domain(email)
        
        # Check cache first
        if domain in self._cache:
            cached = self._cache[domain].copy()
            # Add some randomization for non-cached fields
            seniority = random.choices(SENIORITY_LEVELS, SENIORITY_WEIGHTS)[0]
            job_title = random.choice(JOB_TITLES_BY_SENIORITY[seniority])
            tech_stack = random.choice(TECH_STACKS)
            
            cached.update({
                "job_title": job_title,
                "seniority": seniority,
                "tech_stack": tech_stack,
                "confidence": round(cached["confidence"] + random.uniform(-0.05, 0.05), 2),
            })
            return cached
        
        known = KNOWN_DOMAINS.get(domain)
        confidence = 0.5

        if known:
            industry = known["industry"]
            size_range = known["size_range"]
            revenue_estimate = known["revenue"]
            confidence = 0.85
        else:
            industry = self._infer_industry_from_domain(domain)
            size_range = random.choices(FALLBACK_SIZE_RANGES, FALLBACK_SIZE_WEIGHTS)[0]
            confidence = 0.6 if industry != "Technology" else 0.5

        # Normalize size range key for revenue lookup
        revenue_estimate = SIZE_TO_REVENUE.get(size_range, "$5M-$50M")
        if known:
            revenue_estimate = known["revenue"]

        seniority = random.choices(SENIORITY_LEVELS, SENIORITY_WEIGHTS)[0]
        job_title = random.choice(JOB_TITLES_BY_SENIORITY[seniority])
        tech_stack = random.choice(TECH_STACKS)

        result = {
            "job_title": job_title,
            "seniority": seniority,
            "company_size": size_range,
            "industry": industry,
            "revenue_estimate": revenue_estimate,
            "tech_stack": tech_stack,
            "confidence": round(confidence + random.uniform(-0.05, 0.05), 2),
            "enrichment_source": "domain_heuristics_v1",
        }
        
        # Cache the result for this domain (without personalized fields)
        self._cache[domain] = {
            "company_size": size_range,
            "industry": industry,
            "revenue_estimate": revenue_estimate,
            "confidence": confidence,
            "enrichment_source": "domain_heuristics_v1",
        }
        
        return result

    def _extract_domain(self, email: str) -> str:
        return email.split("@")[-1].lower().strip()

    def _infer_industry_from_domain(self, domain: str) -> str:
        for tld, industry in TLD_INDUSTRY_MAP.items():
            if domain.endswith(tld):
                return industry
        return "Technology"
