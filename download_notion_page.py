#!/usr/bin/env python3
"""
Simple Notion Page Downloader
Downloads a specific Notion page using a persistent browser profile and uploads to S3.
Profile is saved to /tmp/chrome-playwright for session persistence.
"""

import asyncio
import sys
import os
import urllib.request
import json
import yaml
import zipfile
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import time

# Add the parent directory to import S3Storage
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

try:
    from funnel_youtube_transcripts.s3_storage import S3Storage
except ImportError as e:
    print(f"❌ Could not import S3Storage: {e}")
    print("💡 Make sure you're running from the project root directory")
    sys.exit(1)

async def extract_files_via_export(page, page_name, include_subpages=False, timeout_ms=30000):
    """
    Extract all files using Notion's built-in export feature.
    Handles both CSV files (for database pages) and MD files (for normal pages).
    
    Args:
        page: Playwright page object
        page_name: Name of the page for directory organization
        include_subpages: Whether to include subpages in the export
        timeout_ms: Timeout for operations in milliseconds
        
    Returns:
        tuple: (list_of_file_paths, success_flag)
    """
    try:
        print("🔄 Attempting to extract files via Notion export...")
        
        # Step 1: Click the Actions button (three dots)
        print("  → Clicking Actions button...")
        actions_selector = 'div[role="button"][aria-label="Actions"].notion-topbar-more-button'
        
        await page.wait_for_selector(actions_selector, timeout=timeout_ms)
        await page.click(actions_selector)
        print("  ✅ Actions button clicked")
        
        # Step 2: Wait for and click Export option
        print("  → Waiting for Export option...")
        export_selector = '//div[@role="option" and .//div[text()="Export"]]'
        
        await page.wait_for_selector(export_selector, timeout=timeout_ms)
        await page.click(export_selector)
        print("  ✅ Export option clicked")
        
        # Step 3: Wait for export dialog to appear
        print("  → Waiting for export dialog...")
        dialog_selector = 'div[role="dialog"][aria-label="Export"].notion-dialog'
        
        await page.wait_for_selector(dialog_selector, timeout=timeout_ms)
        print("  ✅ Export dialog appeared")
        
        # Step 4: Configure "Include subpages" based on YAML setting
        print(f"  → Setting 'Include subpages' to: {include_subpages}")
        try:
            # Find the "Include subpages" checkbox
            subpages_checkbox = page.locator('div:has-text("Include subpages") + div input[type="checkbox"][role="switch"]').first
            
            # Check current state
            is_currently_checked = await subpages_checkbox.is_checked()
            
            # Set to desired state if different
            if is_currently_checked != include_subpages:
                if include_subpages:
                    print("  → Enabling 'Include subpages'...")
                else:
                    print("  → Disabling 'Include subpages'...")
                    
                await subpages_checkbox.click()
                await page.wait_for_timeout(500)  # Give it a moment to update
                print(f"  ✅ 'Include subpages' set to: {include_subpages}")
            else:
                print(f"  ✅ 'Include subpages' already set to: {include_subpages}")
                
        except Exception as toggle_error:
            print(f"  ⚠️  Could not configure 'Include subpages': {toggle_error}")
            # Continue anyway - this is not critical
        
        # Step 5: Click the final Export button (blue button)
        print("  → Clicking final Export button...")
        
        # Look for the blue export button by its distinctive styling
        # Option 1: XPath approach
        export_button_selector = 'xpath=//div[@role="button" and text()="Export"]'
        
        # Option 2: If XPath fails, use CSS with additional specificity
        # export_button_selector = 'div[role="button"]:has-text("Export"):not(:has-text("Cancel"))'
        
        # Set up download handler before clicking
        download_info = None
        
        async def handle_download(download):
            nonlocal download_info
            download_info = download
            print(f"  📥 Download started: {download.suggested_filename}")
        
        page.on("download", handle_download)
        
        # Click the export button
        await page.click(export_button_selector)
        print("  ✅ Export button clicked")
        
        # Step 6: Wait for download progress dialog and completion
        print("  → Waiting for download progress dialog...")
        
        try:
            # Wait for the progress dialog to appear
            progress_dialog_selector = 'div[role="dialog"].notion-dialog:has(span[role="progressbar"])'
            await page.wait_for_selector(progress_dialog_selector, timeout=10000)
            print("  ✅ Download progress dialog appeared")
            
            # Get the progress text if available
            try:
                progress_text = await page.locator('div[role="dialog"]:has(span[role="progressbar"]) p').first.text_content()
                if progress_text:
                    print(f"  📊 Progress: {progress_text}")
            except:
                pass
            
            # Wait for the progress dialog to disappear (indicates download is complete)
            print("  → Waiting for download to complete...")
            await page.wait_for_selector(progress_dialog_selector, state='detached', timeout=60000)  # Up to 1 minute for large exports
            print("  ✅ Download progress dialog disappeared - download should be complete")
            
        except Exception as progress_error:
            print(f"  ⚠️  Could not track progress dialog: {progress_error}")
            print("  → Falling back to fixed wait...")
            await page.wait_for_timeout(5000)  # Shorter fallback wait
        
        # Wait for download to be available
        print("  → Waiting for download to be available...")
        download_timeout = 10  # seconds
        download_start_time = time.time()
        
        while not download_info and (time.time() - download_start_time) < download_timeout:
            await page.wait_for_timeout(500)  # Check every 500ms
        
        if download_info:
            print(f"  ✅ Download detected: {download_info.suggested_filename}")
            # Wait for download to complete and save it
            download_path = f"/tmp/notion_export_{int(time.time())}.zip"
            await download_info.save_as(download_path)
            print(f"  ✅ Download completed: {download_path}")
            
            # Step 7: Extract all files from ZIP
            print("  → Extracting all files from ZIP...")
            
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find all files in the extracted content
                extracted_files = []
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Get relative path from temp_dir
                        rel_path = os.path.relpath(file_path, temp_dir)
                        extracted_files.append((file_path, rel_path))
                
                if extracted_files:
                    print(f"  ✅ Found {len(extracted_files)} files in export:")
                    for _, rel_path in extracted_files:
                        print(f"    📄 {rel_path}")
                    
                    # Create page-specific directory
                    page_dir = f"/tmp/{page_name}_export_{int(time.time())}"
                    os.makedirs(page_dir, exist_ok=True)
                    
                    # Copy files to page directory maintaining structure
                    final_files = []
                    for src_path, rel_path in extracted_files:
                        # Create destination path in page directory
                        dest_path = os.path.join(page_dir, rel_path)
                        dest_dir = os.path.dirname(dest_path)
                        
                        # Create subdirectories if needed
                        if dest_dir:
                            os.makedirs(dest_dir, exist_ok=True)
                        
                        # Copy file
                        import shutil
                        shutil.copy2(src_path, dest_path)
                        final_files.append(dest_path)
                    
                    print(f"  ✅ Prepared {len(final_files)} files for upload")
                    
                    # Clean up download file
                    # os.remove(download_path)
                    
                    return final_files, True
                else:
                    print("  ❌ No files found in ZIP")
                    # os.remove(download_path)
                    return [], False
        else:
            print("  ❌ No download detected within timeout period")
            return [], False
            
    except Exception as e:
        print(f"  ❌ Export failed: {str(e)}")
        return [], False


