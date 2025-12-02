import os
import re
import time
import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from openpyxl import load_workbook
import xlrd
import ctypes
from bs4 import BeautifulSoup

# --------------------------
# CONFIG
# --------------------------
SCRAPER_API_KEY = ""  # <-- paste your ScraperAPI key here when you're ready
HEADLESS = True       # set False for debugging to see the browser
INVOICES_FOLDER = os.path.join(os.path.expanduser("~/Desktop"), "Invoices to Check")
RESULTS_ROOT_FOLDER = os.path.join(os.path.expanduser("~/Desktop"), "Invoice Checks Results")
WINDOW_SIZE = "1920,1080"

# --------------------------
# Selenium driver setup
# --------------------------
def setup_driver(headless=HEADLESS):
    options = webdriver.EdgeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={WINDOW_SIZE}")
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    return webdriver.Edge(options=options)

# --------------------------
# Helpers
# --------------------------
def parse_price_from_text(text):
    if not text:
        return None
    m = re.search(r'[\d,]+(?:\.\d{1,2})?', str(text).replace('£','').replace('$',''))
    if not m:
        return None
    val = m.group(0).replace(",", "")
    try:
        return float(val)
    except:
        return None

def safe_click_accept_cookies(driver):
    # generic cookie accept (Amazon/eBay)
    try:
        WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.ID, "sp-cc-accept"))).click()
        time.sleep(0.5)
    except:
        pass
    try:
        WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.ID, "gdpr-banner-accept"))).click()
        time.sleep(0.5)
    except:
        pass

# --------------------------
# VAT / EORI checks (screenshots saved)
# --------------------------
def check_vat(driver, vat_number, folder):
    if not vat_number:
        return "Not found"
    try:
        driver.get("https://www.tax.service.gov.uk/check-vat-number/enter-vat-details")
        time.sleep(2)
        for xp in ["//button[contains(text(),'Accept additional cookies')]", "//button[contains(text(),'Hide this message')]"]:
            try:
                WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, xp))).click()
            except:
                pass
        vat_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "target")))
        vat_input.clear()
        vat_input.send_keys(vat_number)
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Search')]"))).click()
        time.sleep(3)
        result = "Valid" if "valid" in driver.page_source.lower() else "Invalid"
        screenshot_path = os.path.join(folder, f"{vat_number}_vat.png")
        driver.save_screenshot(screenshot_path)
        print(f"💳 VAT check: {result} | Screenshot saved: {screenshot_path}")
        return result
    except Exception as e:
        print(f"❌ VAT check failed: {e}")
        return "Error"

def check_eori(driver, eori_number, folder):
    if not eori_number:
        return "Not found"
    try:
        driver.get("https://www.tax.service.gov.uk/check-eori-number")
        time.sleep(2)
        for xp in ["//button[contains(text(),'Accept additional cookies')]", "//button[contains(text(),'Hide this message')]"]:
            try:
                WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, xp))).click()
            except:
                pass
        eori_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "eori")))
        eori_input.clear()
        eori_input.send_keys(eori_number)
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Continue')]"))).click()
        time.sleep(2)
        result = "Valid" if "valid" in driver.page_source.lower() else "Invalid"
        screenshot_path = os.path.join(folder, f"{eori_number}_eori.png")
        driver.save_screenshot(screenshot_path)
        print(f"📦 EORI check: {result} | Screenshot saved: {screenshot_path}")
        return result
    except Exception as e:
        print(f"❌ EORI check failed: {e}")
        return "Error"

# --------------------------
# ScraperAPI - Amazon price (uses SCRAPER_API_KEY if set)
# --------------------------
def get_amazon_price(url):
    try:
        if not SCRAPER_API_KEY:
            # intentionally not using API key (user requested)
            print("🔍 [SCRAPERAPI] Key missing — skipping real API call (no credits used).")
            return "Currently Unavailable (No API Key)"
        payload = {
            "api_key": SCRAPER_API_KEY,
            "url": url,
            "render": "true",
            "country_code": "gb",
            "premium": "true"
        }
        print("🔍 [SCRAPERAPI] Requesting Amazon price...")
        resp = requests.get("http://api.scraperapi.com", params=payload, timeout=60)
        if resp.status_code != 200:
            print(f"❌ [SCRAPERAPI] HTTP {resp.status_code}")
            return "Currently Unavailable (API Failed)"
        soup = BeautifulSoup(resp.text, "html.parser")
        price_element = soup.select_one('span.a-price span.a-offscreen') or \
                        soup.select_one('#priceblock_ourprice') or \
                        soup.select_one('#corePriceDisplay_desktop_feature_div .a-price-whole') or \
                        soup.select_one('.a-price')
        raw = price_element.get_text(strip=True) if price_element else None
        if not raw:
            return "Currently Unavailable (Price Hidden)"
        p = parse_price_from_text(raw)
        return p if p is not None else "Currently Unavailable (Parse Error)"
    except Exception as e:
        print(f"❌ [SCRAPERAPI] Failed: {e}")
        return "Currently Unavailable (Fatal Error)"

