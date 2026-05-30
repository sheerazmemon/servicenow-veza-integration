// Veza Alert Receiver — Scripted REST API
// Namespace: x_snc_veza_alert_r
// API Name:  veza_alert_receiver
// Resource:  /alert
// Method:    POST
//
// Receives inbound webhook payloads from Veza Event Subscriptions
// and auto-creates a Priority 1 incident in ServiceNow.
//
// Setup:
// 1. In ServiceNow: System Web Services > Scripted REST APIs > New
//    Name:      veza_alert_receiver
//    API ID:    veza_alert_receiver
// 2. Add Resource:
//    Name:      alert
//    HTTP Method: POST
//    Script:    paste this file
// 3. Copy the endpoint URL shown after saving — use it in Veza
//    as the webhook target for your Event Subscription.

(function process(request, response) {
    try {
        var body = request.body.dataString;
        var payload = {};

        if (body) {
            payload = JSON.parse(body);
        }

        // Extract fields from Veza webhook payload
        var eventType  = payload.event_type  || 'Unknown Event';
        var entityName = payload.entity_name || 'Unknown Entity';
        var severity   = payload.severity    || 'HIGH';
        var detail     = payload.detail      || 'No additional detail provided';
        var vezaUrl    = payload.veza_url    || 'YOUR_VEZA_URL/app/access-graph';

        // Create the incident
        var inc = new GlideRecord('incident');
        inc.initialize();
        inc.short_description = '[Veza Alert] ' + eventType + ' — ' + entityName;
        inc.description =
            'Veza Event Subscription triggered this incident automatically.\n\n' +
            'Event Type : ' + eventType + '\n' +
            'Entity     : ' + entityName + '\n' +
            'Severity   : ' + severity + '\n' +
            'Detail     : ' + detail + '\n\n' +
            'Review in Veza: ' + vezaUrl;
        inc.priority  = '1';
        inc.urgency   = '1';
        inc.impact    = '1';
        inc.category  = 'Security';
        inc.work_notes =
            '=== Auto-created by Veza Event Subscription ===\n' +
            'This incident was opened autonomously by Veza detecting a risk threshold.\n\n' +
            'Event : ' + eventType + '\n' +
            'Entity: ' + entityName + '\n' +
            'Link  : ' + vezaUrl + '\n\n' +
            'No human initiated this — Veza fired the webhook directly.';

        var sysId = inc.insert();

        response.setStatus(200);
        response.setBody({
            status:  'created',
            sys_id:  sysId,
            number:  inc.getValue('number'),
            message: 'Incident created by Veza alert receiver'
        });

    } catch(e) {
        gs.error('Veza alert receiver error: ' + e.getMessage());
        response.setStatus(500);
        response.setBody({
            status:  'error',
            message: e.getMessage()
        });
    }
})(request, response);