async def download_page_content(page, page_config, global_config):
    """Download content from a specific Notion page using an existing browser page."""
    
    # Configuration from YAML
    NOTION_URL = page_config['url']
    PAGE_NAME = page_config['name']
    INCLUDE_SUBPAGES = page_config.get('subpages', False)  # Default to False if not specified
    S3_BUCKET = global_config.get('s3_bucket', 'snowplow-qa-notion-pages')
    S3_PREFIX = global_config.get('s3_prefix', 'notion-pages')
    OUTPUT_FORMATS = page_config.get('output_formats', global_config.get('output_formats', ['markdown', 'png', 'pdf']))
    S3_REGION = "eu-central-1"  # Same as other QA buckets
    
    print(f"🎯 Target page: {NOTION_URL}")
    print(f"📄 Page name: {PAGE_NAME}")
    print(f"📦 S3 bucket: {S3_BUCKET}")
    print(f"📤 Output formats: {', '.join(OUTPUT_FORMATS)}")
    print(f"📁 Include subpages: {INCLUDE_SUBPAGES}")
    
    # Initialize S3 storage (only once)
    if not hasattr(download_page_content, 's3_storage'):
        try:
            download_page_content.s3_storage = S3Storage(S3_BUCKET, S3_REGION, "notion-pages")
            print("✅ S3 storage initialized")
        except Exception as e:
            print(f"❌ S3 initialization failed: {e}")
            print("💡 Make sure AWS credentials are configured")
            return False
    
    s3_storage = download_page_content.s3_storage

    try:
        # Navigate to the Notion page
        print(f"📄 Navigating to Notion page...")
        try:
            await page.goto(NOTION_URL, timeout=10000)
            print("✅ Page loaded successfully")
        except Exception as e:
            print(f"⚠️  Navigation timeout: {e}")
            print("🔍 Checking what page we're on...")
            current_url = page.url
            title = await page.title()
            print(f"   Current URL: {current_url}")
            print(f"   Current title: {title}")
            
            # Check if we're on a login page
            if 'login' in current_url.lower() or 'sign' in title.lower():
                print("🔐 Looks like we need to log in...")
                print("💡 Please log in manually in the browser window")
                print("⏳ Waiting 30 seconds for manual login...")
                await asyncio.sleep(30)
                
                # Try to navigate again after potential login
                print("🔄 Trying to navigate to the page again...")
                await page.goto(NOTION_URL, timeout=10000)
        
        # Wait for page to load
        print("⏳ Waiting for page to load completely...")
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
            print("✅ Page finished loading")
        except:
            print("⚠️  Network idle timeout, but continuing...")
        
        # Get the current URL and title after potential redirects
        current_url = page.url
        title = await page.title()
        print(f"🔍 Current URL: {current_url}")
        print(f"📄 Page title: {title}")
        
        # Generate timestamp for filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"{PAGE_NAME}_{timestamp}"
        
        # Generate files based on configured formats
        files_to_upload = []
        
        # Extract all files from Notion export (CSV for databases, MD for pages)
        if 'markdown' in OUTPUT_FORMATS:
            print(f"📝 Extracting files for: {PAGE_NAME}")
            try:
                # Extract all files from Notion export
                extracted_files, success = await extract_files_via_export(page, PAGE_NAME, INCLUDE_SUBPAGES)
                
                if success and extracted_files:
                    print(f"✅ Successfully extracted {len(extracted_files)} files")
                    
                    # Add all extracted files for upload with appropriate content types
                    for file_path in extracted_files:
                        # Determine content type based on file extension
                        file_ext = os.path.splitext(file_path)[1].lower()
                        if file_ext == '.md':
                            content_type = "text/markdown"
                        elif file_ext == '.csv':
                            content_type = "text/csv"
                        elif file_ext == '.json':
                            content_type = "application/json"
                        elif file_ext == '.txt':
                            content_type = "text/plain"
                        else:
                            content_type = "application/octet-stream"
                        
                        files_to_upload.append((file_path, content_type))
                        print(f"  📄 Added {os.path.basename(file_path)} ({content_type})")
                else:
                    print("❌ File extraction failed")
                    return False
            except Exception as e:
                print(f"❌ File extraction failed: {e}")
                return False
        
        # Take screenshot (keeping existing functionality)
        if 'png' in OUTPUT_FORMATS:
            print(f"📸 Taking screenshot for: {PAGE_NAME}")
            try:
                png_path = f"{filename_base}.png"
                await page.screenshot(path=png_path, full_page=True)
                print(f"✅ Screenshot saved: {png_path}")
                files_to_upload.append((png_path, "image/png"))
            except Exception as e:
                print(f"❌ Screenshot failed: {e}")
                return False
        
        # Generate PDF (keeping existing functionality)
        if 'pdf' in OUTPUT_FORMATS:
            print(f"📄 Generating PDF for: {PAGE_NAME}")
            try:
                pdf_path = f"{filename_base}.pdf"
                await page.pdf(path=pdf_path, format='A4', print_background=True)
                print(f"✅ PDF saved: {pdf_path}")
                files_to_upload.append((pdf_path, "application/pdf"))
            except Exception as e:
                print(f"❌ PDF generation failed: {e}")
                return False
        
        # Upload files to S3
        if files_to_upload:
            print(f"📤 Uploading {len(files_to_upload)} files to S3...")
            
            # Create page-specific directory in S3
            s3_page_prefix = f"{S3_PREFIX}/{PAGE_NAME}/"
            
            upload_success = True
            uploaded_files = []
            
            for file_path, content_type in files_to_upload:
                try:
                    # Get the relative path within the extracted files
                    filename = os.path.basename(file_path)
                    
                    # For extracted files, maintain directory structure if it exists
                    if PAGE_NAME in file_path and '_export_' in file_path:
                        # This is an extracted file, maintain its relative structure
                        page_dir_pattern = f"{PAGE_NAME}_export_"
                        page_dir_start = file_path.find(page_dir_pattern)
                        if page_dir_start != -1:
                            # Find the part after the page directory
                            after_page_dir = file_path[page_dir_start:].split('/', 1)
                            if len(after_page_dir) > 1:
                                relative_path = after_page_dir[1]
                                
                                # Skip "Private & Shared" folder level if it exists
                                relative_path = relative_path.replace('Private & Shared/', '').replace('Private & Shared\\', '')
                                
                                # If we still have a path after removing Private & Shared, use it
                                if relative_path:
                                    s3_key = f"{s3_page_prefix}{relative_path}"
                                else:
                                    s3_key = f"{s3_page_prefix}{filename}"
                            else:
                                s3_key = f"{s3_page_prefix}{filename}"
                        else:
                            s3_key = f"{s3_page_prefix}{filename}"
                    else:
                        # This is a screenshot or PDF, put directly in page directory
                        s3_key = f"{s3_page_prefix}{filename}"
                    
                    print(f"  📤 Uploading {filename} to s3://{S3_BUCKET}/{s3_key}")
                    
                    try:
                        # Read file content
                        with open(file_path, 'rb') as f:
                            file_content = f.read()
                        
                        # Upload using S3 client directly
                        s3_storage.s3_client.put_object(
                            Bucket=S3_BUCKET,
                            Key=s3_key,
                            Body=file_content,
                            ContentType=content_type,
                            Metadata={
                                'source_url': NOTION_URL,
                                'page_name': PAGE_NAME,
                                'downloaded_at': datetime.now().isoformat()
                            }
                        )
                        
                        uploaded_files.append(s3_key)
                        print(f"  ✅ Uploaded: {filename}")
                        
                        # Clean up local file after successful upload
                        try:
                            os.remove(file_path)
                        except Exception as cleanup_error:
                            print(f"  ⚠️  Could not clean up {file_path}: {cleanup_error}")
                            
                    except Exception as upload_error:
                        print(f"  ❌ Failed to upload {filename}: {upload_error}")
                        upload_success = False
                        
                except Exception as e:
                    print(f"  ❌ Upload error for {filename}: {e}")
                    upload_success = False
            
            if upload_success:
                print(f"🎉 Successfully uploaded {len(uploaded_files)} files to S3!")
                print(f"📂 Files uploaded to: s3://{S3_BUCKET}/{s3_page_prefix}")
                for s3_key in uploaded_files:
                    print(f"   📄 {s3_key}")
                
                # Upload metadata
                metadata = {
                    'page_name': PAGE_NAME,
                    'source_url': NOTION_URL,
                    'download_timestamp': timestamp,
                    'output_formats': OUTPUT_FORMATS,
                    'uploaded_files': uploaded_files,
                    's3_bucket': S3_BUCKET,
                    's3_prefix': s3_page_prefix
                }
                
                metadata_key = f"{s3_page_prefix}metadata.json"
                metadata_json = json.dumps(metadata, indent=2)
                
                with open(f"/tmp/{PAGE_NAME}_metadata.json", 'w') as f:
                    f.write(metadata_json)
                
                try:
                    # Upload metadata using S3 client directly
                    s3_storage.s3_client.put_object(
                        Bucket=S3_BUCKET,
                        Key=metadata_key,
                        Body=metadata_json.encode('utf-8'),
                        ContentType="application/json",
                        Metadata={
                            'page_name': PAGE_NAME,
                            'source_url': NOTION_URL,
                            'uploaded_at': datetime.now().isoformat()
                        }
                    )
                    print(f"✅ Metadata uploaded: {metadata_key}")
                    os.remove(f"/tmp/{PAGE_NAME}_metadata.json")
                except Exception as metadata_error:
                    print(f"⚠️  Failed to upload metadata: {metadata_error}")
                    # Don't fail the whole process for metadata upload failure
                
                return True
            else:
                print("❌ Some uploads failed!")
                return False
        else:
            print("❌ No files to upload!")
            return False
            
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


