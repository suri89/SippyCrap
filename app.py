import streamlit as st
import asyncio
import pandas as pd
import re
import io
import subprocess
import sys
import os
import concurrent.futures

# ─────────────────────────────────────────────
# INSTALL PLAYWRIGHT BROWSERS (RUNS EVERY COLD START)
# ─────────────────────────────────────────────
chrome_path = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"
)
if not os.path.exists(chrome_path):
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        capture_output=False
    )

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Dental Scraper",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background: #0d1117;
    color: #e6edf3;
}

h1, h2, h3 {
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
}

.main-header {
    text-align: center;
    padding: 2.5rem 0 1rem 0;
}

.main-header h1 {
    font-size: 2.8rem;
    font-weight: 600;
    background: linear-gradient(135deg, #58a6ff 0%, #79c0ff 50%, #a5d6ff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.4rem;
}

.main-header p {
    color: #8b949e;
    font-size: 1.05rem;
    font-weight: 300;
}

.stat-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 1.2rem;
    text-align: center;
}

.stat-number {
    font-size: 2rem;
    font-weight: 600;
    color: #58a6ff;
}

.stat-label {
    font-size: 0.8rem;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.success-stat { color: #3fb950; }
.fail-stat    { color: #f85149; }

div[data-testid="stTextArea"] textarea {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
}

div[data-testid="stTextArea"] textarea:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,0.15) !important;
}

div[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg, #238636, #2ea043) !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    padding: 0.7rem 2rem !important;
    border-radius: 8px !important;
    width: 100%;
    transition: all 0.2s ease !important;
}

div[data-testid="stButton"] button[kind="primary"]:hover {
    background: linear-gradient(135deg, #2ea043, #3fb950) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 15px rgba(46,160,67,0.3) !important;
}

div[data-testid="stButton"] button[kind="secondary"] {
    background: #21262d !important;
    color: #58a6ff !important;
    border: 1px solid #30363d !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    width: 100%;
}

div[data-testid="stDataFrame"] {
    border: 1px solid #30363d !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

.url-count-badge {
    display: inline-block;
    background: #1f3a5f;
    color: #58a6ff;
    border: 1px solid #1f6feb;
    border-radius: 20px;
    padding: 0.2rem 0.9rem;
    font-size: 0.85rem;
    font-weight: 500;
    margin-bottom: 1rem;
}

.how-it-works {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.how-it-works li {
    color: #8b949e;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────
def clean_url(url):
    url = url.strip()
    utm_pattern = re.compile(
        r'[?&](utm_source|utm_medium|utm_campaign|utm_content|utm_term'
        r'|y_source|_vsrefdom|sc_cid|gclid|fbclid|ref)[^&]*',
        re.IGNORECASE
    )
    url = utm_pattern.sub('', url)
    url = re.sub(r'[?&]+$', '', url)
    return url.strip()


def extract_names(text):
    found_names = set()

    dr_names = re.findall(
        r'Dr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}', text
    )
    found_names.update(dr_names)

    dds_names = re.findall(
        r'[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+,?\s+(?:DDS|DMD|RDH|NMD|DPM)', text
    )
    found_names.update(dds_names)

    doc_names = re.findall(
        r'(?:Doctor|Dentist|Hygienist|Specialist|Orthodontist|Periodontist|Endodontist)'
        r'\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}',
        text
    )
    found_names.update(doc_names)

    return [n.strip().rstrip(',') for n in found_names if len(n.strip()) > 4]


def find_team_links(base_url, markdown_text):
    team_keywords = [
        '/team', '/about', '/doctors', '/staff', '/meet',
        '/providers', '/our-team', '/meet-the-team',
        '/about-us', '/our-doctors', '/our-staff', '/dentist'
    ]
    found_links = []
    links = re.findall(r'\[.*?\]\((.*?)\)', markdown_text)

    for link in links:
        if not link or link.startswith('#') or link.startswith('mailto'):
            continue
        for keyword in team_keywords:
            if keyword in link.lower():
                if link.startswith('http'):
                    found_links.append(link)
                else:
                    found_links.append(base_url.rstrip('/') + '/' + link.lstrip('/'))
                break

    return list(set(found_links))[:3]


# ─────────────────────────────────────────────
# ASYNC SCRAPER — no Streamlit calls inside!
# ─────────────────────────────────────────────
async def scrape_and_extract(urls):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        ignore_https_errors=True,
        java_script_enabled=True,
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=40000,
        word_count_threshold=5,
        remove_overlay_elements=True,
        magic=True,
        simulate_user=True,
        wait_until="domcontentloaded",
    )

    retry_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=60000,
        word_count_threshold=3,
        remove_overlay_elements=True,
        magic=True,
        simulate_user=True,
        wait_until="networkidle",
    )

    all_data    = []
    results_map = {}

    async with AsyncWebCrawler(config=browser_config) as crawler:

        # PASS 1
        homepage_results = await crawler.arun_many(
            urls=urls, config=run_config, max_concurrent=50
        )

        failed_urls = []
        for result in homepage_results:
            if result.success and result.markdown.strip():
                results_map[result.url] = result
            else:
                failed_urls.append(result.url)

        # PASS 2 — retry failed
        if failed_urls:
            retry_results = await crawler.arun_many(
                urls=failed_urls, config=retry_config, max_concurrent=20
            )
            still_failed = []
            for result in retry_results:
                if result.success and result.markdown.strip():
                    results_map[result.url] = result
                else:
                    still_failed.append(result.url)
            failed_urls = still_failed

        # PASS 3 — team/about pages
        team_urls_map = {}
        for url, result in results_map.items():
            for tl in find_team_links(url, result.markdown):
                team_urls_map[tl] = url

        team_results = {}
        if team_urls_map:
            team_scrape = await crawler.arun_many(
                urls=list(team_urls_map.keys()), config=run_config, max_concurrent=30
            )
            for tr in team_scrape:
                if tr.success:
                    original = team_urls_map.get(tr.url, tr.url)
                    team_results[original] = team_results.get(original, "") + "\n" + tr.markdown

        # EXTRACT NAMES
        for url in urls:
            if url in results_map:
                result    = results_map[url]
                full_text = result.markdown + "\n" + team_results.get(url, "")
                names     = extract_names(full_text)
                names_str = " | ".join(names) if names else "No names found"
                title     = result.metadata.get("title", "N/A")
                all_data.append({
                    "Website URL":            url,
                    "Status":                 "✅ SUCCESS",
                    "Page Title":             title,
                    "Doctors & Team Members": names_str,
                })
            else:
                all_data.append({
                    "Website URL":            url,
                    "Status":                 "❌ FAILED",
                    "Page Title":             "",
                    "Doctors & Team Members": "Could not load site",
                })

    return all_data


def run_scraper_sync(urls):
    """Run async scraper in a fresh thread with its own event loop"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, scrape_and_extract(urls))
        return future.result()


# ─────────────────────────────────────────────
# UI — HEADER
# ─────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🦷 Dental Website Scraper</h1>
    <p>Extract doctor names & team members from any dental clinic website</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ─────────────────────────────────────────────
# UI — TWO COLUMN LAYOUT
# ─────────────────────────────────────────────
left_col, right_col = st.columns([3, 2], gap="large")

with left_col:
    st.markdown("### 📋 Paste Your URLs")
    st.caption("One URL per line — you can paste up to 200 at once")

    url_input = st.text_area(
        label="urls",
        label_visibility="collapsed",
        height=280,
        placeholder="https://castordds.com\nhttps://waltonfamilydentistry.com\nhttps://northaustindentist.com\n..."
    )

    urls = []
    if url_input.strip():
        raw  = [line.strip() for line in url_input.strip().splitlines() if line.strip()]
        urls = [clean_url(u) for u in raw if u.startswith('http')]

    if urls:
        st.markdown(f'<div class="url-count-badge">📊 {len(urls)} URLs ready to scrape</div>', unsafe_allow_html=True)

    run_btn = st.button(
        "🚀 Start Scraping" if urls else "🚀 Start Scraping (paste URLs above)",
        type="primary",
        disabled=len(urls) == 0
    )

with right_col:
    st.markdown("### ℹ️ How It Works")
    st.markdown("""
<div class="how-it-works">
<ol>
<li>Paste all your dental website URLs on the left</li>
<li>Click <strong>Start Scraping</strong></li>
<li>It automatically visits each site + their team/about pages</li>
<li>Extracts all <strong>Dr. Names</strong>, <strong>DDS/DMD</strong> credentials, and staff</li>
<li>Download results as <strong>Excel or CSV</strong></li>
</ol>
</div>
""", unsafe_allow_html=True)

    st.markdown("### 🔍 What Gets Extracted")
    st.markdown("""
- `Dr. John Smith` style names  
- `John Smith, DDS` / `DMD` / `RDH`  
- Dentist, Hygienist, Specialist names  
- Team & About page data  
""")

    st.markdown("### ⏱️ Estimated Time")
    if urls:
        mins = max(1, round(len(urls) * 0.4 / 60, 1))
        st.info(f"~{mins} minutes for {len(urls)} URLs")
    else:
        st.info("~1 min per 25 URLs")

# ─────────────────────────────────────────────
# SCRAPING LOGIC
# ─────────────────────────────────────────────
if run_btn and urls:
    st.markdown("---")
    st.markdown("### ⚡ Scraping Progress")

    status_box   = st.empty()
    progress_bar = st.progress(0, text="Starting...")

    status_box.info(f"🚀 Scraping {len(urls)} websites — please wait, this may take a few minutes...")
    progress_bar.progress(10, text="Scraping in progress...")

    try:
        results = run_scraper_sync(urls)
        st.session_state['results'] = results
        st.session_state['scraped'] = True
        progress_bar.progress(100, text="✅ Complete!")
        status_box.success("🎉 Scraping complete!")

    except Exception as e:
        import traceback
        status_box.error(f"❌ Error: {type(e).__name__}: {str(e)}")
        st.code(traceback.format_exc(), language="python")
        st.stop()

# ─────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────
if st.session_state.get('scraped') and 'results' in st.session_state:
    df = pd.DataFrame(st.session_state['results'])

    success_count = len(df[df['Status'].str.contains('SUCCESS', na=False)])
    failed_count  = len(df[df['Status'].str.contains('FAILED',  na=False)])
    names_found   = len(df[df['Doctors & Team Members'] != 'No names found'])

    st.markdown("---")
    st.markdown("### 📊 Results")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="stat-box"><div class="stat-number">{len(df)}</div><div class="stat-label">Total Sites</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="stat-box"><div class="stat-number success-stat">{success_count}</div><div class="stat-label">Scraped OK</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="stat-box"><div class="stat-number fail-stat">{failed_count}</div><div class="stat-label">Failed</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="stat-box"><div class="stat-number">{names_found}</div><div class="stat-label">Names Found</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_all, tab_success, tab_failed = st.tabs([
        f"All ({len(df)})",
        f"✅ Success ({success_count})",
        f"❌ Failed ({failed_count})"
    ])

    with tab_all:
        st.dataframe(df, use_container_width=True, height=400)

    with tab_success:
        df_ok = df[df['Status'].str.contains('SUCCESS', na=False)]
        st.dataframe(df_ok, use_container_width=True, height=400)

    with tab_failed:
        df_fail = df[df['Status'].str.contains('FAILED', na=False)]
        st.dataframe(df_fail, use_container_width=True, height=400)

    st.markdown("### 💾 Download Results")
    dl_col1, dl_col2, _ = st.columns([1, 1, 2])

    with dl_col1:
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download CSV",
            data=csv_bytes,
            file_name="dental_scraper_results.csv",
            mime="text/csv"
        )

    with dl_col2:
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='All Results')
            df[df['Status'].str.contains('SUCCESS', na=False)].to_excel(writer, index=False, sheet_name='Success Only')
            df[df['Status'].str.contains('FAILED',  na=False)].to_excel(writer, index=False, sheet_name='Failed')
        st.download_button(
            label="📥 Download Excel",
            data=excel_buf.getvalue(),
            file_name="dental_scraper_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
