import streamlit as st
import asyncio
import pandas as pd
import re
import io
import subprocess
import sys
import os
import concurrent.futures
import gc

# CLEAR MEMORY ON FRESH TAB LOAD
if 'initialized' not in st.session_state:
    st.session_state.clear()
    gc.collect()
    st.session_state['initialized'] = True

# ─────────────────────────────────────────────
# INSTALL PLAYWRIGHT BROWSERS
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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #0d1117; color: #e6edf3; }
h1, h2, h3 { font-family: 'DM Sans', sans-serif !important; font-weight: 600 !important; }
.main-header { text-align: center; padding: 2.5rem 0 1rem 0; }
.main-header h1 { font-size: 2.8rem; font-weight: 600; background: linear-gradient(135deg, #58a6ff 0%, #79c0ff 50%, #a5d6ff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.4rem; }
.main-header p { color: #8b949e; font-size: 1.05rem; font-weight: 300; }
.stat-box { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 1.2rem; text-align: center; }
.stat-number { font-size: 2rem; font-weight: 600; color: #58a6ff; }
.stat-label { font-size: 0.8rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; }
.success-stat { color: #3fb950; }
.fail-stat { color: #f85149; }
div[data-testid="stTextArea"] textarea { background: #161b22 !important; border: 1px solid #30363d !important; color: #e6edf3 !important; font-family: 'DM Mono', monospace !important; font-size: 0.85rem !important; border-radius: 8px !important; }
div[data-testid="stButton"] button[kind="primary"] { background: linear-gradient(135deg, #238636, #2ea043) !important; color: white !important; border: none !important; font-weight: 600 !important; font-size: 1rem !important; padding: 0.7rem 2rem !important; border-radius: 8px !important; width: 100%; }
div[data-testid="stButton"] button[kind="secondary"] { background: #21262d !important; color: #58a6ff !important; border: 1px solid #30363d !important; border-radius: 8px !important; font-weight: 500 !important; width: 100%; }
.url-count-badge { display: inline-block; background: #1f3a5f; color: #58a6ff; border: 1px solid #1f6feb; border-radius: 20px; padding: 0.2rem 0.9rem; font-size: 0.85rem; font-weight: 500; margin-bottom: 1rem; }
.how-it-works { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem; }
.how-it-works li { color: #8b949e; margin-bottom: 0.5rem; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def clean_url(url):
    url = url.strip()
    utm_pattern = re.compile(
        r'[?&](utm_source|utm_medium|utm_campaign|utm_content|utm_term'
        r'|y_source|_vsrefdom|sc_cid|gclid|fbclid|ref)[^&]*', re.IGNORECASE)
    url = utm_pattern.sub('', url)
    url = re.sub(r'[?&]+$', '', url)
    return url.strip()

def extract_names(text):
    found_names = set()
    found_names.update(re.findall(r'Dr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}', text))
    found_names.update(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+,?\s+(?:DDS|DMD|RDH|NMD|DPM)', text))
    found_names.update(re.findall(r'(?:Doctor|Dentist|Hygienist|Specialist|Orthodontist|Periodontist|Endodontist)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}', text))
    return [n.strip().rstrip(',') for n in found_names if len(n.strip()) > 4]

def find_team_links(base_url, markdown_text):
    team_keywords = ['/team', '/about', '/doctors', '/staff', '/meet',
                     '/providers', '/our-team', '/meet-the-team',
                     '/about-us', '/our-doctors', '/our-staff', '/dentist']
    found_links = []
    for link in re.findall(r'\[.*?\]\((.*?)\)', markdown_text):
        if not link or link.startswith('#') or link.startswith('mailto'):
            continue
        for keyword in team_keywords:
            if keyword in link.lower():
                found_links.append(link if link.startswith('http') else base_url.rstrip('/') + '/' + link.lstrip('/'))
                break
    return list(set(found_links))[:2]  # max 2 team links per site to save memory

# ─────────────────────────────────────────────
# ASYNC SCRAPER — processes in batches
# ─────────────────────────────────────────────
async def scrape_batch(urls_batch):
    """Scrape a small batch and return only extracted data (not raw markdown)"""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    browser_config = BrowserConfig(
        headless=True, verbose=False,
        ignore_https_errors=True, java_script_enabled=True,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, page_timeout=40000,
        word_count_threshold=5, remove_overlay_elements=True,
        magic=True, simulate_user=True, wait_until="domcontentloaded",
    )
    retry_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, page_timeout=55000,
        word_count_threshold=3, remove_overlay_elements=True,
        magic=True, simulate_user=True, wait_until="networkidle",
    )

    batch_data = []
    results_map = {}

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Pass 1
        homepage_results = await crawler.arun_many(
            urls=urls_batch, config=run_config, max_concurrent=10
        )
        failed_urls = []
        for result in homepage_results:
            if result.success and result.markdown.strip():
                results_map[result.url] = {
                    'markdown': result.markdown[:50000],  # cap at 50KB per page
                    'title': result.metadata.get("title", "N/A")
                }
            else:
                failed_urls.append(result.url)
        del homepage_results
        gc.collect()

        # Pass 2 — retry
        if failed_urls:
            retry_results = await crawler.arun_many(
                urls=failed_urls, config=retry_config, max_concurrent=5
            )
            for result in retry_results:
                if result.success and result.markdown.strip():
                    results_map[result.url] = {
                        'markdown': result.markdown[:50000],
                        'title': result.metadata.get("title", "N/A")
                    }
            del retry_results
            gc.collect()

        # Pass 3 — team pages (only for successful ones)
        team_urls_map = {}
        for url, data in results_map.items():
            for tl in find_team_links(url, data['markdown']):
                team_urls_map[tl] = url

        team_extra = {}
        if team_urls_map:
            team_scrape = await crawler.arun_many(
                urls=list(team_urls_map.keys()), config=run_config, max_concurrent=5
            )
            for tr in team_scrape:
                if tr.success:
                    orig = team_urls_map.get(tr.url, tr.url)
                    team_extra[orig] = tr.markdown[:30000]  # cap team pages too
            del team_scrape
            gc.collect()

        # Extract names — only keep the final strings, not raw markdown
        for url in urls_batch:
            if url in results_map:
                data = results_map[url]
                full_text = data['markdown'] + "\n" + team_extra.get(url, "")
                names = extract_names(full_text)
                batch_data.append({
                    "Website URL": url,
                    "Status": "✅ SUCCESS",
                    "Page Title": data['title'],
                    "Doctors & Team Members": " | ".join(names) if names else "No names found",
                })
                del full_text
            else:
                batch_data.append({
                    "Website URL": url,
                    "Status": "❌ FAILED",
                    "Page Title": "",
                    "Doctors & Team Members": "Could not load site",
                })

    del results_map, team_extra
    gc.collect()
    return batch_data


def run_batch_sync(urls_batch):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, scrape_batch(urls_batch))
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

left_col, right_col = st.columns([3, 2], gap="large")

with left_col:
    st.markdown("### 📋 Paste Your URLs")
    st.caption("One URL per line — processed in batches of 10 to stay within memory limits")

    url_input = st.text_area(
        label="urls", label_visibility="collapsed", height=280,
        placeholder="https://castordds.com\nhttps://waltonfamilydentistry.com\nhttps://northaustindentist.com\n..."
    )

    urls = []
    if url_input.strip():
        raw = [line.strip() for line in url_input.strip().splitlines() if line.strip()]
        urls = [clean_url(u) for u in raw if u.startswith('http')]

    if urls:
        st.markdown(f'<div class="url-count-badge">📊 {len(urls)} URLs ready to scrape</div>', unsafe_allow_html=True)

    run_btn = st.button(
        "🚀 Start Scraping" if urls else "🚀 Start Scraping (paste URLs above)",
        type="primary", disabled=len(urls) == 0
    )

with right_col:
    st.markdown("### ℹ️ How It Works")
    st.markdown("""
<div class="how-it-works">
<ol>
<li>Paste all your dental website URLs on the left</li>
<li>Click <strong>Start Scraping</strong></li>
<li>Scrapes in batches of 10 to avoid memory limits</li>
<li>Extracts <strong>Dr. Names</strong>, <strong>DDS/DMD</strong> credentials, and staff</li>
<li>Download results as <strong>Excel or CSV</strong></li>
</ol>
</div>
""", unsafe_allow_html=True)

    st.markdown("### ⏱️ Estimated Time")
    if urls:
        batches = max(1, (len(urls) + 9) // 10)
        st.info(f"~{batches * 1}-{batches * 2} minutes for {len(urls)} URLs ({batches} batches)")
    else:
        st.info("~1-2 min per 10 URLs")

# ─────────────────────────────────────────────
# SCRAPING — batch loop
# ─────────────────────────────────────────────
BATCH_SIZE = 10

if run_btn and urls:
    st.markdown("---")
    st.markdown("### ⚡ Scraping Progress")

    status_box   = st.empty()
    progress_bar = st.progress(0, text="Starting...")

    all_results = []
    batches = [urls[i:i+BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)]
    total_batches = len(batches)

    try:
        for i, batch in enumerate(batches):
            pct = int((i / total_batches) * 100)
            progress_bar.progress(pct, text=f"Batch {i+1} of {total_batches} — scraping {len(batch)} sites...")
            status_box.info(f"🔍 Batch {i+1}/{total_batches}: scraping {batch[0]} ... and {len(batch)-1} more")

            batch_results = run_batch_sync(batch)
            all_results.extend(batch_results)

            # Free memory between batches
            del batch_results
            gc.collect()

        st.session_state['results'] = all_results
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
        f"All ({len(df)})", f"✅ Success ({success_count})", f"❌ Failed ({failed_count})"
    ])
    with tab_all:
        st.dataframe(df, use_container_width=True, height=400)
    with tab_success:
        st.dataframe(df[df['Status'].str.contains('SUCCESS', na=False)], use_container_width=True, height=400)
    with tab_failed:
        st.dataframe(df[df['Status'].str.contains('FAILED', na=False)], use_container_width=True, height=400)

    st.markdown("### 💾 Download Results")
    dl_col1, dl_col2, _ = st.columns([1, 1, 2])

    with dl_col1:
        st.download_button(
            label="📥 Download CSV",
            data=df.to_csv(index=False).encode('utf-8'),
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