# --------------------------
# Selenium price for eBay / Majexic
# --------------------------
def scrape_ebay_price(driver, url):
    try:
        driver.get(url)
        time.sleep(2)
        safe_click_accept_cookies(driver)
        selectors = [
            "span[itemprop='price']",
            "span.x-price-approx__price",
            "span.s-item__price",
            "span.ux-textspans",
            "span.ux-textspans.ux-textspans--BOLD",
            "#mainContent > div.vim.x-price-section.mar-t-20 > div > div > div.x-price-primary > span"
        ]
        raw_text = None
        for sel in selectors:
            try:
                # try both css and xpath
                if sel.startswith("/") or sel.startswith("("):
                    el = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.XPATH, sel)))
                else:
                    el = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, sel)))
                raw_text = el.get_attribute("textContent") or el.text
                if raw_text and parse_price_from_text(raw_text) is not None:
                    break
            except:
                continue
        if not raw_text:
            return "Currently Unavailable"
        p = parse_price_from_text(raw_text)
        return p if p is not None else "Currently Unavailable"
    except Exception as e:
        print(f"❌ eBay price scrape failed: {e}")
        return "Currently Unavailable"

# --------------------------
# Amazon - extract seller link from product page (if invoice lacks seller link)
# --------------------------
def get_amazon_seller_link_from_product(driver, product_url):
    """Opens product page and tries to find the seller profile/sp link."""
    try:
        driver.get(product_url)
        time.sleep(2)
        safe_click_accept_cookies(driver)

        # Common places for seller link
        candidate_selectors = [
            "a#sellerProfileTriggerId",            # direct seller profile link
            "a[href*='/sp?ie=UTF8&seller=']",     # seller short link
            "a[href*='/gp/aag/main?ie=UTF8&seller=']",
            "#bylineInfo a",                      # sometimes merchant link
            "#merchant-info a"
        ]

        for sel in candidate_selectors:
            try:
                if sel.startswith("a[") or sel.startswith("#"):
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                else:
                    # generic xpath check
                    el = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                href = el.get_attribute("href")
                if href and ("sp?ie=UTF8&seller=" in href or "/gp/aag/main" in href or "/seller" in href):
                    # normalize to https://www.amazon.co.uk/... if relative
                    return href
            except:
                continue

        # fallback: look for any anchor containing 'seller='
        try:
            anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'seller=')]")
            for a in anchors:
                href = a.get_attribute("href")
                if href:
                    return href
        except:
            pass

        return None
    except Exception as e:
        print(f"❌ Could not auto-detect Amazon seller link: {e}")
        return None

# --------------------------
# Seller screenshot capture (Amazon & eBay)
# --------------------------
def capture_amazon_seller(driver, seller_link, pair_folder, filename):
    """Robust capture of #page-section-detail-seller-info container (VAT included)."""
    try:
        if not seller_link:
            return False
        driver.get(seller_link)
        time.sleep(2)
        safe_click_accept_cookies(driver)

        # Scroll to middle (helps lazy-load)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.5);")
        time.sleep(1)

        # Try expand "See more" or similar inside the seller area
        try:
            for xp in ["//span[contains(text(),'See more')]", "//a[contains(text(),'see more')]", "//a[contains(@href,'seller-information')]"]:
                try:
                    btn = driver.find_element(By.XPATH, xp)
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.3)
                    if btn.is_displayed():
                        try:
                            btn.click()
                            time.sleep(0.8)
                        except:
                            pass
                except:
                    continue
        except:
            pass

        # Look for the seller info container using several fallbacks
        css_candidates = [
            "#page-section-detail-seller-info > div > div",
            "#page-section-detail-seller-info",
            "div#page-section-detail-seller-info",
            "div.section-seller-info"  # generic fallback
        ]

        el = None
        for sel in css_candidates:
            try:
                el = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                # ensure it has text and non-zero size
                if el and el.is_displayed():
                    size = el.size
                    if size.get("height", 0) > 12 and size.get("width", 0) > 100 and el.text.strip():
                        break
            except:
                el = None
                continue

        if not el:
            print("❌ Amazon seller info not found or not visible")
            return False

        # scroll element into view and give the page a little time
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.8)

        # final size check
        size = el.size
        if size.get("height", 0) < 12 or size.get("width", 0) < 100:
            print("❌ Amazon seller info element too small to screenshot")
            return False

        screenshot_path = os.path.join(pair_folder, f"{filename}_seller.png")
        el.screenshot(screenshot_path)
        print(f"🖼 Amazon seller screenshot saved: {screenshot_path}")
        return True
    except Exception as e:
        print(f"❌ Amazon seller screenshot failed: {e}")
        return False

