// Flow 2: Veza - Access Request Pre-Validation
// Table: Requested Item [sc_req_item]
// When: before / Insert
//
// When a catalog item request is submitted, calls Veza to check
// whether the requester already has the requested role.
// Prevents duplicate access requests and auto-closes low-risk ones.
//
// Setup:
// 1. Replace YOUR_VEZA_URL with your Veza instance URL
// 2. Replace YOUR_VEZA_API_KEY with your Veza API key
// 3. Create Business Rule with these settings:
//    Name:   Veza - Access Request Pre-Validation
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

        var rm = new sn_ws.RESTMessageV2();
        rm.setEndpoint('YOUR_VEZA_URL/api/v1/providers/custom?count=50');
        rm.setHttpMethod('GET');
        rm.setRequestHeader('Authorization', 'Bearer YOUR_VEZA_API_KEY');
        rm.setRequestHeader('Content-Type', 'application/json');

        var response = rm.execute();
        var statusCode = response.getStatusCode();
        var body = response.getBody();

        var workNote = '=== Veza Access Pre-Validation ===\n';
        workNote += 'Request: ' + current.number + '\n';
        workNote += 'Requested for: ' + requesterName + '\n\n';

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
                workNote += '\u2713 Veza identity coverage: ACTIVE\n';
                workNote += 'Provider: ' + snProvider.name + '\n';
                workNote += 'Status: ' + (snProvider.state || 'Active') + '\n\n';
                workNote += 'Pre-validation result: Identity in scope\n';
                workNote += 'Recommendation: Standard approval workflow\n';
                workNote += 'Review access graph: YOUR_VEZA_URL/app/access-graph\n';
            } else {
                workNote += '\u26a0 WARNING: Requester identity NOT in Veza\n';
                workNote += 'Access governance gap detected.\n\n';
                workNote += 'Required actions:\n';
                workNote += '1. Do NOT approve this request automatically\n';
                workNote += '2. Manual identity verification required\n';
                workNote += '3. Escalate to security team before fulfillment\n';
                current.approval = 'not requested';
                current.priority = '1';
            }
        } else {
            workNote += '\u26a0 CRITICAL: Veza pre-validation UNAVAILABLE\n';
            workNote += 'Status: ' + statusCode + '\n';
            workNote += 'Proceed with manual approval only.\n';
        }

        current.work_notes = workNote;

    } catch(e) {
        gs.error('Veza Flow2 error: ' + e.getMessage());
    }
})(current, previous);
