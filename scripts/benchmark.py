#!/usr/bin/env python3
"""
Performance benchmark for AutonomousSDR pipeline
"""
import time
import requests
import sys

def time_function(func, *args, **kwargs):
    """Time a function execution"""
    start = time.time()
    result = func(*args, **kwargs)
    end = time.time()
    return result, end - start

def submit_lead(base_url: str, lead_data: dict) -> bool:
    """Submit a single lead and return success"""
    try:
        response = requests.post(f"{base_url}/leads", json=lead_data, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def benchmark_pipeline(base_url: str, num_leads: int = 10) -> dict:
    """Benchmark the pipeline with multiple leads"""
    print(f"Benchmarking with {num_leads} leads...")

    # Get initial lead count to track only new leads
    try:
        response = requests.get(f"{base_url}/leads", timeout=10)
        initial_lead_count = len(response.json()) if response.status_code == 200 else 0
    except requests.RequestException:
        initial_lead_count = 0

    # Sample lead data - use realistic names like the test data generator
    first_names = ["Sarah", "James", "Emily", "Michael", "Jessica", "David", "Rachel", "Kevin", "Amanda", "Ryan"]
    last_names = ["Chen", "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson"]
    
    submitted_leads = []

    # Submit leads
    submit_times = []
    for i in range(num_leads):
        first = first_names[i % len(first_names)]
        last = last_names[i % len(last_names)]
        domain = "techcorp.com"
        company = "TechCorp"
        
        lead_data = {
            "name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}@{domain}",
            "company": company
        }
        submitted_leads.append(lead_data)

        success, submit_time = time_function(submit_lead, base_url, lead_data)
        if success:
            submit_times.append(submit_time)
            print(f"✓ Submitted {lead_data['name']} @ {lead_data['company']} ({submit_time:.1f}s)")
        else:
            print(f"✗ Failed to submit {lead_data['name']}")

    # Wait for processing and check completion
    print("\nWaiting for processing...")
    time.sleep(5)  # Give time for processing

    # Check how many NEW leads completed
    try:
        response = requests.get(f"{base_url}/leads", timeout=10)
        if response.status_code == 200:
            all_leads = response.json()
            new_leads = all_leads[initial_lead_count:]  # Only count leads added in this benchmark
            
            completed = sum(1 for lead in new_leads if lead.get("status") == "complete")
            failed = sum(1 for lead in new_leads if lead.get("status") == "failed")
            processing = sum(1 for lead in new_leads if lead.get("status") == "processing")

            avg_submit_time = sum(submit_times) / len(submit_times) if submit_times else 0
            total_time = sum(submit_times) + 5  # Include processing wait time
            throughput = len(submit_times) / total_time if total_time > 0 else 0

            return {
                "total_submitted": len(submit_times),
                "avg_submit_time": avg_submit_time,
                "completed": completed,
                "failed": failed,
                "processing": processing,
                "success_rate": completed / len(submit_times) if submit_times else 0,
                "throughput": throughput,
                "total_time": total_time
            }
    except Exception as e:
        print(f"Error checking results: {e}")
        return {"error": str(e)}

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ['--help', '-h']:
        print("Usage: python benchmark.py <api_url> [num_leads]")
        print("Example: python benchmark.py http://localhost:8000 20")
        print("\nThis benchmark:")
        print("- Submits leads to your API")
        print("- Measures submission speed and success rate")
        print("- Waits for background processing to complete")
        print("- Reports on completion rates and throughput")
        sys.exit(0)

    base_url = sys.argv[1]
    num_leads = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    print("🚀 AutonomousSDR Pipeline Benchmark")
    print("=" * 40)

    # Test API connectivity
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            service = response.json().get("service", "unknown")
            print(f"✓ Connected to {service} API at {base_url}")
        else:
            print(f"✗ API not responding (status {response.status_code})")
            sys.exit(1)
    except Exception as e:
        print(f"✗ Cannot connect to API: {e}")
        sys.exit(1)

    # Run benchmark
    results, total_time = time_function(benchmark_pipeline, base_url, num_leads)

    if "error" in results:
        print(f"✗ Benchmark failed: {results['error']}")
        sys.exit(1)

    print("\n📊 Results:")
    print(f"  Total leads submitted: {results['total_submitted']}")
    print(f"  Average submit time: {results['avg_submit_time']:.2f}s")
    print(f"  Completed: {results['completed']}")
    print(f"  Failed: {results['failed']}")
    if 'processing' in results:
        print(f"  Still processing: {results['processing']}")
    print(f"  Success rate: {results['success_rate']:.1%}")
    if 'throughput' in results:
        print(f"  Throughput: {results['throughput']:.2f} leads/second")
    if 'total_time' in results:
        print(f"  Total time: {results['total_time']:.1f}s")
    
    if results['failed'] > 0:
        print("\n⚠️  Note: 'Failed' means the lead encountered an error during processing.")
        print("   This could be due to LLM timeouts, validation errors, or other issues.")
        print("   The pipeline includes error recovery, so some failures are expected.")

    throughput = results['completed'] / total_time if total_time > 0 else 0
    print(f"Throughput: {throughput:.2f} leads/sec")

if __name__ == "__main__":
    main()