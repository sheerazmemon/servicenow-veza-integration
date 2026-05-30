# ServiceNow + Veza Integration

A working reference implementation connecting ServiceNow and Veza — built as a hands-on lab and Brown Bag demonstration. Includes a Python OAA connector that pushes ServiceNow identity data into the Veza Access Graph, four automated Business Rules that enrich ServiceNow records with live Veza identity intelligence, and a Scripted REST API webhook that lets Veza autonomously create incidents in ServiceNow when risk thresholds are breached.

---

## What this does

| Component | What it does |
|---|---|
| OAA Connector | Pulls users, roles, and tables from ServiceNow and pushes them into Veza as a Custom Provider |
| Flow 1 — Incident Enrichment | Enriches every new incident with Veza identity coverage status |
| Flow 2 — Access Request Pre-Validation | Pre-validates catalog requests against Veza before approval routing |
| Flow 3 — Offboarding Verification | Flags offboarding risk when a problem reporter is not found in Veza |
| Flow 4 — Separation of Duties | Blocks access requests that would create SoD violations |
| Alert Receiver | Inbound webhook that auto-creates P1 incidents when Veza fires an Event Subscription |

---

## Prerequisites

- Python 3.8+
- A Veza instance (demo or production) with an API key
- A ServiceNow instance (Personal Developer Instance works)
- pip install oaaclient python-dotenv requests

---

## Setup

### 1. Clone the repo

    git clone https://github.com/YOUR_GITHUB_USERNAME/servicenow-veza-integration.git
    cd servicenow-veza-integration

### 2. Configure credentials

    cp oaa-connector/.env.example oaa-connector/.env

Edit .env with your real values:

    VEZA_URL=https://your-instance.vezacloud.com
    VEZA_API_KEY=your-veza-api-key
    SN_INSTANCE=https://devXXXXX.service-now.com
    SN_USER=your-sn-username
    SN_PASSWORD=your-sn-password

Get your Veza API key: Administration > API Keys > Add New API Key

### 3. Run the OAA connector

    cd oaa-connector

    # Dry run first
    python veza_servicenow_connector.py --dry-run

    # Full push
    python veza_servicenow_connector.py

After a successful run, ServiceNow appears under Integrations > Custom in your Veza instance. Search any ServiceNow username in Access Search to see their roles and permissions in the graph.

---

## Business Rules

Each script in business-rules/ is a ServiceNow Business Rule. To deploy:

1. In ServiceNow: System Definition > Business Rules > New
2. Set the table, timing, and trigger as documented in the comment header of each file
3. Replace YOUR_VEZA_URL and YOUR_VEZA_API_KEY with your real values
4. Save and test by creating a record on the target table

---

## Webhook Setup (Alert Receiver)

The script in scripted-rest-api/veza_alert_receiver.js creates an inbound REST endpoint in ServiceNow that Veza calls when an Event Subscription fires.

1. In ServiceNow: System Web Services > Scripted REST APIs > New — Name: veza_alert_receiver
2. Add a Resource: path /alert, method POST, paste the script
3. Copy the generated endpoint URL
4. In Veza: Integrations > Event Subscriptions > New — paste the URL as the webhook target

When Veza detects a risk threshold breach it calls the endpoint directly, and a P1 incident appears in ServiceNow with no human involved.

---

## Repository Structure

    servicenow-veza-integration/
    ├── oaa-connector/
    │   ├── veza_servicenow_connector.py
    │   ├── veza_servicenow_connector_sdk.py
    │   ├── requirements.txt
    │   └── .env.example
    ├── business-rules/
    │   ├── flow1_incident_enrichment.js
    │   ├── flow2_access_request_validation.js
    │   ├── flow3_offboarding_verification.js
    │   └── flow4_separation_of_duties.js
    ├── scripted-rest-api/
    │   └── veza_alert_receiver.js
    ├── docs/
    └── screenshots/

---

## Author

Built by Sheeraz Memon as a hands-on Veza SME lab and ServiceNow Brown Bag demonstration.
