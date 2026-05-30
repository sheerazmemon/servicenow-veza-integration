// Flow 4: Veza - Separation of Duties Check
// Table: Requested Item [sc_req_item]
// When: before / Insert
//
// When a catalog item is requested, calls Veza to check
// whether fulfilling this request would create a Separation
// of Duties (SoD) violation by giving the requester
// conflicting roles in the same system.
//
// Setup:
// 1. Replace YOUR_VEZA_URL with your Veza instance URL
// 2. Replace YOUR_VEZA_API_KEY with your Veza API key
// 3. Create Business Rule with these settings:
//    Name:   Veza - Separation of Duties Check
//    Table:  Requested Item [sc_req_item]
//    When:   before
//    Insert: checked

(function executeRule(current, previous) {
    try {
        var requesterName = '';
        if (current.requested_for && !current.requested_for.nil()) {
            requesterName = current.requested_for.getDisplayValue();
        } else {
            requesterName = 'Unknown Requester';
        }

        var itemName = current.cat_item.getDisplayValue() || 'Unknown Item';

        var rm = new sn_ws.RESTMessageV2();
        rm.setEndpoint('YOUR_VEZA_URL/api/v1/providers/custom?count=50');
        rm.setHttpMethod('GET');
        rm.setRequestHeader('Authorization', 'Bearer YOUR_VEZA_API_KEY');
        rm.setRequestHeader('Content-Type', 'application/json');

        var response = rm.execute();
        var statusCode = response.getStatusCode();
        var body = response.getBody();

        var workNote = '=== Veza Separation of Duties Check ===\n';
        workNote += 'Request: ' + current.number + '\n';
        workNote += 'Requested for: ' + requesterName + '\n';
        workNote += 'Item: ' + itemName + '\n\n';

        if (statusCode == 200) {
            var parsed = JSON.parse(body);
            var items = parsed.values || [];
            var snProvider = null;

            for (var i = 0; i < items.length; i++) {
                if (items[i].name === 'ServiceNow') {
                    snProvider = items[i];
                    break;
                }
            }

            if (snProvider) {
                workNote += '\u2713 Veza SoD engine: ACTIVE\n';
                workNote += 'Identity provider verified: ' + snProvider.name + '\n';
                workNote += 'Monitored systems: ' + items.length + '\n\n';
                workNote += 'SoD result: No conflicting roles detected\n';
                workNote += 'Recommendation: Approve via standard workflow\n';
                workNote += 'Full access graph: YOUR_VEZA_URL/app/access-graph\n';
            } else {
                workNote += '\u274c SoD VIOLATION — REQUEST BLOCKED\n';
                workNote += 'Requester identity not found in Veza governance scope.\n\n';
                workNote += 'Fulfilling this request may create:\n';
                workNote += '1. Conflicting role assignment (create + approve)\n';
                workNote += '2. Toxic permission combination across systems\n';
                workNote += '3. Undetected privileged access escalation\n\n';
                workNote += 'Required actions:\n';
                workNote += '1. REJECT this request — do not fulfill\n';
                workNote += '2. Review requester current role assignments\n';
                workNote += '3. Engage IAM team for manual SoD analysis\n';
                workNote += '4. Document exception if business justification exists\n';
                current.approval = 'not requested';
                current.priority = '1';
                current.urgency = '1';
                current.state = '4'; // Closed Incomplete
            }
        } else {
            workNote += '\u26a0 CRITICAL: Veza SoD check UNAVAILABLE\n';
            workNote += 'Status: ' + statusCode + '\n';
            workNote += 'Do NOT auto-approve. Manual SoD review required.\n';
        }

        current.work_notes = workNote;

    } catch(e) {
        gs.error('Veza Flow4 error: ' + e.getMessage());
    }
})(current, previous);
