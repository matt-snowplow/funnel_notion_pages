# Notion Pages Downloader

Simple tool to download multiple Notion pages using a persistent browser profile and upload them to S3.

## What it does

Downloads Notion pages configured in `pages_config.yaml`:
- Launches Playwright browser with persistent profile
- **Extracts page content as Markdown (default)**
- Takes a full-page screenshot (PNG) for each page
- Exports each page as PDF  
- Uploads all formats to S3 bucket: `snowplow-qa-notion-pages`
- Maintains login sessions between runs
- Processes multiple pages in sequence

## Setup

1. **Install dependencies** (one time):
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   python3 -m playwright install chromium
   ```

2. **Configure AWS credentials** (one time):
   ```bash
   export AWS_ACCESS_KEY_ID="your_key"
   export AWS_SECRET_ACCESS_KEY="your_secret"
   ```

3. **Configure pages to download** (edit `pages_config.yaml`):
   ```yaml
   config:
     output_formats: ["markdown", "png", "pdf"]  # markdown is default
     s3_bucket: "snowplow-qa-notion-pages"
     s3_prefix: "notion-pages"
     
   pages:
     - url: "https://www.notion.so/your-workspace/page-id"
       name: "page_name"  # Used for filename generation
   ```

## Usage

**Download the page**:
```bash
python download_notion_page.py
```

On first run, you may need to manually log into Notion in the browser window that opens. The login session will be saved for future runs.

## Features

- **Efficient Batch Processing**: Opens browser once and reuses it for all pages (much faster than opening per page)
- **Markdown Export**: Extracts Notion page content as structured markdown (default format)
- **Multiple Formats**: PNG screenshots, PDF exports, and markdown content
- **Configurable Subpages**: Choose whether to include child pages and database records per page
- **Persistent Profile**: Login sessions and cookies are saved to `/tmp/chrome-playwright/`
- **Automatic Upload**: Files are automatically uploaded to S3 and cleaned up locally
- **Smart Organization**: Files organized in page-specific S3 directories with clean paths
- **Error Handling**: Robust handling of navigation timeouts and login requirements
- **Self-contained**: No external Chrome setup required

## Files

- `download_notion_page.py` - Main downloader script with persistent profile support
- `pages_config.yaml` - Configuration file listing pages to download
- `requirements.txt` - Python dependencies (playwright, boto3, pyyaml)
- `venv/` - Python virtual environment

## Output

Files are uploaded to: `s3://snowplow-qa-notion-pages/notion-pages/`

**Default formats (3 files per page):**
- `{page_name}_YYYYMMDD_HHMMSS.md` - Structured markdown content  
- `{page_name}_YYYYMMDD_HHMMSS.png` - Full-page screenshot
- `{page_name}_YYYYMMDD_HHMMSS.pdf` - PDF export

**Example:**
- `git_20250715_111338.md` - Markdown content of Git page
- `git_20250715_111338.png` - Screenshot of Git page  
- `git_20250715_111338.pdf` - PDF export of Git page

## Profile Management

- Browser profile is stored in `/tmp/chrome-playwright/`
- To reset login state: `rm -rf /tmp/chrome-playwright/`
- Each run reuses the saved profile, maintaining login sessions

## Adding More Pages

To add more pages to download, edit `pages_config.yaml`:

```yaml
pages:
  - url: "https://www.notion.so/keep-in-the-snow/Git-1c207af295a2807a9d1ecf578d1465ea"
    name: "git"
    subpages: false  # Only the main page
    
  - url: "https://www.notion.so/keep-in-the-snow/f7588c331ea846aabd0e25c5c4a35d0b"
    name: "postmortems"
    subpages: true   # Include child pages and database records
    
  - url: "https://www.notion.so/your-workspace/another-page-id"
    name: "new_page"
    subpages: false  # Default if not specified
```

**Configuration Options:**
- `name` - Used for filename generation, use descriptive, filesystem-safe names
- `subpages` - Set to `true` to include child pages and database records (default: `false`)

**When to use `subpages: true`:**
- Database pages: Exports individual records as separate files
- Parent pages: Includes all nested child pages
- Complete hierarchies: Gets the full structure, not just the top-level page

**S3 Organization:**
- With subpages: `s3://bucket/notion-pages/page_name/subfolder/file.csv`
- Without subpages: `s3://bucket/notion-pages/page_name/page_name_timestamp.md`

## Customizing Output Formats

You can customize which formats to generate by modifying the `output_formats` in your config:

**Markdown only:**
```yaml
config:
  output_formats: ["markdown"]
```

**Screenshots only:**
```yaml
config:
  output_formats: ["png"]
```

**All formats (default):**
```yaml
config:
  output_formats: ["markdown", "png", "pdf"]
```

**Per-page override:**
```yaml
pages:
  - url: "https://www.notion.so/keep-in-the-snow/Git-1c207af295a2807a9d1ecf578d1465ea"
    name: "git"
    output_formats: ["markdown"]  # Only markdown for this page
    
  - url: "https://www.notion.so/keep-in-the-snow/f7588c331ea846aabd0e25c5c4a35d0b"
    name: "postmortems"
    # Uses global config (markdown, png, pdf)
``` 