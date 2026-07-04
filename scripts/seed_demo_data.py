"""
Demo data seeder — inserts ~150 realistic leads with full Phase 3/4 data.

Run AFTER all migrations:
    python scripts/seed_demo_data.py

Idempotent: skips if demo leads already exist (tagged "demo").
Does NOT depend on Ollama, Redis, or any external API.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import random

from app.database.connection import SessionLocal, create_all_tables
from app.database.models import (
    Lead, Enrichment, Verdict, AgentLog,
    OutreachEmail, OutreachSequence, ABTestResult,
    BookingRequest, Conversation, IntentSignal,
    OptimizationRun,
)

random.seed(42)

# ---------------------------------------------------------------------------
# Curated high-quality personas (hot / warm / cold)
# ---------------------------------------------------------------------------

HOT_PERSONAS = [
    {
        "name": "Sarah Chen", "email": "s.chen@veritas-ai.com", "company": "Veritas AI",
        "source": "linkedin_signal", "job_title": "VP of Engineering", "seniority": "VP",
        "company_size": "150-300", "industry": "Technology", "revenue_estimate": "$20M-$50M",
        "tech_stack": ["Python", "Kubernetes", "AWS", "Terraform"],
        "bant": {"budget": 0.87, "authority": 0.91, "need": 0.88, "timeline": 0.82},
        "reasoning": "Sarah is VP of Engineering at a 200-person AI startup with strong budget signals from Series B funding. Full procurement authority and urgent timeline to modernize their go-to-market stack.",
        "conversion_status": "converted",
    },
    {
        "name": "Marcus Williams", "email": "m.williams@dataflow.io", "company": "DataFlow Systems",
        "source": "event", "job_title": "Chief Revenue Officer", "seniority": "C-Level",
        "company_size": "300-500", "industry": "FinTech", "revenue_estimate": "$50M-$100M",
        "tech_stack": ["Salesforce", "HubSpot", "Tableau", "Snowflake"],
        "bant": {"budget": 0.92, "authority": 0.97, "need": 0.85, "timeline": 0.78},
        "reasoning": "Marcus is CRO with clear budget authority and an active vendor evaluation in Q1. Company recently raised Series C and is scaling their sales team aggressively.",
        "conversion_status": "converted",
    },
    {
        "name": "Priya Kapoor", "email": "priya.k@cloudpeak.dev", "company": "CloudPeak Solutions",
        "source": "website_form", "job_title": "Head of Growth", "seniority": "Director",
        "company_size": "80-150", "industry": "DevTools", "revenue_estimate": "$5M-$20M",
        "tech_stack": ["React", "Node.js", "GCP", "Datadog"],
        "bant": {"budget": 0.79, "authority": 0.83, "need": 0.91, "timeline": 0.86},
        "reasoning": "Priya leads Growth at a DevTools scale-up with a specific need for automated lead qualification as they plan to double their sales headcount. Timeline is Q1 this year.",
        "conversion_status": "converted",
    },
    {
        "name": "James O'Brien", "email": "jobs@meridian-soft.com", "company": "Meridian Software",
        "source": "inbound_email", "job_title": "COO", "seniority": "C-Level",
        "company_size": "200-400", "industry": "SaaS", "revenue_estimate": "$30M-$70M",
        "tech_stack": ["Salesforce", "Marketo", "Python", "Azure"],
        "bant": {"budget": 0.84, "authority": 0.95, "need": 0.82, "timeline": 0.72},
        "reasoning": "James reached out directly citing a failed manual SDR process. As COO he can approve new tools. Budget confirmed via their recent pricing page visits.",
        "conversion_status": "converted",
    },
    {
        "name": "Elena Sorokina", "email": "e.sorokina@nexgen-analytics.com", "company": "NexGen Analytics",
        "source": "linkedin_signal", "job_title": "VP Sales", "seniority": "VP",
        "company_size": "100-200", "industry": "SaaS", "revenue_estimate": "$15M-$40M",
        "tech_stack": ["Salesforce", "Outreach", "SQL", "Looker"],
        "bant": {"budget": 0.81, "authority": 0.88, "need": 0.87, "timeline": 0.76},
        "reasoning": "Elena is VP Sales expanding her team to 3x and needs pipeline automation. LinkedIn activity shows active competitor research. Q1 purchase window confirmed.",
        "conversion_status": "converted",
    },
    {
        "name": "Daniel Kim", "email": "d.kim@stackbridge.io", "company": "StackBridge",
        "source": "event", "job_title": "Director of RevOps", "seniority": "Director",
        "company_size": "120-250", "industry": "Technology", "revenue_estimate": "$12M-$30M",
        "tech_stack": ["HubSpot", "Segment", "dbt", "Redshift"],
        "bant": {"budget": 0.77, "authority": 0.82, "need": 0.90, "timeline": 0.79},
        "reasoning": "Daniel is RevOps Director with full stack access. He shared specific pain points around lead scoring accuracy and has a Q2 tool evaluation underway.",
        "conversion_status": "converted",
    },
    {
        "name": "Amara Osei", "email": "a.osei@finbridge-capital.com", "company": "FinBridge Capital",
        "source": "marketing_ad", "job_title": "Managing Director", "seniority": "C-Level",
        "company_size": "200-500", "industry": "FinTech", "revenue_estimate": "$80M-$150M",
        "tech_stack": ["Bloomberg Terminal", "Python", "AWS", "Salesforce"],
        "bant": {"budget": 0.93, "authority": 0.96, "need": 0.79, "timeline": 0.68},
        "reasoning": "Senior exec at a fintech firm with high budget. Clicked on enterprise pricing page 3x. Actively building out their institutional sales function.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Lena Müller", "email": "l.mueller@agileops.de", "company": "AgileOps GmbH",
        "source": "inbound_email", "job_title": "Chief Technology Officer", "seniority": "C-Level",
        "company_size": "90-180", "industry": "Technology", "revenue_estimate": "$8M-$20M",
        "tech_stack": ["Go", "Kubernetes", "Terraform", "Datadog"],
        "bant": {"budget": 0.76, "authority": 0.94, "need": 0.84, "timeline": 0.81},
        "reasoning": "CTO with technical decision authority and an explicit need to automate their SDR process. Recently posted 3 SDR job listings — a clear buying signal.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Ryan Torres", "email": "ryan@growthlab.io", "company": "GrowthLab",
        "source": "website_form", "job_title": "CEO", "seniority": "C-Level",
        "company_size": "50-100", "industry": "SaaS", "revenue_estimate": "$3M-$10M",
        "tech_stack": ["HubSpot", "Stripe", "React", "Node.js"],
        "bant": {"budget": 0.74, "authority": 0.98, "need": 0.86, "timeline": 0.84},
        "reasoning": "Founder-CEO with absolute purchase authority at a fast-growing SaaS. Described their SDR problem in detail on the intake form. Ready to buy in 30 days.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Yuki Tanaka", "email": "y.tanaka@pixelstorm.jp", "company": "PixelStorm",
        "source": "linkedin_signal", "job_title": "VP Product & Growth", "seniority": "VP",
        "company_size": "100-200", "industry": "Technology", "revenue_estimate": "$10M-$25M",
        "tech_stack": ["TypeScript", "PostgreSQL", "GCP", "Mixpanel"],
        "bant": {"budget": 0.80, "authority": 0.85, "need": 0.89, "timeline": 0.77},
        "reasoning": "VP level with combined product and growth ownership. Company recently shifted to PLG and urgently needs lead intelligence for their sales-assist motion.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Thomas Andersen", "email": "t.andersen@scalehq.dk", "company": "ScaleHQ",
        "source": "event", "job_title": "Chief Commercial Officer", "seniority": "C-Level",
        "company_size": "100-200", "industry": "SaaS", "revenue_estimate": "$10M-$25M",
        "tech_stack": ["Pipedrive", "ActiveCampaign", "Intercom"],
        "bant": {"budget": 0.83, "authority": 0.96, "need": 0.88, "timeline": 0.74},
        "reasoning": "CCO driving international expansion. Expressed urgency around qualifying inbound leads from new markets. Q2 deployment target confirmed.",
        "conversion_status": "converted",
    },
    {
        "name": "Isabelle Fontaine", "email": "i.fontaine@hexacloud.fr", "company": "HexaCloud",
        "source": "inbound_email", "job_title": "VP Revenue", "seniority": "VP",
        "company_size": "150-300", "industry": "Technology", "revenue_estimate": "$25M-$60M",
        "tech_stack": ["Salesforce", "Gong", "Outreach", "Looker"],
        "bant": {"budget": 0.86, "authority": 0.89, "need": 0.92, "timeline": 0.80},
        "reasoning": "VP Revenue at a cloud infrastructure company scaling from 150 to 300 people. Board-approved budget for sales tooling. Q1 go-live required.",
        "conversion_status": "converted",
    },
    {
        "name": "Kwame Asante", "email": "k.asante@afrohub.tech", "company": "AfroHub Tech",
        "source": "website_form", "job_title": "CEO & Co-founder", "seniority": "C-Level",
        "company_size": "50-100", "industry": "FinTech", "revenue_estimate": "$4M-$12M",
        "tech_stack": ["Python", "React", "AWS", "PostgreSQL"],
        "bant": {"budget": 0.71, "authority": 0.99, "need": 0.91, "timeline": 0.85},
        "reasoning": "Founder-CEO with full budget authority. Raised $5M seed round 3 months ago. Described exact pain: losing hot leads because their 2-person SDR team can't keep up.",
        "conversion_status": "unqualified",
    },
]

WARM_PERSONAS = [
    {
        "name": "Carlos Reyes", "email": "c.reyes@synaptix.com", "company": "Synaptix",
        "source": "marketing_ad", "job_title": "Sales Operations Manager", "seniority": "Manager",
        "company_size": "80-150", "industry": "Software", "revenue_estimate": "$8M-$20M",
        "tech_stack": ["Salesforce", "Outreach", "Clari"],
        "bant": {"budget": 0.55, "authority": 0.58, "need": 0.71, "timeline": 0.44},
        "reasoning": "Mid-level ops role with partial decision authority. Clear need but budget requires sign-off from CFO. Timeline is H2 rather than immediate.",
    },
    {
        "name": "Nina Patel", "email": "nina.patel@streamline-hq.com", "company": "Streamline HQ",
        "source": "website_form", "job_title": "Director of Marketing", "seniority": "Director",
        "company_size": "60-120", "industry": "SaaS", "revenue_estimate": "$5M-$15M",
        "tech_stack": ["HubSpot", "Mailchimp", "Google Analytics"],
        "bant": {"budget": 0.58, "authority": 0.62, "need": 0.74, "timeline": 0.51},
        "reasoning": "Marketing director evaluating tools for Q3. Has influence but not final budget approval. Opened both follow-up emails.",
    },
    {
        "name": "Omar Hassan", "email": "o.hassan@infrastack.io", "company": "InfraStack",
        "source": "event", "job_title": "Engineering Manager", "seniority": "Manager",
        "company_size": "100-200", "industry": "DevTools", "revenue_estimate": "$12M-$30M",
        "tech_stack": ["Go", "AWS", "Terraform", "PagerDuty"],
        "bant": {"budget": 0.52, "authority": 0.65, "need": 0.78, "timeline": 0.42},
        "reasoning": "Technical manager who can champion internally but needs director sign-off. Engaged in conversation thread about pricing tiers.",
    },
    {
        "name": "Sophie Laurent", "email": "s.laurent@techlift-fr.com", "company": "TechLift",
        "source": "inbound_email", "job_title": "Head of Business Development", "seniority": "Manager",
        "company_size": "70-130", "industry": "Technology", "revenue_estimate": "$7M-$18M",
        "tech_stack": ["Pipedrive", "LinkedIn Sales Nav", "Notion"],
        "bant": {"budget": 0.61, "authority": 0.70, "need": 0.69, "timeline": 0.55},
        "reasoning": "BizDev head with decent authority. Budget is constrained but there is willingness to explore. Q3 decision window.",
    },
    {
        "name": "Alex Novak", "email": "a.novak@databridge-eu.com", "company": "DataBridge",
        "source": "linkedin_signal", "job_title": "Revenue Operations Lead", "seniority": "Manager",
        "company_size": "90-180", "industry": "FinTech", "revenue_estimate": "$10M-$25M",
        "tech_stack": ["HubSpot", "dbt", "Stripe", "Snowflake"],
        "bant": {"budget": 0.57, "authority": 0.68, "need": 0.73, "timeline": 0.49},
        "reasoning": "RevOps lead with strong analytical background. Has influence in tool selection but shares authority with VP Sales.",
    },
    {
        "name": "Maria Santos", "email": "m.santos@grovetech.br", "company": "GroveTech",
        "source": "marketing_ad", "job_title": "CMO", "seniority": "C-Level",
        "company_size": "50-100", "industry": "Software", "revenue_estimate": "$4M-$10M",
        "tech_stack": ["Mailchimp", "WordPress", "Stripe"],
        "bant": {"budget": 0.50, "authority": 0.72, "need": 0.67, "timeline": 0.38},
        "reasoning": "CMO at a smaller company with high authority but limited budget for tooling. Need is clear; will revisit in next fiscal quarter.",
    },
    {
        "name": "Tom Bergmann", "email": "t.bergmann@logicflow.de", "company": "LogicFlow",
        "source": "website_form", "job_title": "VP of Customer Success", "seniority": "VP",
        "company_size": "100-200", "industry": "SaaS", "revenue_estimate": "$15M-$35M",
        "tech_stack": ["Salesforce", "Gainsight", "Zendesk"],
        "bant": {"budget": 0.59, "authority": 0.75, "need": 0.72, "timeline": 0.46},
        "reasoning": "CS VP looking to automate their expansion pipeline qualification. Good authority but needs sales team alignment. Mid-year evaluation.",
    },
    {
        "name": "Fatima Al-Rashid", "email": "f.alrashid@meridian-mea.com", "company": "Meridian MEA",
        "source": "event", "job_title": "Sales Director", "seniority": "Director",
        "company_size": "150-300", "industry": "Technology", "revenue_estimate": "$20M-$50M",
        "tech_stack": ["Salesforce", "LinkedIn Sales Nav", "Gong"],
        "bant": {"budget": 0.63, "authority": 0.78, "need": 0.70, "timeline": 0.52},
        "reasoning": "Sales Director with regional budget authority. Expressed interest but current tooling contract expires in 8 months.",
    },
    {
        "name": "Lucas Ferreira", "email": "l.ferreira@proptech-br.com", "company": "PropTech Brasil",
        "source": "website_form", "job_title": "Head of Sales", "seniority": "Manager",
        "company_size": "60-120", "industry": "PropTech", "revenue_estimate": "$5M-$12M",
        "tech_stack": ["Pipedrive", "WhatsApp Business", "Google Workspace"],
        "bant": {"budget": 0.55, "authority": 0.71, "need": 0.76, "timeline": 0.48},
        "reasoning": "Head of Sales at a growing PropTech company. Needs to qualify inbound leads faster but budget approval sits with CEO.",
    },
    {
        "name": "Mei Lin", "email": "mei.lin@cloudscale-sg.com", "company": "CloudScale SG",
        "source": "linkedin_signal", "job_title": "Director of Growth", "seniority": "Director",
        "company_size": "80-160", "industry": "SaaS", "revenue_estimate": "$8M-$20M",
        "tech_stack": ["Mixpanel", "Amplitude", "Segment", "HubSpot"],
        "bant": {"budget": 0.60, "authority": 0.72, "need": 0.79, "timeline": 0.54},
        "reasoning": "Growth Director at a Singapore-based SaaS company expanding into new markets. Interested in automated qualification but finalizing Q3 budget.",
    },
    {
        "name": "Patrick O'Sullivan", "email": "p.osullivan@revuup.ie", "company": "RevUup",
        "source": "inbound_email", "job_title": "Co-Founder & VP Sales", "seniority": "VP",
        "company_size": "40-80", "industry": "SaaS", "revenue_estimate": "$2M-$8M",
        "tech_stack": ["HubSpot", "Intercom", "Stripe"],
        "bant": {"budget": 0.56, "authority": 0.90, "need": 0.82, "timeline": 0.61},
        "reasoning": "Co-founder handling sales personally. Authority is high but the company is early-stage with limited tooling budget. H2 decision.",
    },
    {
        "name": "Anya Petrov", "email": "a.petrov@techpulse-ams.com", "company": "TechPulse AMS",
        "source": "event", "job_title": "VP Marketing", "seniority": "VP",
        "company_size": "100-200", "industry": "Technology", "revenue_estimate": "$12M-$28M",
        "tech_stack": ["Marketo", "Salesforce", "6sense", "Demandbase"],
        "bant": {"budget": 0.64, "authority": 0.77, "need": 0.71, "timeline": 0.50},
        "reasoning": "VP Marketing with ABM focus. Needs lead intelligence to prioritize accounts. Budget request pending CFO sign-off for Q3.",
    },
]

COLD_PERSONAS = [
    {
        "name": "Brett Thompson", "email": "b.thompson@oldco.com", "company": "OldCo Corp",
        "source": "website_form", "job_title": "Junior Sales Rep", "seniority": "IC",
        "company_size": "1000+", "industry": "Manufacturing", "revenue_estimate": "$500M+",
        "tech_stack": ["Excel", "Outlook"],
        "bant": {"budget": 0.22, "authority": 0.18, "need": 0.31, "timeline": 0.15},
        "reasoning": "Junior IC with no purchase authority at a large manufacturing company outside ICP. No budget signals and long enterprise procurement cycles.",
    },
    {
        "name": "Jessica Park", "email": "j.park@ngo-impact.org", "company": "Impact NGO",
        "source": "marketing_ad", "job_title": "Programme Coordinator", "seniority": "IC",
        "company_size": "10-50", "industry": "Non-Profit", "revenue_estimate": "<$1M",
        "tech_stack": ["Google Workspace", "Airtable"],
        "bant": {"budget": 0.09, "authority": 0.25, "need": 0.35, "timeline": 0.20},
        "reasoning": "NGO with no budget and outside ICP industry. Engagement appears research-focused rather than purchase intent.",
    },
    {
        "name": "Kevin Lau", "email": "kevin.l@startuphub.co", "company": "StartupHub",
        "source": "website_form", "job_title": "Founder", "seniority": "C-Level",
        "company_size": "1-10", "industry": "Technology", "revenue_estimate": "<$500K",
        "tech_stack": ["Notion", "Slack", "Stripe"],
        "bant": {"budget": 0.15, "authority": 0.92, "need": 0.45, "timeline": 0.30},
        "reasoning": "Founder with full authority but pre-revenue startup. Below minimum company size threshold and no budget for tooling at this stage.",
    },
    {
        "name": "Hannah Beck", "email": "h.beck@agency-creative.com", "company": "Creative Agency",
        "source": "inbound_email", "job_title": "Account Manager", "seniority": "IC",
        "company_size": "20-50", "industry": "Marketing", "revenue_estimate": "$1M-$3M",
        "tech_stack": ["Adobe CC", "Figma", "Asana"],
        "bant": {"budget": 0.20, "authority": 0.28, "need": 0.32, "timeline": 0.25},
        "reasoning": "Small creative agency outside ICP vertical and below minimum size. No clear product-market fit for B2B sales automation.",
    },
    {
        "name": "Pierre Dumont", "email": "p.dumont@retail-eu.fr", "company": "RetailEU",
        "source": "linkedin_signal", "job_title": "Store Manager", "seniority": "Manager",
        "company_size": "500-1000", "industry": "Retail", "revenue_estimate": "$50M-$150M",
        "tech_stack": ["SAP", "POS System"],
        "bant": {"budget": 0.24, "authority": 0.21, "need": 0.28, "timeline": 0.18},
        "reasoning": "Retail industry outside ICP. Store manager with no authority over software procurement. Enterprise sales cycle would be 12+ months.",
    },
    {
        "name": "Rashid Al-Farsi", "email": "r.alfarsi@gov-portal.ae", "company": "Gov Portal",
        "source": "website_form", "job_title": "IT Officer", "seniority": "IC",
        "company_size": "1000+", "industry": "Government", "revenue_estimate": "N/A",
        "tech_stack": ["Windows Server", "SharePoint"],
        "bant": {"budget": 0.18, "authority": 0.12, "need": 0.29, "timeline": 0.10},
        "reasoning": "Government entity with extremely long procurement cycles. No budget authority and outside target vertical.",
    },
    {
        "name": "Chloe Martin", "email": "chloe.m@freelance.me", "company": "Self-Employed",
        "source": "marketing_ad", "job_title": "Freelance Designer", "seniority": "IC",
        "company_size": "1-10", "industry": "Creative", "revenue_estimate": "<$200K",
        "tech_stack": ["Figma", "Canva", "Notion"],
        "bant": {"budget": 0.05, "authority": 0.80, "need": 0.20, "timeline": 0.15},
        "reasoning": "Solo freelancer who clicked an ad. No team to sell to and no use case for B2B lead qualification tooling.",
    },
]

# ---------------------------------------------------------------------------
# Parametric lead generation data for volume
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Adrian", "Beatrice", "Cameron", "Diana", "Ethan", "Fiona", "George", "Helena",
    "Ivan", "Julia", "Karl", "Laura", "Michael", "Natasha", "Oscar", "Patricia",
    "Quentin", "Rachel", "Simon", "Tara", "Ulrich", "Victoria", "William", "Xena",
    "Yannick", "Zara", "Andrei", "Brigitte", "Cédric", "Daria", "Emil", "Franziska",
    "Gregor", "Hana", "Igor", "Jana", "Kosta", "Luisa", "Magnus", "Nadia",
    "Olga", "Piotr", "Quentin", "Rosa", "Stefan", "Tamara", "Udo", "Vera",
]

LAST_NAMES = [
    "Armstrong", "Bauer", "Chen", "Diaz", "Evans", "Fischer", "Garcia", "Hansen",
    "Ivanov", "Jensen", "Klein", "Lopez", "Meyer", "Nakamura", "Olsen", "Petrov",
    "Quinn", "Reyes", "Schmidt", "Torres", "Ueda", "Vargas", "Wagner", "Xu",
    "Yıldız", "Zimmermann", "Bakker", "Conti", "Dubois", "Eriksson",
]

COMPANIES_HOT = [
    ("Apex Analytics", "SaaS", "150-300", "$20M-$50M"),
    ("BrightPath AI", "Technology", "100-200", "$15M-$35M"),
    ("CoreShift", "FinTech", "200-400", "$40M-$90M"),
    ("DeepLoop", "DevTools", "80-150", "$8M-$20M"),
    ("Elevate Revenue", "SaaS", "120-250", "$18M-$45M"),
    ("FutureSales Co", "Technology", "100-200", "$12M-$30M"),
    ("GridPath", "SaaS", "150-300", "$22M-$55M"),
    ("HorizonStack", "Technology", "90-180", "$10M-$25M"),
    ("InsightFlow", "SaaS", "200-400", "$30M-$70M"),
    ("JetScale", "FinTech", "100-200", "$15M-$40M"),
    ("KineticOps", "DevTools", "80-160", "$8M-$22M"),
    ("LaunchMetrics", "SaaS", "120-240", "$18M-$50M"),
    ("MomentumHQ", "Technology", "100-200", "$14M-$35M"),
    ("NovaPilot", "SaaS", "150-300", "$20M-$50M"),
    ("OrbitalAI", "Technology", "80-160", "$10M-$28M"),
    ("PivotStack", "SaaS", "100-200", "$12M-$30M"),
    ("QuantumSales", "FinTech", "150-300", "$25M-$60M"),
    ("RadianceCloud", "Technology", "100-200", "$15M-$40M"),
    ("SprintOps", "SaaS", "80-150", "$8M-$22M"),
    ("TractionHQ", "DevTools", "100-200", "$12M-$30M"),
]

COMPANIES_WARM = [
    ("Axle Software", "Software", "60-120", "$5M-$15M"),
    ("BlueLine CRM", "SaaS", "50-100", "$4M-$10M"),
    ("ClearPath Tech", "Technology", "70-130", "$6M-$18M"),
    ("DriftPoint", "SaaS", "60-120", "$5M-$12M"),
    ("EdgeRevenue", "Technology", "80-150", "$7M-$20M"),
    ("FlowMetrics", "SaaS", "50-100", "$4M-$10M"),
    ("GlideOps", "Software", "70-130", "$6M-$16M"),
    ("HubRight", "SaaS", "60-120", "$5M-$14M"),
    ("ImpactSales", "Technology", "50-100", "$4M-$12M"),
    ("JumpCloud EU", "DevTools", "80-150", "$7M-$20M"),
    ("KompassAI", "SaaS", "60-120", "$5M-$14M"),
    ("LeapFrog CRM", "Software", "50-100", "$4M-$10M"),
    ("MercurySales", "Technology", "70-130", "$6M-$18M"),
    ("NectarOps", "SaaS", "60-120", "$5M-$12M"),
    ("OpenRevenue", "Technology", "80-150", "$7M-$20M"),
]

COMPANIES_COLD = [
    ("MegaCorp Industries", "Manufacturing", "1000+", "$500M+"),
    ("RetailGiant", "Retail", "500-1000", "$100M-$300M"),
    ("OldMedia Inc", "Publishing", "200-500", "$20M-$50M"),
    ("LocalBank", "Banking", "500-1000", "$50M-$200M"),
    ("Gov Services Ltd", "Government", "1000+", "N/A"),
    ("Tiny Agency", "Marketing", "10-20", "$500K-$1M"),
    ("Student Startup", "Technology", "1-5", "<$100K"),
    ("ChurchDigital", "Non-Profit", "10-30", "<$500K"),
]

TITLES_HOT = [
    ("VP of Sales", "VP"), ("Chief Revenue Officer", "C-Level"), ("VP Engineering", "VP"),
    ("Director of RevOps", "Director"), ("CEO", "C-Level"), ("COO", "C-Level"),
    ("Head of Growth", "Director"), ("VP Product", "VP"), ("Chief Commercial Officer", "C-Level"),
    ("Director of Sales", "Director"),
]

TITLES_WARM = [
    ("Sales Operations Manager", "Manager"), ("Director of Marketing", "Director"),
    ("Head of Business Development", "Manager"), ("Revenue Operations Lead", "Manager"),
    ("Senior Account Executive", "IC"), ("Marketing Director", "Director"),
    ("VP Customer Success", "VP"), ("Head of Sales", "Manager"),
]

TITLES_COLD = [
    ("Junior Sales Rep", "IC"), ("Account Manager", "IC"), ("Programme Coordinator", "IC"),
    ("Store Manager", "Manager"), ("IT Officer", "IC"), ("Marketing Assistant", "IC"),
]

SOURCES = ["linkedin_signal", "website_form", "event", "inbound_email", "marketing_ad"]

TECH_STACKS_HOT = [
    ["Salesforce", "Gong", "Outreach", "Looker"],
    ["HubSpot", "Segment", "dbt", "Redshift"],
    ["Python", "AWS", "Kubernetes", "Datadog"],
    ["Salesforce", "Marketo", "Tableau", "Snowflake"],
    ["React", "Node.js", "GCP", "PostgreSQL"],
    ["TypeScript", "Stripe", "AWS", "Mixpanel"],
]

TECH_STACKS_WARM = [
    ["HubSpot", "Mailchimp", "Google Analytics"],
    ["Pipedrive", "Intercom", "Slack"],
    ["Salesforce", "Clari", "LinkedIn Sales Nav"],
    ["Notion", "Airtable", "Zapier"],
]

TECH_STACKS_COLD = [
    ["Excel", "Outlook"],
    ["Google Workspace", "Airtable"],
    ["SAP", "SharePoint"],
]

WARM_REASONINGS = [
    "Decision-maker with moderate authority. Need is clear but budget cycle hasn't started. Q3 re-engagement recommended.",
    "Manager-level champion with genuine interest. Needs VP sign-off to proceed. Follow up in 6 weeks.",
    "Engaged with pricing page twice. Authority is shared. Good candidate for nurture sequence.",
    "Director-level with aligned ICP. Budget constrained until next quarter. Warm maintain track.",
    "Expressed need in conversation. Timeline is 90+ days out. Monitor for buying signal uptick.",
]

COLD_REASONINGS = [
    "Outside ICP industry. No budget signals and no authority to purchase software.",
    "Below minimum company size. Early-stage with no tooling budget.",
    "Enterprise procurement with 12+ month cycle. Not worth pursuing this quarter.",
    "Role has no authority over sales tooling decisions. Would need to reach C-level.",
    "No clear use case for B2B lead qualification. Research intent only.",
]

# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

CORE_NODES = ["orchestrate", "enrich", "score_intent", "analyse", "validate"]
VERDICT_NODES = {"Hot": "booking", "Warm": "outreach", "Cold": "sync_crm"}

SUBJECTS = [
    "Quick question about {company}",
    "How {industry} teams use us",
    "Re: your growth at {company}",
    "A resource for your team",
    "Following up — {company}",
    "Last note — {company}",
]

CONVERSATION_MSGS = [
    ("assistant", "Hi {first_name}, I noticed {company} is scaling its go-to-market motion. Would love to show you how AutonomousSDR can automate your lead qualification. 15 minutes this week?"),
    ("user", "Sure, sounds interesting. What does it actually do?"),
    ("assistant", "AutonomousSDR uses a multi-agent LangGraph pipeline to enrich, score, and qualify leads automatically — so your team only spends time on leads that are genuinely ready to buy. Happy to send you a short demo."),
    ("user", "That looks useful. What does pricing look like?"),
    ("assistant", "Happy to! Pricing scales with volume. For a team your size at {company}, we typically see ROI within 60 days. Want to hop on a call to walk through it together?"),
]

INTENT_SIGNAL_TYPES = [
    ("linkedin_signal",    0.20, "heuristic"),
    ("seniority_vp_plus",  0.15, "heuristic"),
    ("icp_industry_match", 0.15, "heuristic"),
    ("company_size_match", 0.10, "heuristic"),
    ("recent_funding",     0.20, "crunchbase"),
    ("hot_budget_score",   0.12, "heuristic"),
    ("tight_timeline",     0.08, "heuristic"),
    ("high_need_score",    0.12, "heuristic"),
]


def _ago(days=0, hours=0, minutes=0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours, minutes=minutes)


def _make_agent_logs(db, lead_id: str, verdict: str, days_ago: int):
    nodes = CORE_NODES + [VERDICT_NODES.get(verdict, "sync_crm")]
    t = _ago(days=days_ago, hours=2)
    for name in nodes:
        t = t + timedelta(seconds=random.randint(800, 4000))
        db.add(AgentLog(
            lead_id=lead_id, agent_name=name,
            duration_ms=random.randint(300, 4500), success=True,
            input_data={"lead_id": lead_id},
            output_data={"status": "ok", "node": name},
            created_at=t,
        ))


def _make_intent_signals(db, lead_id: str, verdict: str, days_ago: int):
    n = {"Hot": 6, "Warm": 3, "Cold": 1}[verdict]
    for sig_type, score, source in INTENT_SIGNAL_TYPES[:n]:
        db.add(IntentSignal(
            lead_id=lead_id, signal_type=sig_type,
            score=score * random.uniform(0.85, 1.0), source=source,
            signal_metadata={"triggered": True}, captured_at=_ago(days=days_ago),
        ))


def _make_outreach(db, lead_id: str, seq_id: str, verdict: str, days_ago: int, company: str, industry: str):
    if verdict == "Cold":
        return
    patterns = {
        "Hot":  [("sent", True, True), ("sent", True, False), ("scheduled", False, False)],
        "Warm": [("sent", True, False), ("sent", False, False), ("scheduled", False, False)],
    }
    for step_num, (status, opened, replied) in enumerate(patterns[verdict], 1):
        sent_at = _ago(days=days_ago - step_num * 3) if status == "sent" else None
        db.add(OutreachEmail(
            lead_id=lead_id, sequence_id=seq_id, step_number=step_num,
            subject=SUBJECTS[step_num - 1].format(company=company, industry=industry),
            body=f"Demo email body — step {step_num}.",
            status="replied" if replied else status,
            scheduled_at=_ago(days=days_ago - step_num * 3 + 1),
            sent_at=sent_at,
            opened_at=_ago(days=days_ago - step_num * 3, hours=2) if opened else None,
            replied_at=_ago(days=days_ago - step_num * 3, hours=4) if replied else None,
        ))


def _make_booking(db, lead_id: str, days_ago: int):
    db.add(BookingRequest(
        lead_id=lead_id, status="confirmed",
        booking_link="https://cal.com/autonomoussdr/30min",
        notes="Discovery call booked via outreach sequence.",
        start_time=_ago(days=days_ago - 7),
        end_time=_ago(days=days_ago - 7, hours=-1),
        created_at=_ago(days=days_ago),
    ))


def _make_conversation(db, lead_id: str, first_name: str, company: str, days_ago: int):
    messages, t = [], _ago(days=days_ago)
    for role, tpl in CONVERSATION_MSGS[:4]:
        t += timedelta(hours=random.randint(1, 8))
        messages.append({"role": role, "content": tpl.format(first_name=first_name, company=company), "timestamp": t.isoformat(), "channel": "email"})
    db.add(Conversation(
        lead_id=lead_id, channel="email", messages=messages,
        summary=f"Engaged prospect at {company}. Interest confirmed; pricing discussed. Next step: demo call.",
        created_at=_ago(days=days_ago), updated_at=t,
    ))


def _insert_lead(db, name, email, company, source, status, verdict,
                 job_title, seniority, company_size, industry, revenue_estimate,
                 tech_stack, bant, reasoning, seq_id, days_ago,
                 conversion_status="unqualified", quality=None, completeness=None):
    if quality is None:
        quality = {"Hot": (0.78, 0.96), "Warm": (0.58, 0.80), "Cold": (0.38, 0.62)}[verdict]
    if completeness is None:
        completeness = {"Hot": (0.82, 0.98), "Warm": (0.68, 0.88), "Cold": (0.48, 0.72)}[verdict]

    lead = Lead(
        name=name, email=email, company=company, source=source,
        status=status, tags=["demo"], archived=False,
        data_quality_score=round(random.uniform(*quality), 2),
        completeness_score=round(random.uniform(*completeness), 2),
        conversion_status=conversion_status,
        created_at=_ago(days=days_ago),
        updated_at=_ago(days=days_ago - 1),
    )
    db.add(lead)
    db.flush()

    enr = Enrichment(
        lead_id=lead.id, job_title=job_title, seniority=seniority,
        company_size=company_size, industry=industry, revenue_estimate=revenue_estimate,
        tech_stack=tech_stack, confidence=round(random.uniform(0.70, 0.95), 2),
        enrichment_source="synthetic",
    )
    db.add(enr)
    db.flush()

    confidence = round(sum(bant.values()) / 4, 2)
    db.add(Verdict(
        lead_id=lead.id, enrichment_id=enr.id,
        analysis_verdict=verdict, final_verdict=verdict,
        bant_scores=bant, confidence_score=confidence,
        icp_match=(verdict != "Cold"), validated=True,
        analysis_reasoning=reasoning,
        consistency_notes="BANT scores consistent with final verdict." if verdict != "Cold" else "Lead outside ICP. Routed to CRM for archival.",
    ))

    _make_agent_logs(db, lead.id, verdict, days_ago)
    _make_intent_signals(db, lead.id, verdict, days_ago)
    _make_outreach(db, lead.id, seq_id, verdict, days_ago, company, industry)
    if verdict == "Hot":
        _make_booking(db, lead.id, days_ago)
        _make_conversation(db, lead.id, name.split()[0], company, days_ago)

    return lead


# ---------------------------------------------------------------------------
# Date distribution — realistic 30-day intake pattern
# ---------------------------------------------------------------------------

def _daily_counts(total: int, days: int = 30) -> list:
    """
    Generate a realistic-looking daily lead intake distribution over N days.
    Simulates: slow start → campaign spike around day 10 → steady state → recent uptick.
    """
    weights = []
    for d in range(days):
        day_from_start = days - d  # d=0 is today, d=29 is 30 days ago
        # baseline
        w = 1.0
        # campaign spike ~20 days ago
        w += 3.0 * max(0, 1 - abs(day_from_start - 20) / 4)
        # recent activity uptick (last 5 days)
        if day_from_start <= 5:
            w += 1.5
        weights.append(w)

    total_w = sum(weights)
    counts = []
    remaining = total
    for i, w in enumerate(weights[:-1]):
        n = max(0, round(total * w / total_w))
        counts.append(n)
        remaining -= n
    counts.append(max(0, remaining))
    return counts  # counts[0] = today, counts[29] = 30 days ago


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(db):
    existing = db.query(Lead).filter(Lead.tags.contains(["demo"])).count()
    if existing > 0:
        print(f"  ✓ Demo data already present ({existing} leads) — skipping.")
        print("  To re-seed, delete demo leads first: DELETE FROM leads WHERE tags @> '[\"demo\"]';")
        return

    # ── Outreach sequences ───────────────────────────────────────────────────
    print("  Creating outreach sequences…")
    seq_a = OutreachSequence(name="Value-First 3-Step (Variant A)", ab_variant="A", is_active=True, steps=[])
    seq_b = OutreachSequence(name="Problem-Led 3-Step (Variant B)", ab_variant="B", is_active=True, steps=[])
    db.add_all([seq_a, seq_b])
    db.flush()

    db.add(ABTestResult(sequence_id=seq_a.id, variant="A", emails_sent=61, emails_opened=28, replies=11, meetings_booked=7, conversions=6))
    db.add(ABTestResult(sequence_id=seq_b.id, variant="B", emails_sent=59, emails_opened=21, replies=7,  meetings_booked=4, conversions=3))

    # ── Optimization runs — 6 runs showing the system learning ─────────────
    print("  Creating optimization history (6 runs)…")
    opt_runs = [
        # run_at,      old_weights (uniform),                                  new_weights,                                                  improvement, sample, notes
        (_ago(days=28), {"budget": 0.25, "authority": 0.25, "need": 0.25, "timeline": 0.25}, {"budget": 0.26, "authority": 0.27, "need": 0.26, "timeline": 0.21}, 0.02, 8,  "First run — insufficient sample. Minor adjustment."),
        (_ago(days=21), {"budget": 0.26, "authority": 0.27, "need": 0.26, "timeline": 0.21}, {"budget": 0.24, "authority": 0.30, "need": 0.28, "timeline": 0.18}, 0.04, 15, "Authority emerging as stronger signal. Budget slightly down."),
        (_ago(days=14), {"budget": 0.24, "authority": 0.30, "need": 0.28, "timeline": 0.18}, {"budget": 0.22, "authority": 0.33, "need": 0.30, "timeline": 0.15}, 0.07, 23, "Pattern confirmed: authority and need dominate. Timeline weight reduced."),
        (_ago(days=10), {"budget": 0.22, "authority": 0.33, "need": 0.30, "timeline": 0.15}, {"budget": 0.21, "authority": 0.35, "need": 0.30, "timeline": 0.14}, 0.03, 19, "Marginal adjustment — weights stabilising around new optimum."),
        (_ago(days=5),  {"budget": 0.21, "authority": 0.35, "need": 0.30, "timeline": 0.14}, {"budget": 0.20, "authority": 0.36, "need": 0.31, "timeline": 0.13}, 0.02, 27, "Stable. Authority at 36% — strong predictor in SaaS/FinTech cohort."),
        (_ago(days=1),  {"budget": 0.20, "authority": 0.36, "need": 0.31, "timeline": 0.13}, {"budget": 0.19, "authority": 0.37, "need": 0.31, "timeline": 0.13}, 0.01, 31, "Convergence. Weights near optimal for current lead cohort."),
    ]
    for run_at, old_w, new_w, improvement, sample, notes in opt_runs:
        db.add(OptimizationRun(
            run_at=run_at, old_weights=old_w, new_weights=new_w,
            improvement_score=improvement, sample_size=sample, notes=notes,
        ))

    # ── Build date assignment maps using realistic distribution ──────────────
    # Curated hot/warm/cold
    n_hot_curated = len(HOT_PERSONAS)
    n_warm_curated = len(WARM_PERSONAS)
    n_cold_curated = len(COLD_PERSONAS)

    # Parametric additional leads
    n_hot_gen   = len(COMPANIES_HOT)     # 20
    n_warm_gen  = len(COMPANIES_WARM)    # 15
    n_cold_gen  = len(COMPANIES_COLD)    # 8

    total_complete = n_hot_curated + n_warm_curated + n_cold_curated + n_hot_gen + n_warm_gen + n_cold_gen
    daily = _daily_counts(total_complete, days=30)

    # Assign a days_ago to each lead by sampling from the distribution
    day_pool = []
    for days_ago, count in enumerate(daily):
        day_pool.extend([days_ago] * count)
    random.shuffle(day_pool)
    day_iter = iter(day_pool + [random.randint(0, 30) for _ in range(20)])  # padding

    def next_day():
        try:
            return next(day_iter)
        except StopIteration:
            return random.randint(1, 28)

    # ── Curated Hot leads ────────────────────────────────────────────────────
    print(f"  Seeding {n_hot_curated} curated Hot leads…")
    for i, p in enumerate(HOT_PERSONAS):
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        _insert_lead(
            db, p["name"], p["email"], p["company"], p["source"],
            "complete", "Hot", p["job_title"], p["seniority"],
            p["company_size"], p["industry"], p["revenue_estimate"],
            p["tech_stack"], p["bant"], p["reasoning"], seq_id, next_day(),
            conversion_status=p.get("conversion_status", "unqualified"),
        )
        print(f"    + Hot: {p['name']} @ {p['company']}")

    # ── Curated Warm leads ───────────────────────────────────────────────────
    print(f"  Seeding {n_warm_curated} curated Warm leads…")
    for i, p in enumerate(WARM_PERSONAS):
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        _insert_lead(
            db, p["name"], p["email"], p["company"], p["source"],
            "complete", "Warm", p["job_title"], p["seniority"],
            p["company_size"], p["industry"], p["revenue_estimate"],
            p["tech_stack"], p["bant"], p["reasoning"], seq_id, next_day(),
        )
        print(f"    + Warm: {p['name']} @ {p['company']}")

    # ── Curated Cold leads ───────────────────────────────────────────────────
    print(f"  Seeding {n_cold_curated} curated Cold leads…")
    for p in COLD_PERSONAS:
        _insert_lead(
            db, p["name"], p["email"], p["company"], p["source"],
            "complete", "Cold", p["job_title"], p["seniority"],
            p["company_size"], p["industry"], p["revenue_estimate"],
            p.get("tech_stack", []), p["bant"], p["reasoning"], seq_a.id, next_day(),
            conversion_status="lost",
        )

    # ── Generated Hot leads ──────────────────────────────────────────────────
    print(f"  Generating {n_hot_gen} additional Hot leads…")
    used_emails: set = set()
    for i, (company, industry, company_size, revenue) in enumerate(COMPANIES_HOT):
        first = random.choice(FIRST_NAMES)
        last  = random.choice(LAST_NAMES)
        name  = f"{first} {last}"
        email = f"{first[0].lower()}.{last.lower()}@{company.lower().replace(' ', '-')}.com"
        if email in used_emails:
            email = f"{first.lower()}.{last.lower()}{i}@{company.lower().replace(' ', '-')}.com"
        used_emails.add(email)

        title, seniority = random.choice(TITLES_HOT)
        stack = random.choice(TECH_STACKS_HOT)
        bant = {
            "budget":    round(random.uniform(0.72, 0.93), 2),
            "authority": round(random.uniform(0.78, 0.97), 2),
            "need":      round(random.uniform(0.75, 0.92), 2),
            "timeline":  round(random.uniform(0.68, 0.88), 2),
        }
        reasoning = (
            f"{first} is {title} at {company}, a {company_size}-person {industry} company. "
            f"Strong BANT alignment with budget confirmed, clear authority, and a Q1-Q2 timeline."
        )
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        _insert_lead(
            db, name, email, company, random.choice(SOURCES),
            "complete", "Hot", title, seniority, company_size, industry, revenue,
            stack, bant, reasoning, seq_id, next_day(),
        )

    # ── Generated Warm leads ─────────────────────────────────────────────────
    print(f"  Generating {n_warm_gen} additional Warm leads…")
    for i, (company, industry, company_size, revenue) in enumerate(COMPANIES_WARM):
        first = random.choice(FIRST_NAMES)
        last  = random.choice(LAST_NAMES)
        name  = f"{first} {last}"
        email = f"{first[0].lower()}.{last.lower()}@{company.lower().replace(' ', '-')}.com"
        if email in used_emails:
            email = f"{first.lower()}.{last.lower()}{i+100}@{company.lower().replace(' ', '-')}.com"
        used_emails.add(email)

        title, seniority = random.choice(TITLES_WARM)
        stack = random.choice(TECH_STACKS_WARM)
        bant = {
            "budget":    round(random.uniform(0.45, 0.65), 2),
            "authority": round(random.uniform(0.55, 0.80), 2),
            "need":      round(random.uniform(0.60, 0.80), 2),
            "timeline":  round(random.uniform(0.38, 0.60), 2),
        }
        reasoning = random.choice(WARM_REASONINGS)
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        _insert_lead(
            db, name, email, company, random.choice(SOURCES),
            "complete", "Warm", title, seniority, company_size, industry, revenue,
            stack, bant, reasoning, seq_id, next_day(),
        )

    # ── Generated Cold leads ─────────────────────────────────────────────────
    print(f"  Generating {n_cold_gen} additional Cold leads…")
    for i, (company, industry, company_size, revenue) in enumerate(COMPANIES_COLD):
        first = random.choice(FIRST_NAMES)
        last  = random.choice(LAST_NAMES)
        name  = f"{first} {last}"
        email = f"{first[0].lower()}.{last.lower()}@{company.lower().replace(' ', '-')}.com"
        if email in used_emails:
            email = f"{first.lower()}.{last.lower()}{i+200}@{company.lower().replace(' ', '-')}.com"
        used_emails.add(email)

        title, seniority = random.choice(TITLES_COLD)
        stack = random.choice(TECH_STACKS_COLD)
        bant = {
            "budget":    round(random.uniform(0.08, 0.28), 2),
            "authority": round(random.uniform(0.10, 0.35), 2),
            "need":      round(random.uniform(0.15, 0.38), 2),
            "timeline":  round(random.uniform(0.08, 0.25), 2),
        }
        _insert_lead(
            db, name, email, company, random.choice(SOURCES),
            "complete", "Cold", title, seniority, company_size, industry, revenue,
            stack, bant, random.choice(COLD_REASONINGS), seq_a.id, next_day(),
            conversion_status="lost",
        )

    # ── In-flight leads ──────────────────────────────────────────────────────
    print("  Seeding in-flight and failed leads…")
    inflight = [
        ("Isaac Mensah",    "i.mensah@proptech-hub.com",   "PropTech Hub",      "linkedin_signal", "processing"),
        ("Chiara Romano",   "c.romano@cloudnative.it",     "CloudNative.it",    "website_form",    "processing"),
        ("Jack Morrison",   "j.morrison@saasco.io",        "SaaSCo",            "marketing_ad",    "pending"),
        ("Aisha Kamara",    "a.kamara@techrise.africa",    "TechRise Africa",   "event",           "pending"),
        ("Mikael Ström",    "m.strom@nordicsaas.se",       "NordicSaaS",        "inbound_email",   "processing"),
        ("Hemi Walker",     "h.walker@pacificops.nz",      "PacificOps",        "website_form",    "pending"),
        ("Unknown Contact", "noreply@tempmail.xyz",         "Unknown",           "website_form",    "failed"),
        ("Test Lead",       "test@disposable.com",          "Test Corp",         "marketing_ad",    "failed"),
        ("Invalid Data",    "bad-email",                    "",                  "website_form",    "failed"),
    ]
    for name, email, company, source, status in inflight:
        minutes = random.randint(5, 60) if status in ("processing", "pending") else None
        days_f  = random.randint(1, 5)  if status == "failed" else None
        db.add(Lead(
            name=name, email=email, company=company, source=source,
            status=status, tags=["demo"], archived=False,
            created_at=_ago(minutes=minutes) if minutes else _ago(days=days_f),
        ))

    db.commit()

    hot_total  = n_hot_curated + n_hot_gen
    warm_total = n_warm_curated + n_warm_gen
    cold_total = n_cold_curated + n_cold_gen
    grand_total = hot_total + warm_total + cold_total + len(inflight)

    print(f"\n  ✓ Seeded {grand_total} leads:")
    print(f"     {hot_total} Hot  ·  {warm_total} Warm  ·  {cold_total} Cold  ·  {len(inflight)} in-flight/failed")
    print("  ✓ 2 outreach sequences (A/B test — Variant A leading)")
    print("  ✓ 6 optimization runs showing BANT weight convergence over 28 days")
    print("  ✓ Leads distributed across 30 days with campaign spike simulation")


if __name__ == "__main__":
    print("AutonomousSDR — Demo Data Seeder")
    print("=" * 45)
    create_all_tables()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    print("\nDone. Start the app and visit http://localhost:5173")
