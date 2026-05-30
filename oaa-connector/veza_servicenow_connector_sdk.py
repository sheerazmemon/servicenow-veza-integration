#!/usr/bin/env python3
"""
Veza OAA Connector for ServiceNow — SDK Version
=================================================
Same functionality as veza_servicenow_connector.py
but uses the official oaaclient Python SDK instead
of raw HTTP calls.

This is the production-grade pattern used by connectors
in the Veza oaa-community repo.

SETUP:
    pip install oaaclient requests python-dotenv

ENVIRONMENT VARIABLES:
    VEZA_URL        = https://your-demo.veza.com
    VEZA_API_KEY    = your-api-key
    SN_INSTANCE     = https://your-instance.service-now.com
    SN_USER         = your-sn-username
    SN_PASSWORD     = your-sn-password

USAGE:
    python3 veza_servicenow_connector_sdk.py
    python3 veza_servicenow_connector_sdk.py --dry-run
"""

import os
import sys
import json
import logging
import argparse

import requests
from dotenv import load_dotenv
from oaaclient.client import OAAClient, OAAClientError
from oaaclient.templates import CustomApplication, OAAPermission

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("veza-sn-sdk")

# ─── ServiceNow client (unchanged from raw version) ───────────────────────────

class ServiceNowClient:
    def __init__(self, instance_url, username, password):
        self.base = instance_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _get(self, table, params=None):
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
            log.info("  fetched %d records from %s ...", len(records), table)

        return records

    def get_users(self):
        log.info("Fetching active users from ServiceNow ...")
        return self._get("sys_user", {
            "sysparm_query": "active=true",
            "sysparm_fields": "sys_id,user_name,email,active,last_login_time",
        })

    def get_roles(self):
        log.info("Fetching roles from ServiceNow ...")
        return self._get("sys_user_role", {
            "sysparm_fields": "sys_id,name,elevated_privilege",
        })

    def get_user_roles(self):
        log.info("Fetching user-role assignments from ServiceNow ...")
        return self._get("sys_user_has_role", {
            "sysparm_fields": "user,role,inherited",
        })

    def get_tables(self, max_tables=60):
        log.info("Fetching tables from ServiceNow ...")
        return self._get("sys_db_object", {
            "sysparm_query": "sys_package.active=true^super_class=NULL",
            "sysparm_fields": "name,label,sys_scope",
            "sysparm_limit": max_tables,
        })


# ─── Build OAA payload using SDK ──────────────────────────────────────────────