def capture_ebay_seller(driver, seller_link, pair_folder, filename):
    try:
        if not seller_link:
            return False
        driver.get(seller_link)
        time.sleep(2)
        safe_click_accept_cookies(driver)

        selectors = [
            "div.x-business-seller-information",
            "#RightSummaryPanel",
            "div#LeftSummaryPanel"
        ]
        el = None
        for sel in selectors:
            try:
                el = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                if el and el.is_displayed() and el.text.strip():
                    break
            except:
                el = None
                continue

        if not el:
            print("❌ eBay seller info not found")
            return False

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.6)
        screenshot_path = os.path.join(pair_folder, f"{filename}_seller.png")
        el.screenshot(screenshot_path)
        print(f"🖼 eBay seller screenshot saved: {screenshot_path}")
        return True
    except Exception as e:
        print(f"❌ eBay seller screenshot failed: {e}")
        return False

# --------------------------
# Price comparison helper
# --------------------------
def compare_unit_price(invoice_unit_price, link_price):
    # link_price may be float or a string error message
    if isinstance(link_price, str):
        return "Price unavailable"
    try:
        invoice_unit_price = float(invoice_unit_price)
    except:
        return "Invoice price invalid"
    reduced = link_price * 0.3
    return f"OK ✅ (30% = £{reduced:.2f})" if invoice_unit_price >= reduced else f"Check ❌ (30% = £{reduced:.2f})"

