import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin

st.set_page_config(page_title="Dental Scraper", page_icon="🦷", layout="wide")

st.markdown("""
<style>
.stApp { background: #0d1117; color: #e6edf3; }
.main-header { text-align: center; padding: 2rem 0 1rem 0; }
.main-header h1 {
    font-size: 2.5rem; font-weight: 700;
    background: linear-gradient(135deg, #58a6ff, #79c0ff);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.stat-box { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 1.2rem; text-align: center; }
.stat-number { font-size: 2rem; font-weight: 700; color: #58a6ff; }
.stat-label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; }
.success-stat { color: #3fb950 !important; }
.fail-stat    { color: #f85149 !important; }
div[data-testid="stTextArea"] textarea {
    background: #161b22 !important; border: 1px solid #30363d !important;
    color: #e6edf3 !important; font-family: monospace !important;
}
div[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg,#238636,#2ea043) !important;
    color: white !important; border: none !important;
    font-weight: 600 !important; width: 100%; border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)

# ── HEADERS ──────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── URL CLEANER ───────────────────────────────────────────
def clean_url(url):
    url = url.strip()
    utm = re.compile(
        r'[?&](utm_source|utm_medium|utm_campaign|utm_content|utm_term'
        r'|y_source|_vsrefdom|sc_cid|gclid|fbclid)[^&]*', re.I)
    url = utm.sub('', url)
    return re.sub(r'[?&]+$', '', url).strip()

# ── NAME EXTRACTOR ────────────────────────────────────────
def extract_names(text):
    found = set()
    found.update(re.findall(r'Dr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}', text))
    found.update(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+,?\s+(?:DDS|DMD|RDH|NMD|DPM)', text))
    found.update(re.findall(
        r'(?:Doctor|Dentist|Hygienist|Orthodontist|Periodontist|Endodontist)'
        r'\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}', text))
    return [n.strip().rstrip(',') for n in found if len(n.strip()) > 4]

# ── FIND TEAM LINKS ───────────────────────────────────────
def find_team_links(base_url, soup):
    keywords = ['/team','/about','/doctors','/staff','/meet',
                '/providers','/our-team','/meet-the-team',
                '/about-us','/our-doctors','/our-staff']
    found = []
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        for kw in keywords:
            if kw in href:
                full = a['href'] if a['href'].startswith('http') else urljoin(base_url, a['href'])
                found.append(full)
                break
    return list(set(found))[:3]

# ── FETCH ONE PAGE ────────────────────────────────────────
def fetch_page(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True, verify=False)
        r.raise_for_status()
        return r.text
    except Exception:
        # try http fallback
        try:
            fallback = url.replace('https://', 'http://') if url.startswith('https') else url.replace('http://', 'https://')
            r = requests.get(fallback, headers=HEADERS, timeout=timeout,
                             allow_redirects=True, verify=False)
            r.raise_for_status()
            return r.text
        except Exception:
            return None

# ── SCRAPE ONE SITE ───────────────────────────────────────
def scrape_site(url):
    html = fetch_page(url)
    if not html:
        return {"url": url, "status": "❌ FAILED", "title": "", "names": "Could not load site"}

    soup = BeautifulSoup(html, 'lxml')
    title = soup.title.string.strip() if soup.title else "N/A"
    text  = soup.get_text(separator=' ', strip=True)
    names = extract_names(text)

    # try team/about pages
    team_links = find_team_links(url, soup)
    for tlink in team_links:
        thtml = fetch_page(tlink)
        if thtml:
            tsoup = BeautifulSoup(thtml, 'lxml')
            names += extract_names(tsoup.get_text(separator=' ', strip=True))

    names = list(set(names))
    names_str = " | ".join(names) if names else "No names found"
    return {"url": url, "status": "✅ SUCCESS", "title": title, "names": names_str}

# ── SCRAPE ALL (threaded) ─────────────────────────────────
def scrape_all(urls, progress_bar, status_box):
    results = []
    total   = len(urls)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scrape_site, url): url for url in urls}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            pct = int(done / total * 100)
            progress_bar.progress(pct, text=f"Scraped {done}/{total} sites...")
            status_box.info(f"{'✅' if 'SUCCESS' in result['status'] else '❌'} {result['url'][:60]}")

    # preserve original order
    url_order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r['url'], 9999))
    return results

# ── UI ────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🦷 Dental Website Scraper</h1>
    <p style="color:#8b949e">Extract doctor & team member names from dental clinic websites</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown("### 📋 Paste Your URLs")
    st.caption("One URL per line — up to 200 at once")
    url_input = st.text_area(
        label="urls", label_visibility="collapsed", height=280,
        placeholder="https://castordds.com\nhttps://waltonfamilydentistry.com\n..."
    )

    urls = []
    if url_input.strip():
        raw  = [l.strip() for l in url_input.strip().splitlines() if l.strip()]
        urls = [clean_url(u) for u in raw if u.startswith('http')]

    if urls:
        st.markdown(f'<div style="display:inline-block;background:#1f3a5f;color:#58a6ff;'
                    f'border:1px solid #1f6feb;border-radius:20px;padding:0.2rem 0.9rem;'
                    f'font-size:0.85rem;margin-bottom:1rem">📊 {len(urls)} URLs ready</div>',
                    unsafe_allow_html=True)

    run_btn = st.button(
        "🚀 Start Scraping" if urls else "🚀 Start Scraping (paste URLs above)",
        type="primary", disabled=len(urls) == 0
    )

with right:
    st.markdown("### ℹ️ How It Works")
    st.markdown("""
- Paste up to **200 dental website URLs**
- Clicks Start — scrapes all sites simultaneously
- Finds **team / about / doctors** pages automatically
- Extracts **Dr. Names**, **DDS/DMD/RDH** credentials
- Download as **Excel** (3 sheets) or **CSV**
""")
    st.markdown("### ⏱️ Speed")
    if urls:
        mins = max(1, round(len(urls) * 0.15 / 60, 1))
        st.info(f"~{mins} min for {len(urls)} URLs")
    else:
        st.info("~30 seconds per 50 URLs")

# ── RUN SCRAPER ───────────────────────────────────────────
if run_btn and urls:
    st.markdown("---")
    st.markdown("### ⚡ Live Progress")
    status_box   = st.empty()
    progress_bar = st.progress(0, text="Starting...")

    status_box.info(f"🚀 Scraping {len(urls)} sites...")

    import warnings
    warnings.filterwarnings('ignore')   # suppress SSL warnings

    raw_results = scrape_all(urls, progress_bar, status_box)
    st.session_state['results'] = [
        {"Website URL": r['url'], "Status": r['status'],
         "Page Title": r['title'], "Doctors & Team Members": r['names']}
        for r in raw_results
    ]
    st.session_state['scraped'] = True
    progress_bar.progress(100, text="✅ Done!")
    status_box.success("🎉 Scraping complete!")

# ── RESULTS ───────────────────────────────────────────────
if st.session_state.get('scraped') and 'results' in st.session_state:
    df = pd.DataFrame(st.session_state['results'])

    success = len(df[df['Status'].str.contains('SUCCESS', na=False)])
    failed  = len(df[df['Status'].str.contains('FAILED',  na=False)])
    names_f = len(df[~df['Doctors & Team Members'].isin(['No names found','Could not load site'])])

    st.markdown("---")
    st.markdown("### 📊 Results")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="stat-box"><div class="stat-number">{len(df)}</div><div class="stat-label">Total</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="stat-box"><div class="stat-number success-stat">{success}</div><div class="stat-label">Success</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="stat-box"><div class="stat-number fail-stat">{failed}</div><div class="stat-label">Failed</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="stat-box"><div class="stat-number">{names_f}</div><div class="stat-label">Names Found</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    t1, t2, t3 = st.tabs([f"All ({len(df)})", f"✅ Success ({success})", f"❌ Failed ({failed})"])
    with t1: st.dataframe(df, use_container_width=True, height=400)
    with t2: st.dataframe(df[df['Status'].str.contains('SUCCESS', na=False)], use_container_width=True, height=400)
    with t3: st.dataframe(df[df['Status'].str.contains('FAILED',  na=False)], use_container_width=True, height=400)

    st.markdown("### 💾 Download Results")
    dl1, dl2, _ = st.columns([1, 1, 2])

    with dl1:
        st.download_button("📥 Download CSV",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name="dental_results.csv", mime="text/csv")

    with dl2:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name='All Results')
            df[df['Status'].str.contains('SUCCESS', na=False)].to_excel(w, index=False, sheet_name='Success')
            df[df['Status'].str.contains('FAILED',  na=False)].to_excel(w, index=False, sheet_name='Failed')
        st.download_button("📥 Download Excel",
            data=buf.getvalue(),
            file_name="dental_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