def build_oaa_app(sn: ServiceNowClient) -> CustomApplication:
    """
    Fetch SN data and populate a CustomApplication object
    using the oaaclient SDK. This replaces the manual JSON
    payload construction in the raw version.
    """

    users      = sn.get_users()
    roles      = sn.get_roles()
    user_roles = sn.get_user_roles()
    tables     = sn.get_tables(max_tables=60)

    log.info("Building OAA app: %d users, %d roles, %d assignments, %d tables",
             len(users), len(roles), len(user_roles), len(tables))

    # ── Initialize CustomApplication ──────────────────────────────────────────
    # This replaces the manual {"applications": [...]} dict construction
    app = CustomApplication(
        name="ServiceNow",
        application_type="servicenow",
    )

    # ── Define permissions ─────────────────────────────────────────────────────
    # SDK uses add_permission() instead of a manual permissions list
    app.add_custom_permission("read",   [OAAPermission.DataRead],   apply_to_sub_resources=True)
    app.add_custom_permission("write",  [OAAPermission.DataWrite],  apply_to_sub_resources=True)
    app.add_custom_permission("create", [OAAPermission.DataCreate], apply_to_sub_resources=True)
    app.add_custom_permission("delete", [OAAPermission.DataDelete], apply_to_sub_resources=True)
    app.add_custom_permission("admin",  [
        OAAPermission.DataRead, OAAPermission.DataWrite,
        OAAPermission.DataCreate, OAAPermission.DataDelete,
        OAAPermission.MetadataRead, OAAPermission.MetadataWrite,
    ], apply_to_sub_resources=True)

    # ── Add resources (SN tables) ──────────────────────────────────────────────
    # SDK uses add_resource() instead of building resource dicts
    for t in tables:
        table_name = t.get("name", "").strip()
        if table_name:
            app.add_resource(
                name=table_name,
                resource_type="table",
            )

    # ── Add local roles ────────────────────────────────────────────────────────
    # SDK uses add_local_role() instead of building role dicts
    role_id_to_name = {}
    elevated_roles  = set()

    for r in roles:
        role_name = r.get("name", "").strip()
        if not role_name:
            continue
        role_id_to_name[r["sys_id"]] = role_name
        app.add_local_role(role_name)
        if r.get("elevated_privilege") == "true":
            elevated_roles.add(role_name)

    # ── Add local groups (roles as groups for membership) ──────────────────────
    for r in roles:
        role_name = r.get("name", "").strip()
        if role_name:
            app.add_local_group(role_name)

    # ── Build user → role map ──────────────────────────────────────────────────
    user_id_to_name = {u["sys_id"]: u.get("user_name", "") for u in users}
    user_to_roles: dict = {}

    for assignment in user_roles:
        uid   = assignment.get("user", "")
        rid   = assignment.get("role", "")
        uname = user_id_to_name.get(uid, "")
        rname = role_id_to_name.get(rid, "")
        if uname and rname:
            user_to_roles.setdefault(uname, []).append(rname)

    # ── Add local users ────────────────────────────────────────────────────────
    # SDK uses add_local_user() instead of building user dicts
    for u in users:
        username = u.get("user_name", "").strip()
        if not username:
            continue

        user = app.add_local_user(
            name=username,
            identities=[u["email"]] if u.get("email") else [],
        )
        user.is_active = u.get("active", "true") == "true"

        # Add group memberships
        for role_name in user_to_roles.get(username, []):
            user.add_group(role_name)

        # Add permissions on tables via roles
        for role_name in user_to_roles.get(username, []):
            perm = "admin" if role_name in elevated_roles else "read"
            for t in tables[:20]:
                table_name = t.get("name", "").strip()
                if table_name and table_name in app.resources:
                    user.add_permission(
                        permission=perm,
                        resources=[app.resources[table_name]],
                    )

    log.info("OAA app built successfully")
    return app


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Veza OAA connector for ServiceNow — SDK version"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Build app object but do not push to Veza")
    args = parser.parse_args()

    # ── Validate env ────────────────────────────────────────────────────────────
    required = {
        "VEZA_URL":     os.getenv("VEZA_URL"),
        "VEZA_API_KEY": os.getenv("VEZA_API_KEY"),
        "SN_INSTANCE":  os.getenv("SN_INSTANCE"),
        "SN_USER":      os.getenv("SN_USER"),
        "SN_PASSWORD":  os.getenv("SN_PASSWORD"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        log.error("Missing environment variables: %s", ", ".join(missing))
        sys.exit(1)

    # ── Connect to ServiceNow ───────────────────────────────────────────────────
    sn = ServiceNowClient(
        instance_url=required["SN_INSTANCE"],
        username=required["SN_USER"],
        password=required["SN_PASSWORD"],
    )

    # ── Build OAA app using SDK ─────────────────────────────────────────────────
    try:
        app = build_oaa_app(sn)
    except requests.exceptions.ConnectionError as e:
        log.error("Cannot connect to ServiceNow: %s", e)
        sys.exit(1)

    # ── Dry run ─────────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("Dry-run mode: skipping Veza push.")
        payload = app.get_payload()
        print(f"\nPayload summary:")
        print(f"  Users:     {len(payload['applications'][0].get('local_users', []))}")
        print(f"  Roles:     {len(payload['applications'][0].get('local_roles', []))}")
        print(f"  Resources: {len(payload['applications'][0].get('resources', []))}")
        return

    # ── Push to Veza using SDK ──────────────────────────────────────────────────
    # This replaces ALL the manual provider/datasource/push logic
    # from the raw version — one method call handles everything
    try:
        log.info("Connecting to Veza ...")
        veza_con = OAAClient(
            url=required["VEZA_URL"],
            token=required["VEZA_API_KEY"],
        )

        log.info("Pushing to Veza ...")
        response = veza_con.push_application(
            provider_name="ServiceNow",
            data_source_name="ServiceNow - Demo",
            application_object=app,
            create_provider=True,
        )

        if response.get("warnings"):
            log.warning("%d warning(s):", len(response["warnings"]))
            for w in response["warnings"][:5]:
                log.warning("  %s", w)
        else:
            log.info("Push successful — no warnings.")

    except OAAClientError as e:
        log.error("Veza SDK error: %s", e)
        sys.exit(1)

    print("\nDone! ServiceNow data is live in your Veza Access Graph.")
    print(f"  Graph: {required['VEZA_URL']}/app/access-graph")


if __name__ == "__main__":
    main()