# --------------------------
# Main invoice processing
# --------------------------
def process_invoice(file_path, driver):
    filename = os.path.splitext(os.path.basename(file_path))[0]
    print(f"\n--- Processing: {filename} ---")

    # Read invoice (xls/xlsx both supported)
    try:
        if file_path.lower().endswith(".xls"):
            book = xlrd.open_workbook(file_path)
            sheet = book.sheet_by_index(0)
            vat_eori_text = str(sheet.cell_value(4, 1)) if sheet.nrows > 4 else ""
            rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(8, sheet.nrows)]
        else:
            wb = load_workbook(file_path, data_only=True)
            ws = wb.active
            vat_eori_text = str(ws["B5"].value) if "B5" in ws and ws["B5"].value else (str(ws.cell(row=5, column=2).value) if ws.max_row >=5 else "")
            rows = [[ws.cell(row=r, column=c).value for c in range(1, ws.max_column+1)] for r in range(9, ws.max_row+1)]
    except Exception as e:
        print(f"❌ Failed to read invoice {file_path}: {e}")
        return

    # VAT/EORI detection
    vat_match = re.search(r"\bGB\d{9}\b", vat_eori_text)
    eori_match = re.search(r"\bGB\d{12}\b", vat_eori_text)
    vat_number = vat_match.group(0) if vat_match else ""
    eori_number = eori_match.group(0) if eori_match else ""

    # create folders
    invoice_folder = os.path.join(RESULTS_ROOT_FOLDER, filename)
    os.makedirs(invoice_folder, exist_ok=True)
    pair_folder_name = f"{vat_number}_{eori_number}" if (vat_number or eori_number) else "No_VAT_EORI"
    pair_folder = os.path.join(invoice_folder, pair_folder_name)
    os.makedirs(pair_folder, exist_ok=True)

    # do checks
    vat_result = check_vat(driver, vat_number, pair_folder) if vat_number else "Not found"
    eori_result = check_eori(driver, eori_number, pair_folder) if eori_number else "Not found"

    results = []

    # Process rows
    for row_idx, row in enumerate(rows, start=9):
        # Column F -> index 5 = Unit price
        unit_price = row[5] if len(row) > 5 else None

        # Column H -> index 7 = Sales link (if present)
        sales_link = str(row[7]).strip() if len(row) > 7 and row[7] else None

        # If there's a seller-only row (no unit price, but a link in column H), capture seller and continue
        if (not unit_price or str(unit_price).strip() == "") and sales_link:
            # treat as seller link if it points to amazon or ebay
            if "amazon" in sales_link.lower():
                # either capture direct seller link or, if this is a product link, try to find seller link and capture
                # If the sales_link is already a seller sp link, capture directly
                if "/sp?ie=UTF8&seller=" in sales_link or "/seller" in sales_link:
                    capture_amazon_seller(driver, sales_link, pair_folder, filename)
                else:
                    # try to auto-detect seller link from product page
                    seller = get_amazon_seller_link_from_product(driver, sales_link)
                    if seller:
                        capture_amazon_seller(driver, seller, pair_folder, filename)
                    else:
                        # fallback: attempt to screenshot page (merchant block)
                        try:
                            driver.get(sales_link)
                            time.sleep(1.2)
                            safe_click_accept_cookies(driver)
                            # merchant info
                            try:
                                el = WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#merchant-info")))
                                el.screenshot(os.path.join(pair_folder, f"{filename}_seller.png"))
                                print("🖼 Amazon merchant screenshot saved (fallback).")
                            except:
                                pass
                        except:
                            pass
                continue  # don't add seller-only rows to results

            elif "ebay" in sales_link.lower():
                # capture ebay seller (sales_link sometimes points to a product - capture seller panel from it)
                # If link looks like a product page, open product and try find seller panel link inside product page
                try:
                    # try to find seller profile link from product page
                    driver.get(sales_link)
                    time.sleep(1.5)
                    safe_click_accept_cookies(driver)
                    # product page may have seller link like a[href*="/usr/"] or a[href*="/user/"]
                    seller_href = None
                    try:
                        a = driver.find_element(By.CSS_SELECTOR, "a.mbg-id")
                        seller_href = a.get_attribute("href")
                    except:
                        # fallback find anchors with /usr/ or /user/
                        try:
                            anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'/usr/') or contains(@href,'/user/')]")
                            if anchors:
                                seller_href = anchors[0].get_attribute("href")
                        except:
                            seller_href = None
                    if seller_href:
                        capture_ebay_seller(driver, seller_href, pair_folder, filename)
                    else:
                        # fallback screenshot product page's seller block if present
                        try:
                            el = WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.x-business-seller-information")))
                            el.screenshot(os.path.join(pair_folder, f"{filename}_seller.png"))
                        except:
                            pass
                except Exception as e:
                    print(f"❌ eBay seller capture fallback failed: {e}")
                continue

        # Only process rows with numeric unit price
        if unit_price is None or not str(unit_price).replace('.', '', 1).isdigit():
            continue

        # Fetch price for sales link (if product link)
        link_price = "No link available"
        if sales_link:
            if "amazon" in sales_link.lower():
                link_price = get_amazon_price(sales_link)
            elif "ebay" in sales_link.lower() or "majexic" in sales_link.lower():
                link_price = scrape_ebay_price(driver, sales_link)
            else:
                link_price = "Unrecognized Link Type"

        # Append result row (seller_link is not written)
        results.append({
            "VAT Number": vat_number,
            "VAT Status": vat_result,
            "EORI Number": eori_number,
            "EORI Status": eori_result,
            "Invoice Unit Price": f"£{float(unit_price):.2f}",
            "Link Price": f"£{link_price:.2f}" if isinstance(link_price, (int, float)) else link_price,
            "Price Check Result": compare_unit_price(unit_price, link_price),
            "Sales Link": sales_link if sales_link else "No link available"
        })

    # Save results sheet
    if results:
        out = os.path.join(invoice_folder, f"{filename}_results.xlsx")
        pd.DataFrame(results).to_excel(out, index=False)
        print(f"✅ Results saved: {out}")
    else:
        print("[INFO] No valid rows to save for this invoice.")

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    os.makedirs(INVOICES_FOLDER, exist_ok=True)
    files = [os.path.join(INVOICES_FOLDER, f) for f in os.listdir(INVOICES_FOLDER)
             if f.lower().endswith((".xls", ".xlsx"))]
    if not files:
        ctypes.windll.user32.MessageBoxW(0, f"No Excel files found in '{INVOICES_FOLDER}'!", "Invoice Checker", 0)
    else:
        driver = setup_driver(headless=HEADLESS)
        try:
            for i, fp in enumerate(files):
                process_invoice(fp, driver)
                if i < len(files) - 1:
                    time.sleep(3)
        finally:
            driver.quit()
        ctypes.windll.user32.MessageBoxW(0, "All invoices processed successfully!", "Invoice Checker", 0)