async def download_notion_page(page_config, global_config):
    """Legacy function - opens browser for single page download."""
    # This is now a wrapper that creates a browser just for one page
    # Kept for backward compatibility but not recommended for multi-page usage
    
    from playwright.async_api import async_playwright
    
    print("⚠️  Using legacy single-page browser mode - consider using the batch mode for better performance")
    
    try:
        async with async_playwright() as p:
            # Launch Playwright with persistent context (profile)
            print("🚀 Launching Playwright browser with persistent profile...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir="/tmp/chrome-playwright/",
                headless=False,  # Keep visible for manual login if needed
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )
            
            # Create a new page
            page = await context.new_page()
            
            # Download the page content
            result = await download_page_content(page, page_config, global_config)
            
            # Close the browser
            await context.close()
            return result
            
    except Exception as e:
        print(f"❌ Browser error: {e}")
        return False

async def main():
    """Main function - efficiently processes all pages with a single browser instance."""
    
    print("🚀 Notion Pages Downloader (Batch Mode)")
    print("=" * 40)
    print("💡 Using efficient single-browser mode for all pages")
    print()
    
    # Load configuration
    try:
        with open('pages_config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        global_config = config.get('config', {})
        pages = config.get('pages', [])
        
        if not pages:
            print("❌ No pages configured in pages_config.yaml")
            sys.exit(1)
            
    except FileNotFoundError:
        print("❌ Configuration file 'pages_config.yaml' not found!")
        print("💡 Create one based on the example in README.md")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        sys.exit(1)
    
    print(f"📋 Found {len(pages)} page(s) to download")
    print()
    
    # Check dependencies
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Missing playwright! Install with:")
        print("pip3 install playwright")
        print("python3 -m playwright install chromium")
        sys.exit(1)
    
    # Open browser once for all pages
    print("🚀 Launching Playwright browser with persistent profile...")
    
    try:
        async with async_playwright() as p:
            # Launch Playwright with persistent context (profile)
            context = await p.chromium.launch_persistent_context(
                user_data_dir='/tmp/chrome-playwright',  # Persistent profile
                headless=False,  # Show browser so you can see it working
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            
            # Create a new page
            page = await context.new_page()
            print("📄 Browser ready!")
            
            # Process each page with the same browser
            successful_downloads = 0
            failed_downloads = 0
            
            for i, page_config in enumerate(pages, 1):
                print(f"\n{'='*50}")
                print(f"📄 Processing page {i}/{len(pages)}: {page_config.get('name', 'unknown')}")
                print(f"{'='*50}")
                
                try:
                    success = await download_page_content(page, page_config, global_config)
                    if success:
                        successful_downloads += 1
                        print(f"✅ Page {i} completed successfully!")
                    else:
                        failed_downloads += 1
                        print(f"❌ Page {i} failed!")
                except Exception as e:
                    failed_downloads += 1
                    print(f"❌ Page {i} failed with error: {e}")
                
                # Small delay between pages to be respectful
                if i < len(pages):  # Don't wait after the last page
                    print("⏳ Brief pause before next page...")
                    await asyncio.sleep(2)
            
            # Close browser
            await context.close()
            print("🔒 Browser closed")
            
    except Exception as e:
        print(f"❌ Browser error: {e}")
        sys.exit(1)
    
    # Final summary
    print(f"\n{'='*50}")
    print("📊 Download Summary")
    print(f"{'='*50}")
    print(f"✅ Successful: {successful_downloads}")
    print(f"❌ Failed: {failed_downloads}")
    print(f"📄 Total: {len(pages)}")
    
    if failed_downloads == 0:
        print("\n🎉 All pages downloaded successfully!")
    else:
        print(f"\n⚠️  {failed_downloads} page(s) failed to download")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 