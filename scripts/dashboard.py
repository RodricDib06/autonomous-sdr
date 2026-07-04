#!/usr/bin/env python3
"""
Simple dashboard for reviewing AutonomousSDR leads
"""
import requests
from typing import Dict, List, Any

class LeadDashboard:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics"""
        response = requests.get(f"{self.base_url}/leads/stats")
        return response.json()
    
    def get_hot_leads(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get high-priority leads"""
        response = requests.get(f"{self.base_url}/leads/hot", params={"limit": limit})
        return response.json()["hot_leads"]
    
    def get_recent_leads(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recently processed leads"""
        response = requests.get(f"{self.base_url}/leads", params={"limit": limit})
        return response.json()
    
    def export_leads(self, verdict_filter: str = None, min_confidence: float = 0.0) -> Dict[str, Any]:
        """Export leads for CRM integration"""
        params = {}
        if verdict_filter:
            params["verdict_filter"] = verdict_filter
        if min_confidence > 0:
            params["min_confidence"] = min_confidence
            
        response = requests.get(f"{self.base_url}/leads/export", params=params)
        return response.json()

def display_stats(stats: Dict[str, Any]):
    """Display statistics in a nice format"""
    print("📊 AutonomousSDR Dashboard")
    print("=" * 40)
    print(f"Total Leads: {stats['total_leads']}")
    print(f"Completed: {stats['completed']}")
    print(f"Failed: {stats['failed']}")
    print(f"Processing: {stats['processing']}")
    print(".1%")
    
    verdict_breakdown = stats['verdict_breakdown']
    print("\n🎯 Verdict Breakdown:")
    print(f"  Hot leads: {verdict_breakdown['hot']}")
    print(f"  Warm leads: {verdict_breakdown['warm']}")
    print(f"  Cold leads: {verdict_breakdown['cold']}")

def display_hot_leads(hot_leads: List[Dict[str, Any]]):
    """Display hot leads in a readable format"""
    if not hot_leads:
        print("\n❄️ No hot leads found")
        return
        
    print(f"\n🔥 Top {len(hot_leads)} Hot Leads:")
    print("-" * 60)
    
    for i, lead in enumerate(hot_leads, 1):
        print(f"{i}. {lead['name']} @ {lead['company']}")
        print(f"   Email: {lead['email']}")
        print(f"   Title: {lead.get('job_title', 'Unknown')}")
        print(f"   Industry: {lead.get('industry', 'Unknown')}")
        print(".1f")
        if lead.get('reasoning'):
            # Truncate long reasoning
            reasoning = lead['reasoning'][:100] + "..." if len(lead['reasoning']) > 100 else lead['reasoning']
            print(f"   Why: {reasoning}")
        print()

def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        print("Usage: python dashboard.py [api_url]")
        print("Example: python dashboard.py http://localhost:8000")
        print("\nShows statistics and hot leads from your AutonomousSDR pipeline.")
        sys.exit(0)
    
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    try:
        dashboard = LeadDashboard(base_url)
        
        # Get and display stats
        stats = dashboard.get_stats()
        display_stats(stats)
        
        # Get and display hot leads
        hot_leads = dashboard.get_hot_leads(limit=5)
        display_hot_leads(hot_leads)
        
        print("💡 Next Steps:")
        print("• Review hot leads above for immediate sales follow-up")
        print("• Export qualified leads: curl http://localhost:8000/leads/export")
        print("• Integrate with your CRM using the export endpoint")
        print("• Set up notifications for new hot leads")
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {base_url}")
        print("Make sure the AutonomousSDR API server is running.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()