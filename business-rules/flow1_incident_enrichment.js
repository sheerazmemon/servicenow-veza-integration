// Flow 1: Veza - Incident Risk Enrichment
// Table:   Incident [incident]
// When:    before / Insert
//
// When an incident is created, calls Veza to verify
// identity coverage and writes risk intelligence
// to the incident work notes automatically.
//
// Setup:
//   1. Replace YOUR_VEZA_URL with your Veza instance URL
//   2. Replace YOUR_VEZA_API_KEY with your Veza API key
//   3. Create Business Rule with these settings:
//      Name:   Veza - Incident Risk Enrichment
//      Table:  Incident [incident]
//      When:   before
//      Insert: checked

(function executeRule(current, previous) {
    try {
        var callerName = '';
        if (current.caller_id && !current.caller_id.nil()) {
            callerName = current.caller_id.getDisplayValue();
        } else {
            callerName = 'Unknown Caller';
        }

        var rm = new sn_ws.RESTMessageV2();
        rm.setEndpoint('YOUR_VEZA_URL/api/v1/providers/custom?count=50');
        rm.setHttpMethod('GET');
        rm.setRequestHeader('Authorization', 'Bearer YOUR_VEZA_API_KEY');
        rm.setRequestHeader('Content-Type', 'application/json');

        var response = rm.execute();
        var statusCode = response.getStatusCode();
        var body = response.getBody();

        var workNote = '=== Veza Identity Risk Intelligence ===\n';
        workNote += 'Incident: ' + current.number + '\n';
        workNote += 'Caller: ' + callerName + '\n\n';

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
                workNote += '\u2713 ServiceNow identity provider: VERIFIED IN VEZA\n';
                workNote += 'Provider ID: ' + snProvider.id + '\n';
                workNote += 'Status: ' + (snProvider.state || 'Active') + '\n';
                workNote += 'Total monitored providers: ' + items.length + '\n\n';
                workNote += 'Action: Review caller permissions in Veza graph\n';
                workNote += 'Search "' + callerName + '" in Veza: YOUR_VEZA_URL/app/access-graph\n';
            } else {
                workNote += '\u26a0 WARNING: ServiceNow NOT found in Veza\n';
                workNote += 'This system has NO identity coverage in Veza.\n\n';
                workNote += 'Risk: Caller permissions cannot be verified.\n';
                workNote += 'Risk: Access governance blind spot detected.\n\n';
                workNote += 'Recommended actions:\n';
                workNote += '1. Deploy Veza OAA connector for ServiceNow\n';
                workNote += '2. Escalate to security team immediately\n';
                workNote += '3. Manually verify caller access before proceeding\n\n';
                workNote += 'Veza Graph: YOUR_VEZA_URL/app/access-graph\n';
                current.priority = '1';
                current.urgency = '1';
                current.impact = '1';
            }
        } else {
            workNote += '\u26a0 CRITICAL: Cannot reach Veza API\n';
            workNote += 'Status: ' + statusCode + '\n';
            workNote += 'Identity risk verification UNAVAILABLE.\n';
        }

        current.work_notes = workNote;

    } catch(e) {
        gs.error('Veza BR error: ' + e.getMessage());
    }
})(current, previous);
