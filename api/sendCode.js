export default async function handler(req, res) {
    if (req.method === 'POST') {
        const { code } = req.body;

        if (!code) {
            return res.status(400).json({ success: false, message: 'Authorization code is required' });
        }

        try {
            const fetch = (await import('node-fetch')).default;

            const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;
            const clientId = process.env.STRAVA_CLIENT_ID;
            const clientSecret = process.env.STRAVA_CLIENT_SECRET;

            if (!webhookUrl || !clientId || !clientSecret) {
                return res.status(500).json({ success: false, message: 'Missing environment variables' });
            }

            const payload = {
                code,
                client_id: clientId,
                client_secret: clientSecret,
                conversationId: 'conv_01J82N4J2B67NMC1TA2MR198RF'
            };

            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            // Log response details
            console.log('Response Status:', response.status);
            console.log('Response Headers:', response.headers.raw());

            // Check if the response is OK
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }

            // Check if the response has a body and parse it
            const contentType = response.headers.get('Content-Type');
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                res.status(200).json({ success: true, data });
            } else {
                // Handle non-JSON responses
                const text = await response.text();
                res.status(200).json({ success: true, data: text });
            }
        } catch (error) {
            console.error('Error:', error); // Log the error to the server logs
            res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error: error.message });
        }
    } else {
        res.status(405).json({ success: false, message: 'Method not allowed' });
    }
}
