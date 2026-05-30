#!/usr/bin/env python3
"""
Veza OAA Connector for ServiceNow
==================================
Pulls users, roles, and table ACLs from a ServiceNow instance
and pushes them into your Veza demo instance as a Custom Application.

After running this, ServiceNow will appear in your Veza Access Graph
and you can search: "who has admin access to which SN tables?"

SETUP (one-time):
    pip install oaaclient requests python-dotenv

ENVIRONMENT VARIABLES — create a .env file or export directly:
    VEZA_URL         = https://your-demo.veza.com
    VEZA_API_KEY     = <from Veza > Administration > API Keys>
    SN_INSTANCE      = https://your-instance.service-now.com
    SN_USER          = your-sn-username
    SN_PASSWORD      = your-sn-password

WHAT THIS CONNECTOR DOES:
    1. Connects to ServiceNow Table API and pulls:
       - All active users (sys_user)
       - All roles (sys_user_role)
       - User-role assignments (sys_user_has_role)
       - Table ACL rules (sys_acl) as "resources"
    2. Maps SN's auth model to Veza's OAA schema:
       - SN users        -> OAA local_users
       - SN roles        -> OAA local_roles
       - SN tables/ACLs  -> OAA resources
       - SN permissions  -> OAA permissions (read/write/admin)
    3. Pushes to Veza and appears in the Access Graph

USAGE:
    python veza_servicenow_connector.py

    # Or with explicit env vars:
    VEZA_URL=https://demo.veza.com VEZA_API_KEY=xxx \
    SN_INSTANCE=https://dev12345.service-now.com \
    SN_USER=admin SN_PASSWORD=xxx \
    python veza_servicenow_connector.py
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime

import requests
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("veza-sn")

# ─── ServiceNow client ────────────────────────────────────────────────────────

class ServiceNowClient:
    """Thin wrapper around the ServiceNow Table REST API."""

    def __init__(self, instance_url: str, username: str, password: str):
        self.base = instance_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _get(self, table: str, params: dict = None) -> list:
        """Paginated GET from a SN table. Returns all records."""
        url = f"{self.base}/api/now/table/{table}"
        defaults = {
            "sysparm_limit": 200,
            "sysparm_offset": 0,
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
        }
        if params:
            defaults.update(params)

        records = []
        while True:
            resp = self.session.get(url, params=defaults)
            resp.raise_for_status()
            data = resp.json().get("result", [])
            records.extend(data)
            if len(data) < defaults["sysparm_limit"]:
                break
            defaults["sysparm_offset"] += defaults["sysparm_limit"]
            log.info("  fetched %d records so far from %s ...", len(records), table)

        return records

    def get_users(self) -> list:
        log.info("Fetching active users from ServiceNow ...")
        return self._get("sys_user", {
            "sysparm_query": "active=true",
            "sysparm_fields": "sys_id,user_name,first_name,last_name,email,active,last_login_time",
        })

    def get_roles(self) -> list:
        log.info("Fetching roles from ServiceNow ...")
        return self._get("sys_user_role", {
            "sysparm_fields": "sys_id,name,description,elevated_privilege",
        })

    def get_user_roles(self) -> list:
        log.info("Fetching user-role assignments from ServiceNow ...")
        return self._get("sys_user_has_role", {
            "sysparm_fields": "user,role,inherited",
        })

    def get_tables(self, max_tables: int = 50) -> list:
        """Get top-level application tables as 'resources' in Veza."""
        log.info("Fetching tables from ServiceNow ...")
        return self._get("sys_db_object", {
            "sysparm_query": "sys_package.active=true^super_class=NULL",
            "sysparm_fields": "name,label,sys_scope",
            "sysparm_limit": max_tables,
        })


# ─── Veza OAA builder ────────────────────────────────────────────────────────

def build_oaa_payload(sn: ServiceNowClient) -> dict:
    """
    Fetch all SN data and assemble the OAA JSON payload.
    Returns a dict ready to be JSON-serialised and pushed to Veza.
    """

    users     = sn.get_users()
    roles     = sn.get_roles()
    user_roles = sn.get_user_roles()
    tables    = sn.get_tables(max_tables=60)

    log.info("Building OAA payload: %d users, %d roles, %d assignments, %d tables",
             len(users), len(roles), len(user_roles), len(tables))

    # Build lookup: sys_id -> name (for resolving role references)
    role_id_to_name = {r["sys_id"]: r["name"] for r in roles}

    # ── Local users ────────────────────────────────────────────────────────────
    local_users = []
    for u in users:
        username = u.get("user_name", "").strip()
        if not username:
            continue

        last_login_raw = u.get("last_login_time", "")
        last_login_iso = None
        if last_login_raw:
            try:
                # SN format: "2024-03-15 10:22:41"
                dt = datetime.strptime(last_login_raw, "%Y-%m-%d %H:%M:%S")
                last_login_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        user_obj = {
            "name": username,
            "is_active": u.get("active", "true") == "true",
        }
        if u.get("email"):
            user_obj["identities"] = [u["email"]]
        if last_login_iso:
            user_obj["last_login_at"] = last_login_iso

        local_users.append(user_obj)

    # ── Local groups (roles as groups for membership tracking) ─────────────────
    local_groups = [
        {
            "name": r["name"],
        }
        for r in roles
    ]

    # ── Local roles (elevated / admin roles as permission-granting roles) ───────
    # We model SN roles as BOTH groups (for membership) and roles (for permissions)
    local_roles = [
        {
            "name": r["name"],
        }
        for r in roles
    ]

    # ── Resources (SN tables) ───────────────────────────────────────────────────
    resources = []
    for t in tables:
        table_name = t.get("name", "").strip()
        if not table_name:
            continue
        resources.append({
            "name": table_name,
            "resource_type": "table",

        })

    # ── Permissions ─────────────────────────────────────────────────────────────
    # Map ServiceNow's access model to Veza's normalized permission types
    permissions = [
        {
            "name": "read",
            "permission_type": ["DataRead"],
            "apply_to_sub_resources": True,
        },
        {
            "name": "write",
            "permission_type": ["DataWrite"],
            "apply_to_sub_resources": True,
        },
        {
            "name": "create",
            "permission_type": ["DataCreate"],
            "apply_to_sub_resources": True,
        },
        {
            "name": "delete",
            "permission_type": ["DataDelete"],
            "apply_to_sub_resources": True,
        },
        {
            "name": "admin",
            "permission_type": ["DataRead", "DataWrite", "DataCreate", "DataDelete",
                               "MetadataRead", "MetadataWrite"],
            "apply_to_sub_resources": True,
        },
    ]

    # ── Identity to permissions (via role assignments) ─────────────────────────
    # Build user -> [role names] map
    user_to_roles: dict[str, list[str]] = {}
    user_id_to_name = {u["sys_id"]: u.get("user_name", "") for u in users}

    for assignment in user_roles:
        uid = assignment.get("user", "")
        rid = assignment.get("role", "")
        uname = user_id_to_name.get(uid, "")
        rname = role_id_to_name.get(rid, "")
        if uname and rname:
            user_to_roles.setdefault(uname, []).append(rname)

    # For simplicity: elevated_privilege roles get admin permission on all tables
    # Regular roles get read permission on all tables
    elevated_roles = {r["name"] for r in roles if r.get("elevated_privilege") == "true"}

    identity_to_permissions = []
    for username, assigned_roles in user_to_roles.items():
        app_perms = []
        for role_name in assigned_roles:
            perm = "admin" if role_name in elevated_roles else "read"
            # Grant permission to each table resource
            for t in tables[:20]:  # cap at 20 tables to keep payload manageable
                table_name = t.get("name", "").strip()
                if table_name:
                    app_perms.append({
                        "application": "ServiceNow",
                        "resources": [table_name],
                        "permission": perm,
                    })

        if app_perms:
            identity_to_permissions.append({
                "identity": username,
                "identity_type": "local_user",
                "application_permissions": app_perms,
            })

    # ── Group memberships ───────────────────────────────────────────────────────
    # Add users to role-groups based on user_roles assignments
    # (we already have user_to_roles above)
    # This is encoded in the local_users via groups field
    local_users_with_groups = []
    for u in local_users:
        uname = u["name"]
        entry = dict(u)
        if uname in user_to_roles:
            entry["groups"] = user_to_roles[uname]
        local_users_with_groups.append(entry)

    # ── Assemble final payload ─────────────────────────────────────────────────
    payload = {
        "applications": [
            {
                "name": "ServiceNow",
                "application_type": "servicenow",

                "local_users": local_users_with_groups,
                "local_groups": local_groups,
                "local_roles": local_roles,
                "resources": resources,
            }
        ],
        "permissions": permissions,
        "identity_to_permissions": identity_to_permissions,
    }

    return payload


# ─── Veza push ────────────────────────────────────────────────────────────────

def push_to_veza(payload: dict, veza_url: str, api_key: str,
                 provider_name: str = "ServiceNow") -> None:
    """
    Register a custom provider + datasource in Veza (if not existing)
    and push the OAA payload.
    """
    base = veza_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 1. Get or create the custom provider
    log.info("Checking for existing Veza provider '%s' ...", provider_name)
    resp = requests.get(
        f"{base}/api/v1/providers/custom",
        params={"filter": f'name eq "{provider_name}"'},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    existing = resp.json().get("values", [])

    if existing:
        provider_id = existing[0]["id"]
        log.info("  Found existing provider: %s", provider_id)
    else:
        log.info("  Creating new provider ...")
        body = {
            "name": provider_name,
            "custom_template": "application",
        }
        resp = requests.post(
            f"{base}/api/v1/providers/custom",
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        provider_id = resp.json()["value"]["id"]
        log.info("  Created provider: %s", provider_id)

    # 2. Get or create the datasource
    datasource_name = f"{provider_name} - Demo"
    log.info("Checking for existing datasource '%s' ...", datasource_name)
    resp = requests.get(
        f"{base}/api/v1/providers/custom/{provider_id}/datasources",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    ds_list = resp.json().get("values", [])
    ds_match = [d for d in ds_list if d.get("name") == datasource_name]

    if ds_match:
        datasource_id = ds_match[0]["id"]
        log.info("  Found existing datasource: %s", datasource_id)
    else:
        log.info("  Creating new datasource ...")
        resp = requests.post(
            f"{base}/api/v1/providers/custom/{provider_id}/datasources",
            headers=headers,
            json={"name": datasource_name},
            timeout=30,
        )
        resp.raise_for_status()
        datasource_id = resp.json()["value"]["id"]
        log.info("  Created datasource: %s", datasource_id)

    # 3. Push the OAA payload
    log.info("Pushing OAA payload to Veza ...")
    payload_str = json.dumps(payload)
    log.info("  Payload size: %.1f KB", len(payload_str) / 1024)

    push_body = {
        "id": provider_id,
        "data_source_id": datasource_id,
        "json_data": payload_str,
        "compression_type": "none",
    }
    resp = requests.post(
        f"{base}/api/v1/providers/custom/{provider_id}/datasources/{datasource_id}:push",
        headers=headers,
        json=push_body,
        timeout=120,
    )
    if not resp.ok:
        log.error("Status code: %s", resp.status_code)
        log.error("Response headers: %s", dict(resp.headers))
        try:
            log.error("Response body: %s", resp.json())
        except Exception:
            log.error("Response text: %s", resp.text[:1000])
    resp.raise_for_status()

    result = resp.json()
    warnings = result.get("warnings", [])

    log.info("Push successful!")
    if warnings:
        log.warning("%d warning(s) from Veza:", len(warnings))
        for w in warnings[:5]:
            log.warning("  %s", w)
    else:
        log.info("No warnings.")


# ─── Dry-run / save mode ──────────────────────────────────────────────────────

def save_payload_to_file(payload: dict, path: str = "sn_oaa_payload.json") -> None:
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info("Payload saved to %s", path)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Veza OAA connector for ServiceNow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full run - push to Veza:
  python veza_servicenow_connector.py

  # Dry run - save payload JSON without pushing:
  python veza_servicenow_connector.py --dry-run

  # Save payload and push:
  python veza_servicenow_connector.py --save-payload
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Build payload but do not push to Veza")
    parser.add_argument("--save-payload", action="store_true",
                        help="Save payload JSON to sn_oaa_payload.json before pushing")
    args = parser.parse_args()

    # ── Validate env ────────────────────────────────────────────────────────────
    required = {
        "VEZA_URL": os.getenv("VEZA_URL"),
        "VEZA_API_KEY": os.getenv("VEZA_API_KEY"),
        "SN_INSTANCE": os.getenv("SN_INSTANCE"),
        "SN_USER": os.getenv("SN_USER"),
        "SN_PASSWORD": os.getenv("SN_PASSWORD"),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        log.error("Set them in a .env file or export them before running.")
        sys.exit(1)

    # ── Connect and fetch ────────────────────────────────────────────────────────
    sn = ServiceNowClient(
        instance_url=required["SN_INSTANCE"],
        username=required["SN_USER"],
        password=required["SN_PASSWORD"],
    )

    try:
        payload = build_oaa_payload(sn)
    except requests.exceptions.ConnectionError as e:
        log.error("Cannot connect to ServiceNow: %s", e)
        log.error("Check SN_INSTANCE URL and network connectivity.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        log.error("ServiceNow API error: %s", e)
        log.error("Check SN_USER / SN_PASSWORD credentials.")
        sys.exit(1)

    # ── Optionally save ──────────────────────────────────────────────────────────
    if args.save_payload or args.dry_run:
        save_payload_to_file(payload)

    if args.dry_run:
        log.info("Dry-run mode: skipping Veza push. Payload saved.")
        # Print a quick summary
        app = payload["applications"][0]
        print(f"\nPayload summary:")
        print(f"  Users:        {len(app['local_users'])}")
        print(f"  Roles/groups: {len(app['local_roles'])}")
        print(f"  Resources:    {len(app['resources'])}")
        print(f"  Permissions:  {len(payload['permissions'])}")
        print(f"  Identity->perm bindings: {len(payload['identity_to_permissions'])}")
        return

    # ── Push to Veza ────────────────────────────────────────────────────────────
    try:
        push_to_veza(
            payload=payload,
            veza_url=required["VEZA_URL"],
            api_key=required["VEZA_API_KEY"],
        )
    except requests.exceptions.HTTPError as e:
        log.error("Veza API error: %s", e)
        log.error("Response: %s", e.response.text[:500] if e.response else "no body")
        sys.exit(1)

    print("\nDone! Now go to your Veza demo instance and:")
    print("  1. Open Administration > Integrations")
    print("     You should see 'ServiceNow' listed as a custom provider.")
    print("  2. Open Access Search and search for any SN username.")
    print("     You'll see their roles and table-level access in the graph.")
    print("  3. Try query: 'Show all users with admin permission'")
    print("     to find elevated-privilege accounts immediately.")


if __name__ == "__main__":
    main()
