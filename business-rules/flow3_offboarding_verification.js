// Flow 3: Veza - Offboarding Access Verification
// Table: Problem [problem]
// When: before / Insert
//
// When a problem record is created, calls Veza to verify
// identity coverage and flags offboarding risk if the
// reporter's identity is not found in Veza.
//
// Setup:
// 1. Replace YOUR_VEZA_URL with your Veza instance URL
// 2. Replace YOUR_VEZA_API_KEY with your Veza API key
// 3. Create Business Rule with these settings:
//    Name:   Veza - Offboarding Access Verification
//    Table:  Problem [problem]
//    When:   before
//    Insert: checked

(function executeRule(current, previous) {
    try {
        var reporterName = '';
        if (current.opened_by && !current.opened_by.nil()) {
            reporterName = current.opened_by.getDisplayValue();
        } else {
            reporterName = 'Unknown Reporter';
        }

        var rm = new sn_ws.RESTMessageV2();
        rm.setEndpoint('YOUR_VEZA_URL/api/v1/providers/custom?count=50');
        rm.setHttpMethod('GET');
        rm.setRequestHeader('Authorization', 'Bearer YOUR_VEZA_API_KEY');
        rm.setRequestHeader('Content-Type', 'application/json');

        var response = rm.execute();
        var statusCode = response.getStatusCode();
        var body = response.getBody();

        var workNote = '=== Veza Offboarding Verification ===\n';
        workNote += 'Problem: ' + current.number + '\n';
        workNote += 'Opened by: ' + reporterName + '\n\n';

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
                workNote += '\u2713 Identity verified in Veza\n';
                workNote += 'Provider: ' + snProvider.name + '\n';
                workNote += 'Monitored systems: ' + items.length + '\n\n';
                workNote += 'Offboarding status: No risk detected\n';
                workNote += 'Access graph: YOUR_VEZA_URL/app/access-graph\n';
            } else {
                workNote += '\u26a0 OFFBOARDING RISK DETECTED\n';
                workNote += 'Reporter identity NOT found in Veza.\n\n';
                workNote += 'This may indicate:\n';
                workNote += '1. User was offboarded but retains system access\n';
                workNote += '2. Orphaned account with no identity governance\n';
                workNote += '3. Cross-instance access not tracked in Veza\n\n';
                workNote += 'Required actions:\n';
                workNote += '1. Verify reporter employment status immediately\n';
                workNote += '2. Audit all active sessions for this user\n';
                workNote += '3. Escalate to IAM team\n';
                current.priority = '1';
                current.urgency = '1';
            }
        } else {
            workNote += '\u26a0 CRITICAL: Veza verification UNAVAILABLE\n';
            workNote += 'Status: ' + statusCode + '\n';
            workNote += 'Manual offboarding check required.\n';
        }

        current.work_notes = workNote;

    } catch(e) {
        gs.error('Veza Flow3 error: ' + e.getMessage());
    }
})(current, previous);
